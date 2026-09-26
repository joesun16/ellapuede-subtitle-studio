"""Reject incorrectly classified Mac apps before packaging or distributing."""
from pathlib import Path
import os,plistlib

def validate_app(app):
    app=Path(app)
    with (app/'Contents/Info.plist').open('rb') as f:info=plistlib.load(f)
    expected={'CFBundlePackageType':'APPL','CFBundleExecutable':'EllaPuede','CFBundleIdentifier':'com.ellapuede.subtitle-studio','LSBackgroundOnly':False,'LSUIElement':False}
    for name,value in expected.items():
        if info.get(name)!=value:raise ValueError(f'Mac 应用配置错误：{name} 应为 {value!r}，实际为 {info.get(name)!r}')
    for path in [app/'Contents/MacOS/EllaPuede',app/'Contents/MacOS/EllaPuedeWorker']:
        if not path.is_file() or not os.access(path,os.X_OK):raise ValueError(f'缺少可运行程序：{path.name}')
    if not (app/'Contents/Resources'/info.get('CFBundleIconFile','')).is_file():raise ValueError('Mac 应用图标缺失')
    return info
