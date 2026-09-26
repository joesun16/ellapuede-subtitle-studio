"""Apple Installer package: fixed Applications destination and safe app upgrade."""
from pathlib import Path
import plistlib,subprocess,tempfile
from xml.etree import ElementTree as ET
from mac_bundle import validate_app

def build_pkg(app,out,version):
    app=Path(app).resolve();out=Path(out).resolve();info=validate_app(app)
    def run(args):subprocess.run([str(x) for x in args],check=True)
    with tempfile.TemporaryDirectory(prefix='ellapuede-pkg-') as tmp:
        root=Path(tmp);payload=root/'payload';payload.mkdir();run(['ditto',app,payload/'EllaPuede.app'])
        components=root/'components.plist'
        run(['pkgbuild','--analyze','--root',payload,components])
        data=plistlib.loads(components.read_bytes())
        for component in data:
            component['BundleIsRelocatable']=False
            component['BundleOverwriteAction']='upgrade'
        components.write_bytes(plistlib.dumps(data))
        scripts=root/'scripts';scripts.mkdir()
        check=scripts/'preinstall';check.write_text('''#!/bin/sh
# Never overwrite a running application or touch user media/cache.
if /usr/bin/pgrep -f '^/Applications/EllaPuede.app/Contents/MacOS/EllaPuede($| )' >/dev/null; then
    echo '请先退出 EllaPuede，再重新运行安装器。任务和已导出字幕会保留。' >&2
    exit 1
fi
exit 0
''');check.chmod(0o755)
        ident='com.ellapuede.subtitle-studio.installer';component=root/'EllaPuede-component.pkg'
        run(['pkgbuild','--root',payload,'--component-plist',components,'--identifier',ident,'--version',version,'--install-location','/Applications','--ownership','recommended','--scripts',scripts,component])
        resources=root/'resources';resources.mkdir()
        (resources/'welcome.html').write_text(f'''<html><meta charset="utf-8"><body style="font-family:-apple-system,sans-serif;font-size:14px"><h1>EllaPuede 字幕提取工具</h1><p>{version} · Mac 公测版</p><p>安装向导会将应用安装到“应用程序”。OCR 模型和运行环境已内置，无需额外下载。</p><p>升级前请退出 EllaPuede。原视频、字幕和任务记录都会保留。</p><p>本公测包尚未完成 Developer ID 签名及 Apple 公证。</p></body></html>''')
        (resources/'conclusion.html').write_text('''<html><meta charset="utf-8"><body style="font-family:-apple-system,sans-serif;font-size:14px"><h1>安装完成</h1><p>从“应用程序”打开 EllaPuede。运行时会在 Dock 显示；按 ⌘Q 可保存任务并退出。</p><p>拖入视频或整剧文件夹，选择语言、模式和字幕格式，再开始提取。</p></body></html>''')
        dist=ET.Element('installer-gui-script',{'minSpecVersion':'2'});ET.SubElement(dist,'title').text='EllaPuede 字幕提取工具'
        ET.SubElement(dist,'options',{'customize':'never','hostArchitectures':'arm64' if __import__('platform').machine()=='arm64' else 'x86_64'})
        ET.SubElement(dist,'domains',{'enable_localSystem':'true','enable_currentUserHome':'false','enable_anywhere':'false'})
        ET.SubElement(dist,'welcome',{'file':'welcome.html'});ET.SubElement(dist,'conclusion',{'file':'conclusion.html'})
        outline=ET.SubElement(dist,'choices-outline');ET.SubElement(outline,'line',{'choice':'main'})
        choice=ET.SubElement(dist,'choice',{'id':'main','title':'EllaPuede','visible':'false'});ET.SubElement(choice,'pkg-ref',{'id':ident})
        ET.SubElement(dist,'pkg-ref',{'id':ident,'version':version,'onConclusion':'none'}).text=component.name
        distribution=root/'Distribution.xml';ET.ElementTree(dist).write(distribution,encoding='utf-8',xml_declaration=True)
        run(['productbuild','--distribution',distribution,'--package-path',root,'--resources',resources,out])
    return out
