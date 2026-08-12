@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo PaperNote needs its small companion environment for Zotero and research notes.
  echo Please run setup.bat once, then run start.bat again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi, pydantic, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo PaperNote dependencies are incomplete because setup did not finish.
  echo Fix the network or proxy problem, then run setup.bat again.
  echo If your network requires a verified proxy, use:
  echo   setup.bat -ProxyUrl http://127.0.0.1:PORT
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "%~dp0scripts\launcher.py" --mode server
if errorlevel 1 pause
exit /b %errorlevel%
