@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
  echo 请先运行“安装依赖-Windows.bat”。
  pause
  exit /b 1
)
.venv\Scripts\python.exe launch.py %*
if errorlevel 1 pause
