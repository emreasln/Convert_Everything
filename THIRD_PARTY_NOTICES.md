# Third-party software

Convert Everything itself is licensed under the [GNU AGPL v3.0 or later](LICENSE).

The ready-made apps on the [Releases](https://github.com/emreasln/Convert_Everything/releases) page
also contain the components below. Because some of them are AGPL/GPL licensed, each release build
as a whole is distributed under the AGPL-3.0, and its complete source code is this repository.
The license texts of all bundled components are included in the app's `licenses` folder.

| Component | License | Source |
|---|---|---|
| Python and Tcl/Tk | PSF License, Tcl/Tk License | https://www.python.org |
| PyMuPDF / MuPDF | AGPL-3.0 | https://github.com/pymupdf/PyMuPDF |
| pdf2docx | MIT | https://github.com/ArtifexSoftware/pdf2docx |
| Pillow | MIT-CMU | https://github.com/python-pillow/Pillow |
| OpenCV (opencv-python-headless) | Apache-2.0 | https://github.com/opencv/opencv-python |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| python-docx | MIT | https://github.com/python-openxml/python-docx |
| fontTools | MIT | https://github.com/fonttools/fonttools |
| lxml | BSD-3-Clause | https://github.com/lxml/lxml |
| Send2Trash | BSD-3-Clause | https://github.com/arsenetar/send2trash |
| Python Fire | Apache-2.0 | https://github.com/google/python-fire |
| imageio-ffmpeg | BSD-2-Clause | https://github.com/imageio/imageio-ffmpeg |
| FFmpeg (shipped inside imageio-ffmpeg) | GPL-3.0-or-later | https://ffmpeg.org/download.html |
| PyInstaller bootloader | GPL-2.0-or-later with the bootloader exception | https://github.com/pyinstaller/pyinstaller |

## FFmpeg

The FFmpeg program is an unmodified build distributed by the imageio-ffmpeg package
(Windows builds come from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), other platforms from
[imageio-binaries](https://github.com/imageio/imageio-binaries)). The source code of every FFmpeg
release is available at https://ffmpeg.org/releases/. The exact version is printed by running the
bundled `ffmpeg -version`.

Microsoft Office and LibreOffice are not included; Convert Everything only uses them when they are
already installed on your computer.
