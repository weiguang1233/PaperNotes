@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo PaperNote setup failed. Please review the message above.
  pause
  exit /b 1
)
echo.
echo PaperNote setup completed. You can now run start.bat.
pause
