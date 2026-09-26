"""Language-routed offline OCR with independent CPU/DirectML device choice."""
import argparse
import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import time
import os

def same_ocr_reading(cpu,gpu,width,height):
    """A device may accelerate inference only when sampled OCR stays aligned."""
    import numpy as np
    if list(cpu.txts if cpu.txts is not None else [])!=list(gpu.txts if gpu.txts is not None else []):return False
    a=np.asarray(cpu.boxes if cpu.boxes is not None else [])
    b=np.asarray(gpu.boxes if gpu.boxes is not None else [])
    if a.shape!=b.shape or (a.size and np.max(np.abs(a-b))>max(2,min(width,height)*.005)):return False
    scores_a=list(cpu.scores if cpu.scores is not None else []);scores_b=list(gpu.scores if gpu.scores is not None else [])
    return len(scores_a)==len(scores_b) and all(abs(x-y)<=.03 for x,y in zip(scores_a,scores_b))

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-dir',type=Path,required=True)
    parser.add_argument('--korean',action='store_true')
    parser.add_argument('--english',action='store_true')
    parser.add_argument('--route',choices=['ch_v6','en_v5','ko_v5','th_v5','latin_v5','ja_v4','cht_v4'])
    parser.add_argument('--cpu',action='store_true')
    parser.add_argument('--device',choices=['auto','cpu','gpu'],default='auto')
    parser.add_argument('--auto-language',action='store_true')
    parser.add_argument('--threads',type=int,default=2)
    args=parser.parse_args(argv)
    # This worker must remain offline even if an upstream library tries to fetch assets.
    def offline(event,values):
        if event in ('socket.connect','socket.getaddrinfo'):
            raise RuntimeError('识别不允许联网。请重新安装含完整离线模型的安装包。')
    sys.addaudithook(offline)
    import numpy as np
    from PIL import Image
    from rapidocr import RapidOCR, OCRVersion, ModelType, LangRec
    from ocr_routes import ROUTES
    route_id=args.route or ('ko_v5' if args.korean else 'en_v5' if args.english else 'ch_v6')
    route=ROUTES[route_id]
    det=args.model_dir/route['det']
    rec=args.model_dir/route['rec']
    cls=args.model_dir/'ch_ppocr_mobile_v2.0_cls_mobile.onnx'
    from model_manifest import MODELS
    import hashlib
    required={route['det'],route['rec'],cls.name}
    if args.auto_language:required.add(ROUTES['ko_v5']['rec'])
    for name in required:
        _,_,digest=MODELS[name]
        model=args.model_dir/name
        if not model.exists() or hashlib.sha256(model.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('安装包的离线模型缺失或损坏，请重新安装完整应用：'+name)
    params={'Global.use_cls':False,'Global.log_level':'error','Global.text_score':.3,
            'Cls.model_path':str(cls),'Det.model_path':str(det),'Det.ocr_version':getattr(OCRVersion,route['det_version']),
            'Det.model_type':getattr(ModelType,route['det_type']),'Det.limit_side_len':960,'Det.limit_type':'max',
            'Rec.model_path':str(rec),'Rec.ocr_version':getattr(OCRVersion,route['rec_version']),
            'Rec.model_type':getattr(ModelType,route['rec_type']),'Rec.lang_type':LangRec(route['script']),
            'EngineConfig.onnxruntime.intra_op_num_threads':args.threads,
            'EngineConfig.onnxruntime.inter_op_num_threads':1,
            'EngineConfig.onnxruntime.enable_cpu_mem_arena':False}
    import onnxruntime as ort
    def build(config,gpu=False):
        values=dict(config);values['EngineConfig.onnxruntime.use_dml']=gpu
        from rapidocr.inference_engine.onnxruntime.main import OrtInferSession
        original=OrtInferSession._init_sess_opts
        def options(cfg):
            opt=original(cfg)
            if gpu:opt.enable_mem_pattern=False;opt.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            return opt
        OrtInferSession._init_sess_opts=staticmethod(options)
        try:
            with contextlib.redirect_stdout(sys.stderr):return RapidOCR(params=values)
        finally:OrtInferSession._init_sess_opts=staticmethod(original)
    engine=build(params);backend='CPU';gpu_engine=None;gpu_samples=[]
    device='cpu' if args.cpu else args.device
    gpu_pending=os.name=='nt' and device!='cpu' and 'DmlExecutionProvider' in ort.get_available_providers()
    if device=='gpu' and not gpu_pending:
        print('当前设备不可用 DirectML，已使用 CPU。',file=sys.stderr,flush=True)
    korean_engine=None;language_samples=0;korean_votes=0;language_locked=not args.auto_language;frame_requests=0
    def infer(instance,array):
        with contextlib.redirect_stdout(sys.stderr):return instance(array,use_cls=False)
    for raw in sys.stdin:
        # Invalid input must never fall back using the previous frame's array.
        array=None;w=h=0
        try:
            data=json.loads(raw)
            im=Image.open(io.BytesIO(base64.b64decode(data['image']))).convert('RGB')
            w,h=im.size
            array=np.asarray(im)[:,:,::-1].copy()
            frame_requests+=1
            start=time.monotonic();result=infer(engine,array);cpu_seconds=time.monotonic()-start
            # Do not compile GPU sessions at startup or benchmark a blank frame.
            # Compare several real subtitle crops using the same language model.
            if gpu_pending and result.txts and (device=='gpu' or frame_requests>=32):
                try:
                    if gpu_engine is None:
                        gpu_engine=build(params,True)
                        if not all('DmlExecutionProvider' in component.session.session.get_providers() for component in (gpu_engine.text_det,gpu_engine.text_rec)):
                            raise RuntimeError('模型未在 DirectML 上执行')
                        infer(gpu_engine,array) # one-time graph compilation and warmup
                    start=time.monotonic();candidate=infer(gpu_engine,array);gpu_seconds=time.monotonic()-start
                    if not same_ocr_reading(result,candidate,w,h):
                        gpu_pending=False;gpu_engine=None
                        print('DirectML 与 CPU 的字幕字框或文字不同，已保留 CPU 结果。',file=sys.stderr,flush=True)
                    else:
                        gpu_samples.append((cpu_seconds,gpu_seconds))
                        if len(gpu_samples)>=3:
                            from statistics import median
                            cpu_speed=median(x for x,_ in gpu_samples);gpu_speed=median(y for _,y in gpu_samples)
                            if device=='gpu' or gpu_speed<cpu_speed*.85:
                                engine=gpu_engine;result=candidate;backend=f'DirectML（同模型 3 帧：CPU {cpu_speed:.3f}s / GPU {gpu_speed:.3f}s）'
                            else:
                                print('此显卡在当前字幕区域未快于 CPU，继续使用 CPU。',file=sys.stderr,flush=True)
                            gpu_pending=False;gpu_engine=None
                except Exception as error:
                    gpu_pending=False;gpu_engine=None
                    print('DirectML 试运行失败，继续使用 CPU：'+str(error),file=sys.stderr,flush=True)
            if args.auto_language and not language_locked:
                if korean_engine is None:
                    values=dict(params);values.update({'Rec.model_path':str(args.model_dir/'korean_PP-OCRv5_rec_mobile.onnx'),'Rec.ocr_version':OCRVersion.PPOCRV5,'Rec.model_type':ModelType.MOBILE,'Rec.lang_type':LangRec.KOREAN})
                    korean_engine=build(values)
                candidate=infer(korean_engine,array);txt=''.join(candidate.txts or []);hangul=sum('가'<=c<='힣' for c in txt)
                score=sum(candidate.scores or [])/max(1,len(candidate.scores or []))
                other=sum(result.scores or [])/max(1,len(result.scores or []))
                valid=hangul>=2 and hangul/max(1,sum(c.isalpha() for c in txt))>.6 and score>=.82 and score>=other-.03
                if valid:korean_votes+=1
                if txt or result.txts:language_samples+=1
                if korean_votes>=3:
                    engine=korean_engine;params=values;korean_engine=None;language_locked=True;result=candidate;backend='CPU · 自动检测韩语'
                elif language_samples>=12:
                    korean_engine=None;language_locked=True

            lines=[]
            if result.txts:
                for box,text,score in zip(result.boxes,result.txts,result.scores):
                    x1,y1=box.min(axis=0);x2,y2=box.max(axis=0)
                    lines.append({'box':[float(x1/w),float(y1/h),float((x2-x1)/w),float((y2-y1)/h)],
                                  'candidates':[{'text':text,'confidence':float(score)}]})
            if data.get('dialogue_crop') and (route_id=='ko_v5' or backend.endswith('自动检测韩语')) and lines:
                from korean_raster import repair
                from rapidocr.ch_ppocr_rec.typings import TextRecInput
                def recognize_batch(images):
                    arrays=[np.asarray(image)[:,:,::-1].copy() for image in images]
                    with contextlib.redirect_stdout(sys.stderr):
                        readings=engine.text_rec(TextRecInput(img=arrays,return_word_box=False))
                    return list(zip(readings.txts or [],readings.scores or []))
                lines=repair(im,lines,recognize_batch)
            print(json.dumps({'lines':lines,'backend':backend,'detected_language':'ko-KR' if backend.endswith('自动检测韩语') else None,'revision':'ko_v5' if backend.endswith('自动检测韩语') else route_id},ensure_ascii=False),flush=True)
        except Exception as error:
            if backend.startswith('DirectML') and array is not None:
                try:
                    engine=build(params);backend='CPU · 显卡异常后回退'
                    result=infer(engine,array);lines=[]
                    for box,text,score in zip(result.boxes if result.boxes is not None else [],result.txts or [],result.scores or []):
                        x1,y1=box.min(axis=0);x2,y2=box.max(axis=0);lines.append({'box':[float(x1/w),float(y1/h),float((x2-x1)/w),float((y2-y1)/h)],'candidates':[{'text':text,'confidence':float(score)}]})
                    print(json.dumps({'lines':lines,'backend':backend},ensure_ascii=False),flush=True);continue
                except Exception as fallback_error:error=RuntimeError(f'显卡识别失败，CPU 重试也失败：{fallback_error}')
            print(json.dumps({'error':str(error)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
