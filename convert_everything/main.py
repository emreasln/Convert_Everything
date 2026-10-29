"""Convert Everything: the windows behind the right-click menu.

    ConvertEverything                      install / uninstall window (what a double-click opens)
    ConvertEverything [--to FMT] FILE...   convert files (what the right-click menu runs)
    ConvertEverything --install            install without asking
    ConvertEverything --uninstall          remove (used by Windows "Installed apps")
    ConvertEverything --self-test          check the packaged app can convert (used by the release build)
"""
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import installer
from converters import ConversionError, MissingTool, convert, targets_for

APP = "Convert Everything"
TRASH = "Recycle Bin" if sys.platform == "win32" else "Trash"
REPLACE = "Replace original"
SPOOL = Path(tempfile.gettempdir()) / "convert-everything"
WHERE = {
    "win32": "\n\nOn Windows 11, click “Show more options” first (or Shift + right-click).",
    "darwin": "\n\nIn Finder, it's under Quick Actions.",
}.get(sys.platform, "")


def gather(path, target):
    """Windows Explorer starts one process per selected file. The first process
    collects everyone's file and converts them all; the others exit quietly.
    Returns the files this process should handle (empty for the others)."""
    spool = SPOOL / target
    spool.mkdir(parents=True, exist_ok=True)
    fd, mine = tempfile.mkstemp(dir=spool, suffix=".path")
    os.write(fd, str(path).encode("utf-8"))
    os.close(fd)
    mine, lock = Path(mine), spool / "lock"

    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
            break
        except FileExistsError:
            time.sleep(0.2)
            if not mine.exists():
                return []  # the collecting process took our file
            try:
                if time.time() - lock.stat().st_mtime > 10:
                    lock.unlink()  # left over from a crash
            except OSError:
                pass

    try:
        files, seen = [], -1
        while len(files) != seen:  # wait until Explorer stops starting new processes
            seen = len(files)
            time.sleep(0.6)
            files = sorted(spool.glob("*.path"))
        paths = []
        for f in files:
            paths.append(Path(f.read_text(encoding="utf-8")))
            f.unlink()
    finally:
        lock.unlink()
    return sorted(paths)


def _show(win):
    """Center a window (created hidden by _window) on the screen, then show it."""
    win.update_idletasks()
    x = (win.winfo_screenwidth() - win.winfo_reqwidth()) // 2
    y = (win.winfo_screenheight() - win.winfo_reqheight()) // 2
    win.geometry(f"+{x}+{y}")
    win.deiconify()
    win.lift()
    win.focus_force()


def _window(root):
    win = tk.Toplevel(root)
    win.withdraw()  # once a window is on screen, Windows ignores our position; place it first
    win.title(APP)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    frame = ttk.Frame(win, padding=16)
    frame.pack()
    return win, frame


