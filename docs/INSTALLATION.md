# 安装与卸载

从 [0.14.4 Release](https://github.com/joesun16/ellapuede-subtitle-studio/releases/tag/v0.14.4) 下载适合系统的文件，并与 Release 中的 SHA-256 清单核对。安装包内含 Python 运行时、OCR 模型和所需组件；识别视频时不需联网。

## macOS Apple Silicon

打开 DMG，将 `EllaPuede.app` 拖入“应用程序”；也可使用 PKG 安装向导。升级前退出旧版本。若 macOS 提示无法验证开发者，这是因为本公测版尚未使用公司 Developer ID 签名和 Apple 公证；请仅从本仓库 Release 获取并核对 SHA-256。不要关闭系统级安全功能来解决来源不明的文件。

卸载时删除 App；已保存的视频、字幕与任务工作记录不会随 App 删除。Intel Mac 原生安装包尚未提供。

## Windows x64

运行 `EllaPuede-0.14.4-Windows-x64-Setup.exe`，按安装向导完成安装；可通过系统“已安装的应用”卸载。安装包目前没有公司代码签名，系统可能显示发布者验证提示，请先核对来源和 SHA-256。Windows ARM 原生包尚未提供；GPU 加速会按硬件能力测试与回退，不作速度承诺。

## 从源码构建

参见 [构建说明](BUILD.md)。首次构建会联网下载已固定 SHA-256 的 OCR 模型；生成的安装包将模型内置。
