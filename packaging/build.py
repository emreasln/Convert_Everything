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


def pyinstaller(*args):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
                    "--icon", str(ICON), "--add-data", f"{ICON}{os.pathsep}.", "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
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
