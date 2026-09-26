import errno

def describe(error):
    if isinstance(error,PermissionError):return '无法读写文件：请检查文件夹权限，或选择其他字幕保存位置。'
    if isinstance(error,FileNotFoundError):return '视频或保存位置已不可用：请连接原磁盘，或在任务菜单中重新定位视频。'
    if isinstance(error,OSError) and error.errno==errno.ENOSPC:return '磁盘空间不足：请清理缓存或更换保存位置后继续。'
    text=str(error)
    if '画幅' in text and '区域' in text:return text+' 请选择该集，再打开“更多操作 → 仅设置本集区域”。'
    if '无法可靠判断本剧字幕语言' in text:return text+' 设置范围选为本剧，在“识别语言”中选择原语言，再点击开始。'
    if '没有识别出字幕' in text:return text+' 选中该集，打开“查看 / 调整区域”，用“识别当前框内文字”检查。'
    if 'Invalid data found' in text:return '视频文件无法解码，可能损坏或格式不完整；请检查原视频后重试。'
    return text
