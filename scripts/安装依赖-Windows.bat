@echo off
chcp 65001 >nul
cd /d "%~dp0.."
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe download_models.py
if errorlevel 1 goto fail
echo 安装完成，请双击“启动EllaPuede-Windows.bat”。
pause
exit /b 0
:fail
echo 安装未完成，请检查 Python 3.10–3.13 和上方错误信息。
pause
exit /b 1
