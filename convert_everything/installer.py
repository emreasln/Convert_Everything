"""Install or remove Convert Everything for the current user.

Everything goes into one folder in your user profile, plus the right-click menu
entries. No admin rights are needed, and uninstall removes all of it.
"""
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from converters import source_extensions, targets_for

NAME = "Convert Everything"
VERSION = "1.0.0"
EXE = "ConvertEverything"
MARKER = "Created by Convert Everything"  # lets uninstall recognise its own files
FROZEN = getattr(sys, "frozen", False)  # True in the packaged app, False when run from source

if sys.platform == "win32":
    APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "ConvertEverything"
elif sys.platform == "darwin":
    APP_DIR = Path.home() / "Library" / "Application Support" / "ConvertEverything"
else:
    APP_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "convert-everything"


def _command():
    """The program the right-click menu runs."""
    if not FROZEN:  # from source: this Python and this checkout
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        return [str(pythonw if pythonw.exists() else python), str(Path(__file__).with_name("main.py"))]
    if sys.platform == "win32":
        return [str(APP_DIR / f"{EXE}.exe")]
    if sys.platform == "darwin":
        return [str(APP_DIR / f"{EXE}.app" / "Contents" / "MacOS" / EXE)]
    return [str(APP_DIR / EXE)]


def _bundle():
    """The packaged app to copy into APP_DIR (None when running from source)."""
    if not FROZEN:
        return None
    payload = Path(getattr(sys, "_MEIPASS", "")) / "payload"  # inside the Windows setup .exe
    if payload.is_dir():
        return payload
    exe = Path(sys.executable).resolve()
    return exe.parents[2] if sys.platform == "darwin" else exe.parent  # macOS: the .app bundle


def running_installed_copy():
    return FROZEN and Path(sys.executable).resolve().is_relative_to(APP_DIR.resolve())


def is_installed():
    if APP_DIR.exists():
        return True
    if sys.platform == "win32":
        return _reg_exists(UNINSTALL_KEY)
    if sys.platform == "darwin":
        return WORKFLOW.exists()
    return any(p.exists() for p in _linux_menus().values())


def install():
    """Returns an extra note for the user ("" if there is nothing to add)."""
    uninstall()  # start clean, which also removes an older version
    bundle = _bundle()
    if bundle:
        shutil.copytree(bundle, APP_DIR / f"{EXE}.app" if sys.platform == "darwin" else APP_DIR, symlinks=True)
        if sys.platform == "darwin":  # we were allowed to run, so our own copy may run too
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(APP_DIR)], check=False)
    try:
        return {"win32": _windows_install, "darwin": _mac_install}.get(sys.platform, _linux_install)() or ""
    except Exception:
        uninstall()
        raise


def uninstall():
    {"win32": _windows_uninstall, "darwin": _mac_uninstall}.get(sys.platform, _linux_uninstall)()
    if not APP_DIR.exists():
        return
    if sys.platform == "win32" and running_installed_copy():
        # Windows can't delete a program while it runs: keep trying for a minute after we exit.
        os.chdir(Path.home())
        subprocess.Popen(f'cmd /c for /l %i in (1,1,60) do (ping -n 2 127.0.0.1 >nul & rmdir /s /q "{APP_DIR}" 2>nul'
                         f' & if not exist "{APP_DIR}" exit)', creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        shutil.rmtree(APP_DIR)


def _quoted(command):
    return " ".join(f'"{part}"' for part in command)


# --- Windows: Explorer right-click menu + "Installed apps" entry ------------------

ASSOC = r"Software\Classes\SystemFileAssociations"
KEY = "ConvertEverything"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ConvertEverything"


def _windows_install():
    run = _quoted(_command())
    for ext in source_extensions():
        menu = rf"{ASSOC}\.{ext}\shell\{KEY}"
        # Player = also show the menu when more than 15 files are selected.
        _reg_set(menu, MUIVerb="Convert", SubCommands="", MultiSelectModel="Player")
        for target in targets_for(ext):
            _reg_set(rf"{menu}\shell\{target}", MUIVerb=f"to {target.upper()}", MultiSelectModel="Player")
            _reg_set(rf"{menu}\shell\{target}\command", **{"": f'{run} --to {target} "%1"'})
    _reg_set(UNINSTALL_KEY, DisplayName=NAME, DisplayVersion=VERSION, Publisher=NAME,
             DisplayIcon=_command()[0], InstallLocation=str(APP_DIR), NoModify=1, NoRepair=1,
             UninstallString=f"{run} --uninstall")
    _refresh_explorer()


def _windows_uninstall():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ASSOC) as key:
            exts = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    except FileNotFoundError:
        exts = []
    for ext in exts:
        if _reg_delete_tree(rf"{ASSOC}\{ext}\shell\{KEY}"):
            _reg_delete_if_empty(rf"{ASSOC}\{ext}\shell")
            _reg_delete_if_empty(rf"{ASSOC}\{ext}")
    _reg_delete_tree(UNINSTALL_KEY)
    _refresh_explorer()


