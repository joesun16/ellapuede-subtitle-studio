# 第三方组件与模型来源

EllaPuede 自有代码的 MIT License **不覆盖**下列第三方组件。安装包将这些组件和离线模型一并打包；各项目的许可证、版权声明及适用条件仍以原项目为准。

| 组件 | 用途 | 来源与许可 |
|---|---|---|
| [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/) | 桌面界面 | Qt Company；社区版本提供 LGPLv3/GPLv3 等许可，或商业许可。构建使用 PySide6 6.8.3。 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | 离线 OCR 推理 | RapidAI；工程代码 Apache-2.0。RapidOCR 说明 OCR 模型版权归百度所有。 |
| [PaddleOCR 模型](https://github.com/PaddlePaddle/PaddleOCR) | 多语言文本检测与识别 | 百度 PaddlePaddle 项目；按模型提供方条款使用。模型从 RapidOCR 的固定发布路径取得，文件名与 SHA-256 见 `src/model_manifest.py`。 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) / [DirectML](https://github.com/microsoft/onnxruntime/tree/main/onnxruntime/core/providers/dml) | CPU / Windows GPU 推理 | Microsoft；各发行包的许可与声明见其项目。 |
| [PyAV](https://github.com/PyAV-Org/PyAV) / [FFmpeg](https://ffmpeg.org/legal.html) | 视频读取与时间轴 | PyAV 与其所附 FFmpeg 库分别适用相应许可；FFmpeg 的 LGPL/GPL 条款取决于实际二进制构建选项。 |
| [NumPy](https://numpy.org/), [Pillow](https://python-pillow.github.io/), [psutil](https://github.com/giampaolo/psutil), [certifi](https://github.com/certifi/python-certifi) | 数值、图像、资源控制、构建证书 | 依各项目许可。 |
| [PyInstaller](https://pyinstaller.org/) | 构建工具 | PyInstaller 许可及其打包例外适用；非用户运行时接口。 |

源码仓库不提交第三方模型大文件。`tools/download_models.py` 从固定路径下载并核对 SHA-256；安装包内包含对应模型，最终用户无需另行下载。Mac 版还使用操作系统提供的 Apple Vision API。

发布方应随每次安装包核对实际依赖、二进制编译选项与许可声明。本文件是来源索引，不替代每个组件的完整许可证。若发现遗漏，请通过 Issue 指出具体包名、版本和许可文件。
