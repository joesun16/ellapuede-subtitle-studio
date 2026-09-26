"""Check packaged OCR without reading any user media. Used after installation."""
import _bootstrap  # noqa: F401  puts src/ on sys.path
import argparse
import base64
import io
import json
from pathlib import Path
import subprocess
import tempfile
from PIL import Image,ImageDraw,ImageFont

def main():
    parser=argparse.ArgumentParser();parser.add_argument('worker',type=Path);parser.add_argument('models',type=Path);a=parser.parse_args()
    from version import VERSION
    version=subprocess.check_output([str(a.worker.resolve()),'--worker','--version'],text=True,encoding='utf-8',timeout=30).strip()
    assert version==f'EllaPuede {VERSION}',version
    print('安装后版本核验通过：'+version)
    if a.worker.parent.name=='MacOS':
        from mac_bundle import validate_app
        info=validate_app(a.worker.resolve().parents[2])
        assert info['CFBundleShortVersionString']==VERSION,info
        print('Mac 前台应用、Dock 与主程序配置校验通过。')
    im=Image.new('RGB',(600,120),'#303030')
    ImageDraw.Draw(im).text((30,30),'ELLA 2026',font=ImageFont.load_default(size=45),fill='white')
    data=io.BytesIO();im.save(data,format='PNG')
    proc=subprocess.run([str(a.worker.resolve()),'--ocr-worker','--model-dir',str(a.models.resolve()),'--threads','1'],
        input=json.dumps({'image':base64.b64encode(data.getvalue()).decode()})+'\n',text=True,encoding='utf-8',capture_output=True,timeout=90)
    if proc.returncode:raise RuntimeError(proc.stderr)
    result=json.loads(proc.stdout.strip().splitlines()[-1])
    found=' '.join(x['candidates'][0]['text'] for x in result.get('lines',[]))
    if 'ELLA' not in found or '2026' not in found:raise RuntimeError(f'打包识别失败：{result}')
    print('安装后的离线 OCR 测试通过：'+found)
    if a.worker.suffix.lower()=='.exe':
        for device in ('cpu','gpu'):
            proc=subprocess.run([str(a.worker.resolve()),'--ocr-worker','--model-dir',str(a.models.resolve()),'--threads','1','--device',device],
                input=json.dumps({'image':base64.b64encode(data.getvalue()).decode()})+'\n',text=True,encoding='utf-8',capture_output=True,timeout=90)
            if proc.returncode:raise RuntimeError(proc.stderr)
            result=json.loads(proc.stdout.strip().splitlines()[-1])
            actual=' '.join(x['candidates'][0]['text'] for x in result.get('lines',[]))
            if 'ELLA' not in actual or '2026' not in actual:raise RuntimeError(f'{device} 设备路径识别失败：{result}')
            print(f'Windows {device} 设备路径及回退测试通过：{result.get("backend")}')
    korean=Path(__file__).resolve().parent.parent/'assets/smoke-korean.png'
    request=json.dumps({'image':base64.b64encode(korean.read_bytes()).decode(),'dialogue_crop':True})+'\n'
    proc=subprocess.run([str(a.worker.resolve()),'--ocr-worker','--model-dir',str(a.models.resolve()),'--threads','1','--korean'],input=request,text=True,encoding='utf-8',capture_output=True,timeout=90)
    if proc.returncode:raise RuntimeError(proc.stderr)
    result=json.loads(proc.stdout.strip().splitlines()[-1]);found=' '.join(x['candidates'][0]['text'] for x in result.get('lines',[]))
    if '안녕하세요' not in found or '반갑습니다' not in found:raise RuntimeError('韩语模型测试失败：'+str(result))
    print('安装后的离线韩语测试通过：'+found)
    proc=subprocess.run([str(a.worker.resolve()),'--ocr-worker','--model-dir',str(a.models.resolve()),'--threads','1','--auto-language'],input=request*4,text=True,encoding='utf-8',capture_output=True,timeout=120)
    if proc.returncode:raise RuntimeError(proc.stderr)
    auto=json.loads(proc.stdout.strip().splitlines()[-1]);assert auto.get('detected_language')=='ko-KR',auto
    print('安装后的自动韩语选择通过。')
    for route,asset,expected in [
        ('ja_v4','smoke-japanese.png','こんにちは世界'),
        ('cht_v4','smoke-traditional.png','繁體字幕測試'),
        ('latin_v5','smoke-latin.png','Bonjour, ça va?'),
        ('th_v5','smoke-thai.png','สวัสดีครับ'),
    ]:
        sample=Path(__file__).resolve().parent.parent/'assets'/asset
        request=json.dumps({'image':base64.b64encode(sample.read_bytes()).decode()})+'\n'
        proc=subprocess.run([str(a.worker.resolve()),'--ocr-worker','--model-dir',str(a.models.resolve()),'--threads','1','--route',route],input=request,text=True,encoding='utf-8',capture_output=True,timeout=90)
        if proc.returncode:raise RuntimeError(proc.stderr)
        result=json.loads(proc.stdout.strip().splitlines()[-1]);found=' '.join(x['candidates'][0]['text'] for x in result.get('lines',[]))
        if expected not in found:raise RuntimeError(f'{route} 离线识别失败：{found}')
        print(f'安装后的 {route} 离线模型测试通过：{found}')
    import av
    with tempfile.TemporaryDirectory(prefix='ellapuede-smoke-') as tmp:
        root=Path(tmp);video=root/'Episode.01.mp4'
        with av.open(str(video),'w') as output:
            stream=output.add_stream('mpeg4',rate=12);stream.width=600;stream.height=120;stream.pix_fmt='yuv420p'
            for _ in range(24):
                for packet in stream.encode(av.VideoFrame.from_image(im)):output.mux(packet)
            for packet in stream.encode():output.mux(packet)
        proc=subprocess.run([str(a.worker.resolve()),'--preview-worker',str(video),'--seconds','0.5'],capture_output=True,text=True,encoding='utf-8',timeout=30)
        if proc.returncode:raise RuntimeError(proc.stderr)
        preview=json.loads(proc.stdout);assert preview['meta']['width']==600 and preview['image']
        command=[str(a.worker.resolve()),'--worker','extract',str(video),'-o',str(root/'out'),'--engine','rapid','--strategy','accurate','--roi','0,0,1,1','--scale','1','--workers','1','--format','both']
        # One unchanging logo is deliberately insufficient evidence to determine
        # a drama's language. Verify the actionable failure, then its recovery.
        proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=90)
        assert proc.returncode==1 and 'choose_language' in proc.stdout,proc.stdout
        assert not (root/'out/Episode.01.srt').exists()
        print('安装后的语言证据不足提示通过；手选原语言后继续。')
        proc=subprocess.run(command+['--language','en-US'],capture_output=True,text=True,encoding='utf-8',timeout=90)
        if proc.returncode:raise RuntimeError(proc.stdout+'\n'+proc.stderr)
        for suffix in ('srt','ass'):
            text=(root/'out'/('Episode.01.'+suffix)).read_text(encoding='utf-8');assert 'ELLA' in text and '2026' in text
        print('安装后的预览、视频提取及同名 SRT / ASS 导出测试通过。')
        thai_image=Image.open(Path(__file__).resolve().parent.parent/'assets/smoke-thai.png').convert('RGB')
        thai_video=root/'Thai.E01.mp4'
        with av.open(str(thai_video),'w') as output:
            stream=output.add_stream('mpeg4',rate=12);stream.width=900;stream.height=190;stream.pix_fmt='yuv420p'
            for _ in range(30):
                for packet in stream.encode(av.VideoFrame.from_image(thai_image)):output.mux(packet)
            for packet in stream.encode():output.mux(packet)
        command=[str(a.worker.resolve()),'--worker','extract',str(thai_video),'-o',str(root/'thai-out'),
                 '--engine','auto','--language','th-TH','--roi','0,0,1,1','--scale','1',
                 '--workers','1','--format','both']
        proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=120)
        if proc.returncode:raise RuntimeError(proc.stdout+'\n'+proc.stderr)
        for suffix in ('srt','ass'):
            result=(root/'thai-out'/('Thai.E01.'+suffix)).read_text(encoding='utf-8')
            if 'สวัสดีครับ' not in result or 'ยินดีต้อนรับ' not in result:
                raise RuntimeError(f'泰语视频导出错误（{suffix}）：{result}')
        print('安装后的泰语视频完整提取与同名 SRT / ASS 导出通过。')
        args=['extract',str(video),'-o',str(root/'batch-out'),'--engine','rapid','--language','en-US','--roi','0,0,1,1','--scale','1','--workers','1','--format','both']
        requests=json.dumps({'args':args})+'\n'+json.dumps({'args':args})+'\n'+json.dumps({'shutdown':True})+'\n'
        proc=subprocess.run([str(a.worker.resolve()),'--batch-worker'],input=requests,capture_output=True,text=True,encoding='utf-8',timeout=120)
        if proc.returncode:raise RuntimeError(proc.stdout+'\n'+proc.stderr)
        events=[json.loads(line[len('@@ELLAPUEDE@@'):]) for line in proc.stdout.splitlines() if line.startswith('@@ELLAPUEDE@@')]
        assert [e['code'] for e in events if e['type']=='job_done']==[0,0]
        print('安装后的连续任务、后台复用及恢复导出通过。')
        if a.worker.parent.name=='MacOS':
            # Exercise the actual native auto-language controller as well as
            # ONNX workers: a one-logo test cannot verify series language votes.
            native_video=root/'Native.E01.mp4'
            texts=['Hello everyone','Welcome back today','See you tomorrow']
            with av.open(str(native_video),'w') as output:
                stream=output.add_stream('mpeg4',rate=12);stream.width=800;stream.height=240;stream.pix_fmt='yuv420p'
                for text in texts:
                    frame=Image.new('RGB',(800,240),'#303030')
                    ImageDraw.Draw(frame).text((30,140),text,font=ImageFont.load_default(size=45),fill='white')
                    for _ in range(24):
                        for packet in stream.encode(av.VideoFrame.from_image(frame)):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            command=[str(a.worker.resolve()),'--worker','extract',str(native_video),'-o',str(root/'native-out'),
                     '--engine','vision','--language','auto','--roi','0,.5,1,1','--scale','1','--workers','2','--format','both']
            proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=120)
            if proc.returncode:raise RuntimeError(proc.stdout+'\n'+proc.stderr)
            records=list((root/'native-out').rglob('*.subtitles.json'));assert len(records)==1
            record=json.loads(records[0].read_text(encoding='utf-8'))
            assert record['resolved_languages']==['en-US'],record['resolved_languages']
            assert [e['text'] for e in record['events']]==texts,record['events']
            assert 'segmentation_diagnostics' not in record
            native_ass=(root/'native-out/Native.E01.ass').read_text(encoding='utf-8')
            assert r'\pos(' in native_ass and r'\fs' in native_ass
            print('Mac 原生 Vision、自动语言、默认跳过旁路诊断及实测字框 ASS 导出通过。')

if __name__=='__main__':main()
