# Build on the target OS. Separate console worker keeps JSON IPC reliable on Windows.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
root=Path(SPECPATH)
import runpy
release=runpy.run_path(str(root/'src'/'version.py'))
datas=collect_data_files('rapidocr')+[(str(root/'models'),'models'),(str(root/'assets'),'assets')]
if sys.platform=='darwin':datas += [(str(root/'.runtime'/'vision-ocr'),'.runtime'),(str(root/'src'/'vision_ocr.swift'),'.')]
hidden=collect_submodules('rapidocr.inference_engine.onnxruntime')
a=Analysis([str(root/'launch.py')],pathex=[str(root),str(root/'src')],binaries=[],datas=datas,
 hiddenimports=hidden,hookspath=[],runtime_hooks=[],
 excludes=['PyQt5','PyQt6','PySide2','torch','torchvision','torchaudio','paddle','tensorflow','jax',
           'matplotlib','pandas','scipy','IPython','notebook','pytest','tkinter','openvino','tensorrt'],noarchive=False)
pyz=PYZ(a.pure)
version_file=None
if sys.platform=='win32':
 sys.path.insert(0,str(root/'tools'))
 from windows_version import resource
 version_file=str(Path(workpath)/'windows-version.txt')
 Path(version_file).write_text(resource(),encoding='utf-8')
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='EllaPuede',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,version=version_file,icon=str(root/'assets'/('app-icon.icns' if sys.platform=='darwin' else 'app-icon.ico')))
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='EllaPuedeWorker',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=True,version=version_file)
coll=COLLECT(gui,worker,a.binaries,a.datas,strip=False,upx=False,name='EllaPuede')
if sys.platform=='darwin':
 # BUNDLE(COLLECT) defaults to console=True even with a GUI executable.
 # Explicit application flags prevent macOS treating the GUI as a background agent.
 app=BUNDLE(coll,name='EllaPuede.app',icon=str(root/'assets'/'app-icon.icns'),bundle_identifier='com.ellapuede.subtitle-studio',
   info_plist={'CFBundleDisplayName':'EllaPuede 字幕提取工具','CFBundleShortVersionString':release['VERSION'],
               'CFBundleVersion':release['BUILD'],'NSHighResolutionCapable':True,
               'LSBackgroundOnly':False,'LSUIElement':False,
               'NSPrincipalClass':'NSApplication'})
