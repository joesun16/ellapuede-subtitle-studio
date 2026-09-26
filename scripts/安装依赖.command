#!/bin/zsh
set -e
cd -- "${0:A:h}/.."
if ! xcrun --find swiftc >/dev/null 2>&1; then
  echo '请先安装 Apple Command Line Tools：xcode-select --install'
  read '?按回车退出…'
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python download_models.py
mkdir -p .runtime
swiftc -O vision_ocr.swift -o .runtime/vision-ocr
echo '安装完成。双击「启动EllaPuede.command」即可打开桌面应用。'
read '?按回车退出…'
