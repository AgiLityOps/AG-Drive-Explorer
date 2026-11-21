@echo off
title AG Drive Track Explorer
cd /d "%~dp0"
echo Starting the AG Drive Track Explorer...
py -3 -c "import sys" >nul 2>nul && ( py -3 serve.py & goto :eof )
python -c "import sys; assert sys.version_info[0]==3" >nul 2>nul && ( python serve.py & goto :eof )
echo Python 3 not found - using the built-in PowerShell server instead.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1"
pause
