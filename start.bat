@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo PaperNote needs its small companion environment for Zotero and research notes.
  echo Please run setup.bat once, then run start.bat again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "%~dp0scripts\launcher.py" --mode server
if errorlevel 1 pause
exit /b %errorlevel%