def ask(root, message, buttons):
    """Small modal dialog. Returns the clicked button's label, or None if closed."""
    win, frame = _window(root)
    ttk.Label(frame, text=message, wraplength=380, justify="left").grid(
        row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
    choice = []
    for i, label in enumerate(buttons):
        ttk.Button(frame, text=label, command=lambda l=label: (choice.append(l), win.destroy())).grid(
            row=1 + i // 4, column=i % 4, padx=3, pady=3, sticky="ew")
    _show(win)
    root.wait_window(win)
    return choice[0] if choice else None


def run_with_progress(root, text, work):
    """Run work(status) in the background behind a small progress window. `work` may
    update status["text"]. Returns what work returns, or raises what it raised."""
    win, frame = _window(root)
    label = ttk.Label(frame, text=text, width=50)
    label.pack(anchor="w")
    bar = ttk.Progressbar(frame, mode="indeterminate", length=340)
    bar.pack(pady=(10, 0))
    bar.start(15)
    win.protocol("WM_DELETE_WINDOW", lambda: None)  # the work can't be stopped halfway

    status, result = {"text": text}, {}

    def run():
        try:
            result["value"] = work(status)
        except Exception as e:
            result["error"] = e

    worker = threading.Thread(target=run, daemon=True)
    worker.start()

    def poll():
        label.config(text=status["text"])
        if worker.is_alive():
            win.after(100, poll)
        else:
            win.destroy()

    _show(win)
    win.after(100, poll)
    root.wait_window(win)
    if "error" in result:
        raise result["error"]
    return result["value"]


def _describe(err):
    return str(err) if isinstance(err, ConversionError) else f"{type(err).__name__}: {err}"


def _plan(files, target, folder):
    """Destination for each file; avoids two inputs (a.png, a.jpg) writing the same output."""
    jobs, used = [], set()
    for src in files:
        dst = (folder or src.parent) / f"{src.stem}.{target}"
        if dst in used:
            dst = dst.with_name(f"{src.stem}-{src.suffix[1:]}.{target}")
        used.add(dst)
        jobs.append((src, dst))
    return jobs


def setup_window(root):
    if installer.is_installed():
        message = f"{APP} is installed.\n\nRight-click any file and choose Convert.{WHERE}"
        buttons = ["Uninstall", "Close"] if installer.running_installed_copy() else ["Reinstall", "Uninstall", "Close"]
    else:
        message = (f"Install {APP}?\n\nIt adds Convert to the right-click menu of your files. "
                   f"Files are converted on this computer and never uploaded anywhere.")
        buttons = ["Install", "Cancel"]
    choice = ask(root, message, buttons)
    try:
        if choice in ("Install", "Reinstall"):
            note = run_with_progress(root, f"Installing {APP}…", lambda status: installer.install())
            messagebox.showinfo(APP, f"Installed! Right-click any file and choose Convert.{WHERE}{note}", parent=root)
        elif choice == "Uninstall":
            run_with_progress(root, f"Removing {APP}…", lambda status: installer.uninstall())
            messagebox.showinfo(APP, f"{APP} has been removed.", parent=root)
    except Exception as e:
        messagebox.showerror(APP, f"Something went wrong:\n\n{_describe(e)}", parent=root)


def self_test():
    """Converts a few generated files with the packaged libraries; used by the release build."""
    import traceback
    import wave

    log = Path.cwd() / "self-test.log"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            from PIL import Image
            Image.new("RGB", (64, 64), "red").save(tmp / "in.png")
            with wave.open(str(tmp / "in.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(bytes(16000))
            for src, dst in [("in.png", "out.jpg"), ("in.png", "in.pdf"), ("in.pdf", "out.docx"),
                             ("in.pdf", "out.png"), ("in.wav", "out.mp3"), ("in.wav", "out.ogg"), ("in.wav", "out.m4a")]:
                convert(tmp / src, tmp / dst)
                assert (tmp / dst).stat().st_size > 0, dst
        log.write_text("self-test passed\n")
    except Exception:
        log.write_text(traceback.format_exc())
        sys.exit(1)


def convert_files(args, root):
    target = None
    if args[:1] == ["--to"]:
        target, args = args[1], args[2:]
    files = [Path(a).resolve() for a in args]
    what = f"“{files[0].name}”" if len(files) == 1 else f"{len(files)} files"

    if not target:  # like Explorer, offer the formats of the first file; others that don't fit are skipped
        offered = targets_for(files[0].suffix)
        if not offered:
            messagebox.showerror(APP, f"“{files[0].name}” can't be converted.", parent=root)
            return
        target = (ask(root, f"Convert {what} to:", [t.upper() for t in offered] + ["Cancel"]) or "").lower()
        if target not in offered:
            return
    skipped = [f for f in files if target not in targets_for(f.suffix)]
    files = [f for f in files if f not in skipped]
    if not files:
        messagebox.showerror(APP, f"{what} can't be converted to {target.upper()}.", parent=root)
        return

    what = f"“{files[0].name}”" if len(files) == 1 else f"{len(files)} files"
    copy = "Save a copy…" if len(files) == 1 else "Save copies…"
    mode = ask(root,
               f"Convert {what} to {target.upper()}.\n\n"
               f"Replace original: the new file takes the original's place and the original "
               f"goes to the {TRASH}.\n\n"
               f"{copy[:-1]}: the original is kept and you choose where the new file goes.",
               [REPLACE, copy, "Cancel"])
    if mode == copy and len(files) == 1:
        path = filedialog.asksaveasfilename(
            parent=root, title=f"Save {target.upper()} as", initialdir=str(files[0].parent),
            initialfile=f"{files[0].stem}.{target}", defaultextension=f".{target}",
            filetypes=[(target.upper(), f"*.{target}")])
        if not path:
            return
        jobs = [(files[0], Path(path))]  # the save dialog already asked about overwriting
    elif mode in (REPLACE, copy):
        folder = None
        if mode == copy:
            folder = filedialog.askdirectory(parent=root, title="Choose where to save the converted files",
                                             initialdir=str(files[0].parent))
            if not folder:
                return
            folder = Path(folder)
        jobs = _plan(files, target, folder)
        existing = [dst for _, dst in jobs if dst.exists()]
        if existing and not messagebox.askyesno(
                APP, f"{len(existing)} file(s) already exist, e.g. “{existing[0].name}”. Overwrite?", parent=root):
            return
    else:
        return

    # Remember where the originals sit on the desktop, so the new files can take their spot.
    positions = {}
    if mode == REPLACE and sys.platform == "win32":
        import desktop
        positions = {src: desktop.icon_position(src) for src, _ in jobs}

    def work(status):
        results = {}
        for i, (src, dst) in enumerate(jobs, 1):
            count = f" ({i} of {len(jobs)})" if len(jobs) > 1 else ""
            status["text"] = f"Converting “{src.name}”…{count}"
            try:
                results[src] = convert(src, dst)
            except Exception as e:
                results[src] = e
        return results

    results = run_with_progress(root, "Converting…", work)
    done = [src for src, r in results.items() if not isinstance(r, Exception)]
    failed = {src: r for src, r in results.items() if isinstance(r, Exception)}
    if mode == REPLACE and done:
        from send2trash import send2trash
        for src in done:
            send2trash(str(src))
            if positions.get(src):
                desktop.move_icon(results[src][0], positions[src], removed=src)

    if len(jobs) == 1 and not skipped:
        src = jobs[0][0]
        if failed:
            err = failed[src]
            messagebox.showerror(APP, str(err) if isinstance(err, MissingTool)
                                 else f"Could not convert “{src.name}”.\n\n{_describe(err)}", parent=root)
            return
        created = results[src]
        lines = [str(f) for f in created[:10]] + ([f"…and {len(created) - 10} more"] if len(created) > 10 else [])
        if mode == REPLACE:
            lines.append(f"\nThe original was moved to the {TRASH}.")
        messagebox.showinfo(APP, "Saved:\n" + "\n".join(lines), parent=root)
        return

    lines = [f"Converted {len(done)} of {len(jobs) + len(skipped)} files to {target.upper()}."]
    if mode == REPLACE and done:
        lines.append(f"The originals were moved to the {TRASH}.")
    problems = [f"• {src.name}: {_describe(err)}" for src, err in failed.items()]
    problems += [f"• {src.name}: can't be converted to {target.upper()}" for src in skipped]
    if problems:
        lines += ["", "Not converted:"] + problems[:8] + ([f"…and {len(problems) - 8} more"] if len(problems) > 8 else [])
    (messagebox.showwarning if problems else messagebox.showinfo)(APP, "\n".join(lines), parent=root)


def main():
    if sys.stdout is None:  # no console (pythonw / packaged app), but some libraries print anyway
        sys.stdout = sys.stderr = open(os.devnull, "w")

    args = sys.argv[1:]
    if args == ["--self-test"]:
        return self_test()
    if args == ["--install"]:
        return installer.install()

    if sys.platform == "win32":
        if args[:1] == ["--to"] and len(args) == 3:
            files = gather(Path(args[2]).resolve(), args[1])
            if not files:
                return
            args = args[:2] + [str(f) for f in files]
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
        except Exception:
            pass

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(Path(__file__).with_name("icon.png"))))
    except tk.TclError:  # just cosmetic; never let a missing icon stop a conversion
        pass
    if not args:
        setup_window(root)
    elif args == ["--uninstall"]:
        installer.uninstall()
        messagebox.showinfo(APP, f"{APP} has been removed.", parent=root)
    else:
        convert_files(args, root)


if __name__ == "__main__":
    main()
