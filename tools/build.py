"""Build native app on macOS or Windows; does not upload or publish anything."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from _bootstrap import ROOT, SRC, TOOLS

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dist',type=Path,default=Path('dist'));parser.add_argument('--work',type=Path,default=Path('build'))
    args=parser.parse_args()
    subprocess.run([sys.executable,str(TOOLS/'make_icons.py')],check=True)
    # Built in place inside src/ so the extension sits next to the modules importing it.
    subprocess.run([sys.executable,str(SRC/'build_features.py'),'build_ext','--inplace'],cwd=SRC,check=True)
    if sys.platform=='darwin':
        (ROOT/'.runtime').mkdir(exist_ok=True)
        subprocess.run(['swiftc','-O',str(SRC/'vision_ocr.swift'),'-o',str(ROOT/'.runtime/vision-ocr')],check=True)
    subprocess.run([sys.executable,str(TOOLS/'download_models.py')],check=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(args.dist.resolve()),'--workpath',str(args.work.resolve()),str(ROOT/'EllaPuede.spec')],check=True)
    if sys.platform=='darwin':
        from mac_bundle import validate_app
        validate_app(args.dist.resolve()/'EllaPuede.app')
    print('应用已生成。公开发布前还需目标系统验收，以及公司自己的签名/公证流程。')

if __name__=='__main__':main()
