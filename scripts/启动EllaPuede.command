#!/bin/zsh
set -e
cd -- "${0:A:h}/.."
if [[ ! -x .venv/bin/python ]]; then
  echo '请先运行「安装依赖.command」，或直接使用已打包的 EllaPuede.app。'
  read '?按回车退出…'
  exit 1
fi
exec .venv/bin/python launch.py "$@"
