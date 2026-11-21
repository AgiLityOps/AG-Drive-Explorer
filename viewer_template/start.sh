#!/bin/sh
# AG Drive Track Explorer - Linux / macOS launcher
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 serve.py "$@"
elif command -v python >/dev/null 2>&1; then exec python serve.py "$@"
else echo "Python 3 is required (https://www.python.org/downloads/)"; exit 1; fi
