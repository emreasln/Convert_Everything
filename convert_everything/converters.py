"""What can be converted into what, and the engines that do the work.

Heavy libraries are imported inside the engines, so the installer can read the
format table with a plain Python before any dependency is installed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGE = ["png", "jpg", "bmp", "gif", "tiff", "webp", "ico"]
DOCUMENT = ["docx", "doc", "odt", "rtf", "txt"]
SHEET = ["xlsx", "xls", "ods", "csv"]
SLIDES = ["pptx", "ppt", "odp"]
VIDEO = ["mp4", "mkv", "avi", "mov", "webm"]
AUDIO = ["mp3", "wav", "flac", "m4a", "ogg"]

# (source extensions, target extensions, engine)
TABLE = [
    (IMAGE + ["jpeg", "tif"], ["pdf"] + IMAGE, "image"),
    (["pdf"], ["docx", "txt", "png", "jpg"], "pdf"),
    (DOCUMENT, ["pdf"] + DOCUMENT, "office"),
    (SHEET, ["pdf"] + SHEET, "office"),
    (SLIDES, ["pdf"] + SLIDES, "office"),
    (VIDEO + ["wmv", "flv", "m4v"], VIDEO + ["gif"] + AUDIO, "media"),
    (AUDIO + ["aac", "opus", "wma"], AUDIO, "media"),
]
ALIASES = {"jpeg": "jpg", "tif": "tiff"}

INSTALL_HINTS = {
    "FFmpeg": {
        "win32": "winget install Gyan.FFmpeg",
        "darwin": "brew install ffmpeg",
        "linux": "sudo apt install ffmpeg",
    },
    "LibreOffice": {
        "win32": "winget install TheDocumentFoundation.LibreOffice",
        "darwin": "brew install --cask libreoffice",
        "linux": "sudo apt install libreoffice",
    },
}


class ConversionError(Exception):
    """A problem explained in plain words, shown to the user as is."""


class MissingTool(ConversionError):
    pass


def _row(ext):
    ext = ext.lower().lstrip(".")
    for sources, targets, engine in TABLE:
        if ext in sources:
            return ext, targets, engine
    return ext, [], None


def targets_for(ext):
    """Formats a file with this extension can be converted to."""
    ext, targets, _ = _row(ext)
    return [t for t in targets if t != ALIASES.get(ext, ext)]


def source_extensions():
    return sorted({ext for sources, _, _ in TABLE for ext in sources})


def convert(src, dst):
    """Convert src into dst. Returns the created files (a multi-page PDF
    converted to images gives one file per page: name-1.png, name-2.png, ...)."""
    src, dst = Path(src), Path(dst)
    if src.stat().st_size == 0:
        raise ConversionError("The file is empty, so there is nothing to convert.")
    engine = ENGINES[_row(src.suffix)[2]]
    # Work in a temp folder so a failed conversion never leaves half a file behind.
    with tempfile.TemporaryDirectory() as tmp:
        engine(src, Path(tmp) / dst.name)
        created = []
        for f in sorted(Path(tmp).iterdir()):
            target = dst.parent / f.name
            shutil.move(str(f), str(target))
            created.append(target)
    return created


def _run(cmd, env=None):
    no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=env, creationflags=no_window)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-1000:] or f"{Path(cmd[0]).name} failed")


def _find(tool, names, extra_paths=()):
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for path in extra_paths:
        if Path(path).exists():
            return path
    hint = INSTALL_HINTS[tool].get(sys.platform, INSTALL_HINTS[tool]["linux"])
    raise MissingTool(f"This conversion needs {tool}, which was not found.\n\nInstall it, then try again:\n    {hint}")


def _image(src, out):
    from PIL import Image, UnidentifiedImageError

    try:
        im = Image.open(src)
    except UnidentifiedImageError:
        raise ConversionError(f"This doesn't look like a valid {src.suffix[1:].upper()} image. "
                              "It may be damaged, or its extension may be wrong.") from None
    with im:
        if out.suffix in (".jpg", ".bmp", ".pdf") and im.mode != "RGB":
            rgba = im.convert("RGBA")  # flatten transparency onto white
            im = Image.new("RGB", im.size, "white")
            im.paste(rgba, mask=rgba)
        elif im.mode not in ("RGB", "RGBA", "L", "P"):  # e.g. CMYK, 16-bit
            im = im.convert("RGBA")
        im.save(out)


def _pdf(src, out):
    if out.suffix == ".docx":
        from pdf2docx import Converter

        cv = Converter(str(src))
        try:
            cv.convert(str(out))
        finally:
            cv.close()
        return

    import pymupdf

    with pymupdf.open(src) as doc:
        if out.suffix == ".txt":
            out.write_text("\n\f".join(page.get_text() for page in doc), encoding="utf-8")
            return
        for i, page in enumerate(doc, 1):
            name = out if len(doc) == 1 else out.with_name(f"{out.stem}-{i}{out.suffix}")
            page.get_pixmap(dpi=150).save(str(name))


# Microsoft Office (Windows only): app -> (sources it opens, SaveAs format codes, PowerShell)
MS_OFFICE = {
    "Word": (
        DOCUMENT,
        {"pdf": 17, "docx": 16, "doc": 0, "odt": 23, "rtf": 6, "txt": 7},
        "$a.DisplayAlerts = 0; $d = $a.Documents.Open($env:CE_SRC, $false, $true); "
        "$d.SaveAs2($env:CE_DST, [int]$env:CE_FMT); $d.Close($false)",
    ),
    "Excel": (
        SHEET,
        {"pdf": -1, "xlsx": 51, "xls": 56, "ods": 60, "csv": 62},
        "$a.DisplayAlerts = $false; $d = $a.Workbooks.Open($env:CE_SRC, 0, $true); "
        "if ($env:CE_FMT -eq '-1') { $d.ExportAsFixedFormat(0, $env:CE_DST) } "
        "else { $d.SaveAs($env:CE_DST, [int]$env:CE_FMT) }; $d.Close($false)",
    ),
    "PowerPoint": (
        SLIDES,
        {"pdf": 32, "pptx": 24, "ppt": 1, "odp": 35},
        "$a.DisplayAlerts = 1; $d = $a.Presentations.Open($env:CE_SRC, -1, 0, 0); "
        "$d.SaveAs($env:CE_DST, [int]$env:CE_FMT); $d.Close()",
    ),
}


def _has_com(prog_id):
    import winreg

    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\CLSID").Close()
        return True
    except OSError:
        return False


def _office(src, out):
    ext, target = src.suffix[1:].lower(), out.suffix[1:]
    if sys.platform == "win32":
        for app, (sources, codes, script) in MS_OFFICE.items():
            if ext in sources and _has_com(f"{app}.Application"):
                env = {**os.environ, "CE_SRC": str(src), "CE_DST": str(out), "CE_FMT": str(codes[target])}
                ps = (f"$ErrorActionPreference = 'Stop'; $a = New-Object -ComObject {app}.Application; "
                      f"try {{ {script} }} finally {{ $a.Quit() }}")
                return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env)

    soffice = _find("LibreOffice", ["soffice", "libreoffice"], [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ])
    _run([soffice, "--headless", "--convert-to", "txt:Text" if target == "txt" else target,
          "--outdir", str(out.parent), str(src)])
    produced = out.parent / f"{src.stem}.{target}"
    if not produced.exists():
        raise RuntimeError("LibreOffice could not convert this file.")
    if produced != out:
        produced.rename(out)


def _ffmpeg():
    try:
        import imageio_ffmpeg  # ships its own FFmpeg, so nothing has to be installed

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return _find("FFmpeg", ["ffmpeg"], ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"])


def _media(src, out):
    ffmpeg = _ffmpeg()
    target = out.suffix[1:]
    if target in AUDIO:
        opts = ["-vn"]
    elif target == "gif":
        opts = ["-vf", "fps=12,scale=480:-1:flags=lanczos"]
    else:
        opts = []
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), *opts, str(out)])


ENGINES = {"image": _image, "pdf": _pdf, "office": _office, "media": _media}
