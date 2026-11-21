#!/bin/sh
# AG Drive Track Explorer - macOS launcher (double-click in Finder)
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 serve.py
else osascript -e 'display alert "Python 3 is needed" message "Install Python 3 from python.org (or run: xcode-select --install), then double-click start.command again."'; fi
