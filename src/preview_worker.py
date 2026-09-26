"""Cancellable preview decode in a separate process; no OCR engine is loaded."""
import argparse,base64,io,json,sys,tempfile,contextlib
from pathlib import Path

def serve(video):
    """Keep one decoder open while the user scrubs the region preview."""
    import av
    import subtitle_ocr as core
    if not video.is_file():
        print(json.dumps({'request_id':None,'code':'source_missing','error':'找不到原视频'},ensure_ascii=False),flush=True)
        return
    try:
        meta=core.probe(video)
        container=av.open(str(video))
    except Exception:
        print(json.dumps({'request_id':None,'code':'decode_failed','error':'无法读取视频'},ensure_ascii=False),flush=True)
        return
    with container:
        stream=container.streams[meta['stream_index']]
        decoder=None;last_frame=None;last_time=-1.;last_request=-1.
        def frame_at(seconds):
            nonlocal decoder,last_frame,last_time,last_request
            target=seconds+meta['origin']
            # VFR clips may have shorter or longer intervals than fps_hint.
            # Only reuse when this decoded frame is known to cover the request.
            if last_frame is not None and last_request<=target<=last_time+1e-6:
                last_request=target
                return core.oriented_image(last_frame)
            # Nearby forward scrubs continue the open decoder. Repeated seeks
            # into the same GOP otherwise decode its earlier frames each time.
            if decoder is None or target<last_time or target-last_time>.75:
                container.seek(int(target/float(stream.time_base)),stream=stream,backward=True)
                decoder=iter(container.decode(stream))
            for frame in decoder:
                if frame.pts is not None and float(frame.pts*frame.time_base)+1e-6>=target:
                    last_frame=frame;last_time=float(frame.pts*frame.time_base);last_request=target
                    return core.oriented_image(frame)
            raise ValueError(f'无法定位视频帧 {seconds:.3f}s')
        for line in sys.stdin:
            request=None
            try:
                request=json.loads(line);request_id=request['request_id']
                seconds=request.get('seconds',meta['duration']*.33)
                seconds=max(0,min(seconds,max(0,meta['duration']-max(.05,1/max(1,meta['fps_hint'])))))
                original=frame_at(seconds);preview=original.copy();preview.thumbnail((1600,1000))
                buffer=io.BytesIO();preview.save(buffer,format='JPEG',quality=91,subsampling=0)
                result={'request_id':request_id,'meta':meta,'seconds':seconds,
                        'image':base64.b64encode(buffer.getvalue()).decode()}
                if request.get('detect_roi') or request.get('read_roi'):
                    pool=None
                    try:
                        with contextlib.redirect_stdout(sys.stderr),tempfile.TemporaryDirectory(prefix='ellapuede-preview-') as tmp:
                            from hardware_policy import resolve_engine
                            engine=resolve_engine(request.get('engine','auto'),request.get('language','auto'))
                            languages=request.get('language','auto').split(',')
                            # A one-frame preview cannot complete the GPU
                            # comparison; keep this interactive action on CPU.
                            pool=core.VisionPool(languages,[]) if engine=='vision' else core.RapidPool(languages,[],2,device='cpu')
                            if request.get('detect_roi'):
                                calibration=core.calibrate(video,meta,pool,Path(tmp))
                                calibration.update(aspect=meta['width']/meta['height'],region_revision=2,font_calibrated=True)
                                result.update(roi=calibration['roi'],calibration=calibration)
                            if request.get('read_roi'):
                                roi=core.roi_arg(request['read_roi'])
                                text,confidence=core.read_lines(pool.recognize(core.image_crop(original,roi,1 if meta['width']>=960 else 2)))
                                result.update(read_roi=list(roi),text=text,confidence=confidence)
                    except Exception as error:result['roi_error']=str(error)
                    finally:
                        if pool:pool.close()
                print(json.dumps(result,ensure_ascii=False),flush=True)
            except Exception as error:
                print(json.dumps({'request_id':request.get('request_id') if isinstance(request,dict) else None,
                                  'error':str(error)},ensure_ascii=False),flush=True)

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('--serve',action='store_true');p.add_argument('--seconds',type=float);p.add_argument('--detect-roi',action='store_true');p.add_argument('--read-roi');p.add_argument('--detect-language',action='store_true');p.add_argument('--series-file',type=Path);p.add_argument('--engine',default='auto');p.add_argument('--language',default='auto');a=p.parse_args(argv)
    if a.serve:return serve(a.video)
    import subtitle_ocr as core
    meta=core.probe(a.video)
    t=meta['duration']*.33 if a.seconds is None else a.seconds
    t=max(0,min(t,max(0,meta['duration']-max(.05,1/max(1,meta['fps_hint'])))))
    original=core.frame_at(a.video,meta,t);im=original.copy();im.thumbnail((1600,1000))
    buf=io.BytesIO();im.save(buf,format='PNG',compress_level=1)
    result={'meta':meta,'seconds':t,'image':base64.b64encode(buf.getvalue()).decode()}
    if a.detect_roi or a.read_roi or a.detect_language:
        pool=None
        try:
            with contextlib.redirect_stdout(sys.stderr),tempfile.TemporaryDirectory(prefix='ellapuede-preview-') as tmp:
                from hardware_policy import resolve_engine
                engine=resolve_engine(a.engine,a.language)
                pool=core.VisionPool(a.language.split(','),[]) if engine=='vision' else core.RapidPool(a.language.split(','),[],2,device='cpu')
                roi=core.roi_arg(a.read_roi) if a.read_roi else None
                if a.detect_language or ('auto' in pool.languages and a.detect_roi):
                    from language_detection import resolve_language
                    result['resolved_languages']=resolve_language(a.video,meta,roi,pool,a.series_file)
                if a.detect_roi:
                    calibration=core.calibrate(a.video,meta,pool,Path(tmp))
                    calibration.update(aspect=meta['width']/meta['height'],region_revision=2,font_calibrated=True)
                    result.update(roi=calibration['roi'],calibration=calibration)
                if roi:
                    text,confidence=core.read_lines(pool.recognize(core.image_crop(original,roi,1 if meta['width']>=960 else 2)))
                    result.update(read_roi=list(roi),text=text,confidence=confidence)
        except Exception as e:result['roi_error']=str(e)
        finally:
            if pool:pool.close()
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
