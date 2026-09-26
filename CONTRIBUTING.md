# 参与 EllaPuede

欢迎修复可复现的问题、完善多语言 OCR/时间轴测试、改善安装与交互。请先搜索现有 Issue，再提交清晰的小范围 Pull Request。

## 开始

1. 阅读 [README](README.md)、[架构](docs/ARCHITECTURE.md)和[质量边界](docs/QUALITY.md)。
2. 在 Python 3.13 虚拟环境安装 `requirements-desktop.txt`。
3. 运行 `python -m unittest discover -s tests -t . -p 'test_*.py'`。
4. 修改 OCR 或时间轴时，用同一有权公开的素材比较逐条文字与视频 PTS；保留真正短句、数字、否定词变化。仅“字幕条数减少”不能证明识别更准确。
5. 修改 UI 时检查小窗口、拖动预览、取消、任务选择与项目进度；修改打包时完成目标系统安装后的自测。

请不要在 Issue、PR 或测试文件中提交未经授权的视频、对白、SRT/ASS、个人路径、令牌或崩溃报告中的私人信息。优先制作短小的合成视频或模糊化截图。公共问题可使用 Issue 模板；安全问题请按 [安全政策](SECURITY.md)私下报告。

新贡献默认按仓库的 [MIT License](LICENSE) 授权。第三方代码、模型和字体不能直接复制进仓库，除非许可和来源已核对并注明。
