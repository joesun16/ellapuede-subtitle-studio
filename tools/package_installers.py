"""Produce installers from an already built native bundle, on its target OS."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile

from _bootstrap import ROOT
from version import VERSION

def run(args):subprocess.run([str(x) for x in args],check=True)

def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    path.with_name(path.name+'.sha256').write_text(h.hexdigest()+'  '+path.name+'\n',encoding='utf-8')

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--dist',type=Path,default=Path('dist'));p.add_argument('--output',type=Path,default=Path('installers'));p.add_argument('--iscc',type=Path)
    a=p.parse_args(argv);dist=a.dist.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if sys.platform=='darwin':
        app=dist/'EllaPuede.app'
        if not app.is_dir():raise SystemExit('缺少 EllaPuede.app，请先执行 build.py')
        from mac_bundle import validate_app
        validate_app(app)
        arch=platform.machine();label='AppleSilicon' if arch=='arm64' else 'Intel'
        with tempfile.TemporaryDirectory(prefix='ellapuede-installer-') as tmp:
            stage=Path(tmp)/'dmg';stage.mkdir()
            run(['ditto',app,stage/'EllaPuede.app'])
            (stage/'Applications').symlink_to('/Applications')
            (stage/'安装说明.txt').write_text(
                f'EllaPuede {VERSION} · macOS {label}\n\n将 EllaPuede.app 拖入 Applications 即可安装。\n程序包含 Python、OCR 模型和依赖，无需另装运行环境。\n\n'
                '这是未完成公司签名与公证的公测构建；下载后可能被 macOS 拦截。\n面向普通用户正式分发前，需要公司的 Developer ID 签名和 Apple 公证。\n\n'
                '升级前请停止处理并退出旧版本。卸载时将应用移到废纸篓；字幕和源视频不会被删除。\n'
                '字幕始终使用视频原文件名，仅扩展名变为 .srt / .ass。\n',encoding='utf-8')
            dmg=out/f'EllaPuede-{VERSION}-macOS-{label}.dmg'
            run(['hdiutil','create','-volname',f'EllaPuede {VERSION}','-srcfolder',stage,'-ov','-format','UDZO',dmg])
            run(['hdiutil','verify',dmg]);checksum(dmg)
        from mac_installer import build_pkg
        pkg=build_pkg(app,out/f'EllaPuede-{VERSION}-macOS-{label}-Installer.pkg',VERSION)
        checksum(pkg)
        print(f'已生成并校验：{dmg}；安装向导：{pkg}')
    elif os.name=='nt':
        if sysconfig.get_platform() != 'win-amd64':raise SystemExit('此安装器需要 Windows x64 Python；Windows ARM 虚拟机中也必须使用 x64 Python。')
        app=dist/'EllaPuede'
        if not (app/'EllaPuede.exe').exists():raise SystemExit('缺少 Windows 程序，请在 Windows 执行 build.py')
        compiler=a.iscc or os.environ.get('ISCC_PATH') or shutil.which('ISCC.exe')
        if not compiler:
            for base in [os.environ.get('ProgramFiles(x86)',''),os.environ.get('ProgramFiles','')]:
                candidate=Path(base)/'Inno Setup 6/ISCC.exe'
                if candidate.exists():compiler=candidate;break
        if not compiler:raise SystemExit('构建机器需要官方 Inno Setup 6；安装后设置 ISCC_PATH。最终用户不需要该工具。')
        run([compiler,f'/DAppVersion={VERSION}',f'/DAppDist={app}',f'/DInstallerOutput={out}',ROOT/'packaging/windows.iss'])
        installer=out/f'EllaPuede-{VERSION}-Windows-x64-Setup.exe';checksum(installer)
        print(f'已生成：{installer}。仍需干净 Windows 系统安装、运行、升级与卸载验收。')
    else:raise SystemExit('在 Windows 或 macOS 上构建对应安装包；不进行伪跨平台打包。')
if __name__=='__main__':main()
