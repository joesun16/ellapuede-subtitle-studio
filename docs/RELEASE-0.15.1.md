# EllaPuede 字幕提取工具 0.15.1 / build 37 公测版

框选窗口新增无声播放、暂停和空格控制，拖动持续更新画面。识别改进覆盖缺行恢复、字号误过滤与低分断行；复核须有当前源帧证据，并完整保留已经验证的文字。解码按实际 PTS 定位，三个模式共用质量规则。

255 项公开回归通过。Mac/Windows 同源构建、包内离线多语 OCR、连续预览与反向定位、实际源帧时间、同名 SRT/ASS、连续任务均通过；Windows 另完成安装与卸载检查。公开构建源码为 `203050de2b1d0f0a1751a2d2115e149553f6c8f5`，标签 v0.15.1 指向该构建源码；主分支的公开文档可能晚于构建提交。安装包与 SHA-256 见 [发布清单](RELEASE-MANIFEST-0.15.1.json)。

这是公测版，泰语与复杂场景仍可能缺行、错字、拆条或误收场景文字；Windows 多硬件整季运行和百分钟速度目标仍未完成。详见 [检查方法与限制](ASSESSMENT-0.15.1.md)。私有用户素材及具体测量数据不公开。

[下载 0.15.1](https://github.com/joesun16/ellapuede-subtitle-studio/releases/tag/v0.15.1) · [双端构建](https://github.com/joesun16/ellapuede-subtitle-studio/actions/runs/36669706152)
