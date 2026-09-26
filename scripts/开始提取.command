#!/bin/zsh
set -e
cd -- "${0:A:h}/.."
if [[ -x .venv/bin/python ]]; then
  tool_python="$PWD/.venv/bin/python"
else
  tool_python="$(command -v python3)"
fi
if ! "$tool_python" -c 'import av; from PIL import Image' >/dev/null 2>&1; then
  echo '请先双击「安装依赖.command」。'
  read '?按回车退出…'
  exit 1
fi
if [[ $# -gt 0 ]]; then
  tool_input="$1"
else
  tool_input="$(osascript <<'APPLESCRIPT'
set choice to button returned of (display dialog "选择要识别的英文字幕视频。整季文件夹将递归处理。" buttons {"取消", "单个视频", "整季文件夹"} default button "整季文件夹" cancel button "取消")
if choice is "单个视频" then
    return POSIX path of (choose file with prompt "选择带画面英文字幕的视频")
else
    return POSIX path of (choose folder with prompt "选择整季视频文件夹")
end if
APPLESCRIPT
)"
fi
tool_output="$PWD/results"
echo "输入：$tool_input"
echo "输出：$tool_output"
echo '字幕区域会自动估计。首次完成后请查看 calibration.jpg 和 review.html。'
if "$tool_python" subtitle_ocr.py extract "$tool_input" -o "$tool_output" --workers 4; then
  open "$tool_output"
  echo '处理完成。高分不等于零错误，请查看复核报告。'
else
  echo '部分文件处理失败，详见上面的信息和 results/manifest.json。再次运行可利用缓存继续。'
fi
read '?按回车退出…'
