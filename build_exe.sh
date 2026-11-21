#!/bin/bash
# Builds dist/AGDriveConverter.exe on Linux with Windows Python 3.12 + PyInstaller running under Wine.
# (On Windows you don't need this script: see "Building from source with Python" in README.md.)
#
# One-time setup (Debian/Ubuntu):
#   sudo dpkg --add-architecture i386 && sudo apt-get update
#   sudo apt-get install wine wine64 wine32:i386 xvfb
#   export WINEPREFIX=$HOME/.wine-agd
#   wine python-3.12.8-amd64.exe /quiet InstallAllUsers=0 TargetDir='C:\Python312' Include_tcltk=1
#   wine 'C:\Python312\python.exe' -m pip install "numpy==1.26.4" pillow lz4 texture2ddecoder tkinterdnd2 pyinstaller
# numpy 1.26.4 is pinned for Wine builds: numpy 2.x calls a ucrtbase function that Wine does not implement.
set -e
cd "$(dirname "$0")"
export WINEPREFIX=${WINEPREFIX:-$HOME/.wine-agd} WINEDEBUG=-all
GLTFPACK_VERSION=${GLTFPACK_VERSION:-v1.3}
if [ ! -f bin/gltfpack.exe ]; then
  echo "Downloading gltfpack $GLTFPACK_VERSION (meshoptimizer, MIT) ..."
  mkdir -p bin
  curl -fsSL -o bin/gltfpack-windows.zip "https://github.com/zeux/meshoptimizer/releases/download/$GLTFPACK_VERSION/gltfpack-windows.zip"
  (cd bin && unzip -o -q gltfpack-windows.zip gltfpack.exe && rm gltfpack-windows.zip)
fi
if [ -z "$DISPLAY" ]; then Xvfb :77 -screen 0 1024x768x24 >/dev/null 2>&1 & export DISPLAY=:77; sleep 1; fi
rm -rf build dist
wine 'C:\Python312\python.exe' -m PyInstaller --noconfirm --clean AGDriveConverter.spec
ls -la dist
