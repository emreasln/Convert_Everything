"""Build the standalone app for this OS and pack it for a GitHub release.

    pip install -r requirements.txt pyinstaller
    python packaging/build.py

Output in release/:
    Windows  ConvertEverything-Windows-Setup.exe   (one file, holds the whole app)
    macOS    ConvertEverything-macOS.zip           (ConvertEverything.app)
    Linux    ConvertEverything-Linux.tar.gz        (folder with the ConvertEverything program)
"""
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST, RELEASE = ROOT / "dist", ROOT / "release"
ICON = ROOT / "convert_everything" / "icon.png"
# Libraries only the converter needs; the Windows setup .exe leaves them out (they're in its payload).
HEAVY = ["PIL", "pymupdf", "fitz", "pdf2docx", "cv2", "numpy", "docx", "imageio_ffmpeg", "send2trash", "fontTools", "lxml"]


def collect_licenses():
    """Gather the license texts of everything we bundle; the app ships them in its `licenses` folder."""
    from importlib.metadata import distributions

    out = ROOT / "build" / "licenses"
    shutil.rmtree(out, ignore_errors=True)
    for dist in distributions():
        for f in dist.files or []:
            if f.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                dest = out / dist.metadata["Name"] / f.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f.locate(), dest)
    base = Path(sys.base_prefix)
    for python_license in [base / "LICENSE.txt", *base.glob("lib/python3*/LICENSE.txt")]:
        if python_license.exists():
            (out / "Python").mkdir(parents=True, exist_ok=True)
            shutil.copy(python_license, out / "Python" / "LICENSE.txt")
    (out / "FFmpeg").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "packaging" / "GPL-3.0.txt", out / "FFmpeg" / "COPYING.GPLv3.txt")
    shutil.copy(ROOT / "LICENSE", out / "LICENSE-ConvertEverything.txt")
    shutil.copy(ROOT / "THIRD_PARTY_NOTICES.md", out)
    return out


def pyinstaller(*args):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
                    "--icon", str(ICON), "--add-data", f"{ICON}{os.pathsep}.",
                    "--add-data", f"{ROOT / 'build' / 'licenses'}{os.pathsep}licenses", "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
                    "--specpath", str(ROOT / "build"), *args, str(ROOT / "convert_everything" / "main.py")],
                   check=True)


def self_test(exe):
    log = ROOT / "self-test.log"
    log.unlink(missing_ok=True)
    code = subprocess.run([str(exe), "--self-test"], cwd=ROOT).returncode
    print(log.read_text() if log.exists() else "(no self-test log written)")
    if code:
        sys.exit("The packaged app failed its self-test.")


def main():
    for folder in (DIST, RELEASE):
        shutil.rmtree(folder, ignore_errors=True)
    RELEASE.mkdir()
    collect_licenses()

    pyinstaller("--name", "ConvertEverything", "--collect-data", "imageio_ffmpeg", "--collect-data", "docx",
                "--osx-bundle-identifier", "io.github.convert-everything")
    if sys.platform == "darwin":
        app = DIST / "ConvertEverything.app"
        self_test(app / "Contents" / "MacOS" / "ConvertEverything")
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(RELEASE / "ConvertEverything-macOS.zip")],
                       check=True)
    elif sys.platform == "win32":
        app = DIST / "ConvertEverything"
        self_test(app / "ConvertEverything.exe")
        pyinstaller("--onefile", "--name", "ConvertEverything-Setup", "--add-data", f"{app}{os.pathsep}payload",
                    *(f"--exclude-module={m}" for m in HEAVY))
        shutil.move(DIST / "ConvertEverything-Setup.exe", RELEASE / "ConvertEverything-Windows-Setup.exe")
    else:
        app = DIST / "ConvertEverything"
        self_test(app / "ConvertEverything")
        with tarfile.open(RELEASE / "ConvertEverything-Linux.tar.gz", "w:gz") as tar:
            tar.add(app, arcname="ConvertEverything")
    print("Built:", *sorted(p.name for p in RELEASE.iterdir()))


if __name__ == "__main__":
    main()
