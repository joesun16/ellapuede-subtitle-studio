# 架构概览

`launch.py` 是桌面界面和工作进程的统一入口。`src/ella_app.py`、`src/task_model.py` 负责队列与设置；`src/crop_editor.py`、`src/preview_worker.py` 负责画面框选和预览；`src/temporal_scan.py`、`src/subtitle_ocr.py` 负责按视频实际 PTS 扫描、识别、分段和导出。短时 OCR 波动的图像复核在 `src/quality_refine.py`、`src/visual_consensus.py` 等模块。`src/hardware_policy.py` 控制语言、后端和资源预算；`src/model_manifest.py` 固定下载模型的 SHA-256。

三档处理模式只改变可用并行度和内存预算。Mac 可使用 Apple Vision 或离线 RapidOCR；Windows 根据设备条件选择 CPU 或可用的 DirectML 加速，计算设备不改变所选语言模型。所有导出都应按实际画面文字和 PTS 组织，不应靠语义猜测、翻译或跳过真实短句来提高表面指标。

用于外部集成的是 [工作进程命令行与 JSON 事件](CLI.md)；内部模块尚不保证稳定 API。贡献 OCR 或时间轴修改时，请同时提供同一素材上的逐条文本和时间轴对照，并保护真实短时文字变化、数字及否定词。