def _reg_exists(path):
    import winreg

    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, path).Close()
        return True
    except OSError:
        return False


def _reg_set(path, **values):
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        for name, value in values.items():
            kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
            winreg.SetValueEx(key, name, 0, kind, value)


def _reg_delete_tree(path):
    """Delete a key and everything under it. Returns False if it didn't exist."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            children = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    except FileNotFoundError:
        return False
    for child in children:
        _reg_delete_tree(rf"{path}\{child}")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    return True


def _reg_delete_if_empty(path):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            subkeys, values, _ = winreg.QueryInfoKey(key)
        if subkeys == 0 and values == 0:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def _refresh_explorer():
    import ctypes

    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


# --- macOS: Finder Quick Action ----------------------------------------------------

WORKFLOW = Path.home() / "Library" / "Services" / f"{NAME}.workflow"


def _mac_install():
    import plistlib
    import uuid

    info = {
        "NSServices": [{
            "NSMenuItem": {"default": "Convert…"},
            "NSMessage": "runWorkflowAsService",
            "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
            "NSSendFileTypes": ["public.item"],
        }],
    }
    ids = [str(uuid.uuid4()).upper() for _ in range(3)]
    workflow = {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [{
            "action": {
                "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.path"]},
                "AMActionVersion": "2.0.3",
                "AMApplication": ["Automator"],
                "AMParameterProperties": {k: {} for k in
                                          ("COMMAND_STRING", "CheckedForUserDefaultShell", "inputMethod", "shell", "source")},
                "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
                "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                "ActionName": "Run Shell Script",
                "ActionParameters": {"COMMAND_STRING": f'{shlex.join(_command())} "$@"',
                                     "CheckedForUserDefaultShell": True,
                                     "inputMethod": 1, "shell": "/bin/bash", "source": ""},
                "BundleIdentifier": "com.apple.RunShellScript",
                "CFBundleVersion": "2.0.3",
                "CanShowSelectedItemsWhenRun": False,
                "CanShowWhenRun": True,
                "Category": ["AMCategoryUtilities"],
                "Class Name": "RunShellScriptAction",
                "InputUUID": ids[0],
                "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
                "OutputUUID": ids[1],
                "UUID": ids[2],
                "UnlocalizedApplications": ["Automator"],
                "isViewVisible": True,
            },
            "isViewVisible": True,
        }],
        "connectors": {},
        "workflowMetaData": {
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    contents = WORKFLOW / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    with open(contents / "document.wflow", "wb") as f:
        plistlib.dump(workflow, f)
    subprocess.run(["/System/Library/CoreServices/pbs", "-update"], check=False)


def _mac_uninstall():
    shutil.rmtree(WORKFLOW, ignore_errors=True)
    subprocess.run(["/System/Library/CoreServices/pbs", "-update"], check=False)


# --- Linux: Nautilus (GNOME), Dolphin (KDE) and Nemo (Cinnamon) --------------------

def _linux_menus():
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return {
        "nautilus": data / "nautilus" / "scripts" / "Convert",
        "dolphin": data / "kio" / "servicemenus" / "convert-everything.desktop",
        "nemo": data / "nemo" / "actions" / "convert-everything.nemo_action",
    }


def _linux_install():
    run = _quoted(_command())
    contents = {
        "nautilus": f'#!/bin/sh\n# {MARKER}\nexec {run} "$@"\n',
        "dolphin": (f"# {MARKER}\n[Desktop Entry]\nType=Service\nMimeType=all/allfiles;\n"
                    f"X-KDE-ServiceTypes=KonqPopupMenu/Plugin\nActions=convert;\n\n"
                    f"[Desktop Action convert]\nName=Convert…\nIcon=document-export\nExec={run} %F\n"),
        "nemo": (f"# {MARKER}\n[Nemo Action]\nName=Convert…\nComment=Convert to another format\n"
                 f"Exec={run} %F\nSelection=notnone\nExtensions={';'.join(source_extensions())};\n"),
    }
    found = [fm for fm in contents if shutil.which(fm)]
    for fm in found:
        path = _linux_menus()[fm]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents[fm], encoding="utf-8")
        path.chmod(0o755)
    if not found:
        return ("\n\nNo supported file manager (GNOME Files, Dolphin or Nemo) was found, so no menu "
                f"entry was added. You can still convert from a terminal:\n{run} FILE")
    if "nautilus" in found:
        return "\n\nIn GNOME Files, it's under Scripts → Convert."


def _linux_uninstall():
    for path in _linux_menus().values():
        if path.exists() and MARKER in path.read_text(encoding="utf-8", errors="ignore"):
            path.unlink()
