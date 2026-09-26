@echo off
setlocal
cd /d "%~dp0.."
py -3.13 tools\build_windows_local.py
if errorlevel 1 (
  echo.
  echo Build failed. Use x64 Python 3.13 and Inno Setup 6 inside Windows.
  pause
  exit /b 1
)
echo.
echo Build completed. Open the installers folder for Setup.exe and SHA256.
pause
