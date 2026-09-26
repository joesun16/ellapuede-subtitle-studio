"""CI-only synthetic Windows CPU comparison; never uploads user video."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import av

def main():
    parser=argparse.ArgumentParser();parser.add_argument('baseline',type=Path);parser.add_argument('output',type=Path);a=parser.parse_args();root=Path(__file__).resolve().parent.parent;a.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ellapuede-benchmark-') as tmp:
        tmp=Path(tmp);old=tmp/'previous';old.mkdir()
        with zipfile.ZipFile(a.baseline) as archive:archive.extractall(old)
        shutil.copytree(root/'models',old/'models')
        for p in root.glob('glyph_features*.pyd'):shutil.copy2(p,old/p.name)
        video=tmp/'Synthetic.E01.mp4';font=ImageFont.load_default(size=30)
        with av.open(str(video),'w') as container:
            stream=container.add_stream('mpeg4',rate=12);stream.width=600;stream.height=200;stream.pix_fmt='yuv420p'
            for i in range(72):
                im=Image.new('RGB',(600,200),(25+i%16,33,40));draw=ImageDraw.Draw(im)
                draw.rectangle((i*7%600,0,min(599,i*7%600+60),199),fill=(75,90,100))
                draw.text((55,100),['We can do this.','Please wait for me.','Are you ready?','Let us go together.'][i//18],font=font,fill='white',stroke_width=2,stroke_fill='black')
                for packet in stream.encode(av.VideoFrame.from_image(im)):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        report={'scope':'Synthetic 6-second video, Windows CI CPU only. Not a real drama or GPU benchmark.','runs':[]}
        documents={}
        for mode in range(3):
            for label,source in [('previous',old),('current',root)]:
                code='import json;from hardware_policy import plan,snapshot;print(json.dumps({"hardware":snapshot(),"policy":plan("rapid",'+str(mode)+',4)}))'
                cfg=json.loads(subprocess.check_output([sys.executable,'-c',code],cwd=source,text=True,encoding='utf-8'));report['hardware']=cfg['hardware'];policy=cfg['policy'];out=tmp/f'{label}-{mode}'
                command=[sys.executable,str(source/'launch.py'),'--worker','extract',str(video),'-o',str(out/'subtitles'),'--cache-root',str(out/'cache'),'--engine','rapid','--language','en-US','--workers',str(policy['workers']),'--threads',str(policy['threads']),'--roi','0,.35,1,.95','--scale','2','--format','both','--organize-output']
                result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=180)
                if result.returncode:raise RuntimeError(result.stdout+'\n'+result.stderr)
                document=json.loads(next((out/'cache/results').rglob('*.subtitles.json')).read_text(encoding='utf-8'));documents[label,mode]=[(e['text'],round(e['start'],6),round(e['end'],6)) for e in document['events']]
                entry={'version':document['tool_version'],'label':label,'mode':mode,'policy':policy,'performance':document['performance'],'events':len(document['events'])};report['runs'].append(entry);print(json.dumps(entry),flush=True)
            report.setdefault('identical_text_and_timing',[]).append(documents['previous',mode]==documents['current',mode])
            expected=[(t,i*1.5,(i+1)*1.5) for i,t in enumerate(['We can do this.','Please wait for me.','Are you ready?','Let us go together.'])]
            actual=documents['current',mode]
            correct=len(actual)==len(expected) and all(x[0]==y[0] and abs(x[1]-y[1])<=1/12+.001 and abs(x[2]-y[2])<=1/12+.001 for x,y in zip(actual,expected))
            report.setdefault('matches_rendered_ground_truth',[]).append(correct)
        (a.output/'Windows-CPU-模式实测.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not all(report['matches_rendered_ground_truth']):raise RuntimeError('Current OCR differs from rendered text or frame timing; review before release.')
if __name__=='__main__':main()
