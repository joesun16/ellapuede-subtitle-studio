# 命令行与外部集成

桌面和工作进程共用 `launch.py`。命令行示例：

```bash
python launch.py --worker extract '/path/to/series' \
  -o '/path/to/output' \
  --roi 0.05,0.62,0.95,0.84 \
  --language en-US --format both
```

`--roi` 为左、上、右、下四个 0–1 坐标，相对视频宽高。省略时使用自动定位；图形界面的主路径是先手动框选。`--language` 是原字幕语言，不执行翻译；可用代码见 `src/hardware_policy.py`。`--format` 为 `srt`、`ass`、`both`。输入可为单个视频或递归扫描的文件夹；输出与视频原文件名对齐，重名视频按子目录避免覆盖。处理已有同名字幕时，显式使用 `--overwrite`，程序会备份旧文件。

其他程序请用参数数组启动子进程，读取工作进程标准输出中以 `@@ELLAPUEDE@@` 开头的单行 JSON。事件包括 `phase`、`progress`、`verify_progress`、`region`、`language`、`result`、`warning` 和 `error`；扫描进度与图像复核进度是不同阶段。退出码 0 为完成，1 为处理失败，130 为中断，2 通常为参数错误。内部 `src` 模块不是稳定 SDK。

```bash
python launch.py --worker extract --help
python launch.py --worker --version
```

从已有的识别记录重新导出而不重做 OCR：

```bash
python launch.py --worker export '/path/to/episode.subtitles.json' --format srt
```

如需在打包版上运行工作进程，使用安装目录中的 `EllaPuedeWorker`（Windows 为 `EllaPuedeWorker.exe`），后续参数与上例的 `--worker` 后部分相同。
