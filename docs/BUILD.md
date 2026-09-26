# 从源码构建

需要目标系统上的 Python 3.13。建议使用隔离的虚拟环境。以下命令在仓库根目录执行：

```bash
python -m pip install -r requirements-desktop.txt pyinstaller==6.17.0
python -m unittest discover -s tests -t . -p 'test_*.py'
python tools/build.py
python tools/package_installers.py
```

Mac 需 Xcode Command Line Tools，用于编译 Apple Vision 组件。Windows 需适用的 C 编译工具和 Inno Setup 6；自动化构建见 `.github/workflows/build.yml`。`tools/build.py` 会根据 `src/model_manifest.py` 下载并校验模型；构建机需要网络，安装后的 OCR 工作不需要网络。

本仓库不提交模型大文件、用户视频、输出字幕或构建缓存。源代码和安装包中的第三方组件有各自许可，参见 [第三方说明](../THIRD_PARTY_NOTICES.md)。构建后应在真实目标系统安装、运行包内离线 OCR 自测，再卸载；仅运行源码单元测试不能替代安装验证。
