"""Conservative text-shape grouping with independent first/middle/last OCR checks.
All original PTS survive. Any sample disagreement falls back to every frame.
"""
from collections import deque,OrderedDict
from concurrent.futures import ThreadPoolExecutor,Future
import hashlib,json,sqlite3,time,threading
import numpy as np
from frame_features import text_mask

class ExactFrameMemo:
    """Share only byte-identical OCR inputs; no mask/presence guess is involved."""
    def __init__(self,pool):
        self.pool=pool;self.lock=threading.Lock();self.recent=OrderedDict();self.calls=0;self.reused=0
    def recognize(self,image):
        key=(image.size,image.mode,hashlib.sha256(image.tobytes()).digest(),image.info.get('ellapuede_pixel_scale',1),bool(image.info.get('ellapuede_dialogue_crop')))
        return self._get(key,lambda:image)

    def recognize_prepared(self,image,key,scale):
        # The group has already hashed this exact unscaled crop. The resampling
        # transform is deterministic; include its settings instead of hashing
        # the enlarged pixel buffer again. Only the cache owner resizes it.
        import subtitle_ocr as core
        return self._get(('prepared',key,scale),lambda:core.image_crop(image,(0,0,1,1),scale))

    def _get(self,key,prepare):
        with self.lock:
            future=self.recent.get(key);owner=future is None
            if owner:
                future=Future();self.recent[key]=future;self.calls+=1
                while len(self.recent)>128:self.recent.popitem(last=False)
            else:self.recent.move_to_end(key);self.reused+=1
        if owner:
            try:future.set_result(self.pool.recognize(prepare()))
            except BaseException as error:future.set_exception(error)
        return future.result()

def compatible(a,b):
    if a.shape!=b.shape:return False
    n=np.count_nonzero(a|b)
    if n<20:return False
    diff=a^b
    if np.count_nonzero(diff)>max(2,n*.035):return False
    h,w=diff.shape;tile=np.pad(diff,((0,(-h)%16),(0,(-w)%16)))
    return not np.any(tile.reshape(tile.shape[0]//16,16,tile.shape[1]//16,16).sum(axis=(1,3))>5)

def recognize_group(pool,images,scale):
    import subtitle_ocr as core
    memo={};hashes={};calls=0
    def recognize(i):
        nonlocal calls
        image=images[i]
        if i not in hashes:
            hashes[i]=(image.size,image.mode,hashlib.sha256(image.tobytes()).digest(),image.info.get('ellapuede_pixel_scale',1),bool(image.info.get('ellapuede_dialogue_crop')))
        key=hashes[i]
        if key not in memo:
            memo[key]=(pool.recognize_prepared(image,key,scale) if isinstance(pool,ExactFrameMemo)
                       else pool.recognize(core.image_crop(image,(0,0,1,1),scale)))
            calls+=1
        return memo[key]
    sample=sorted(set([0,len(images)//2,len(images)-1]));results=[recognize(i) for i in sample]
    texts=[core.read_lines(r) for r in results]
    if len(images)>2 and all(t[0] and t[1]>=.75 and core.key(t[0])==core.key(texts[0][0]) for t in texts):
        result=results[max(range(len(results)),key=lambda i:texts[i][1])]
        return [result]*len(images),calls,True
    return [recognize(i) for i in range(len(images))],calls,False

def group_capacity(image):
    # At most 8 MiB of unscaled RGB crops per queued group; one huge crop
    # still fits as a singleton and is never accumulated with more images.
    return max(1,min(64,(8*1024*1024)//max(1,image.width*image.height*3)))

def scan_frames(path,meta,roi,pool,cache,workers,scale):
    import av
    import subtitle_ocr as core
    from video_crops import FrameCropper
    memo=ExactFrameMemo(pool)
    cropper=FrameCropper(roi)
    db=sqlite3.connect(cache/'frames.sqlite');db.execute('CREATE TABLE IF NOT EXISTS frames (idx INTEGER PRIMARY KEY,t REAL,end REAL,data TEXT)')
    last_commit=time.monotonic();last_emit=last_commit;uncommitted=0;commits=0
    done={r[0] for r in db.execute('SELECT idx FROM frames')};pending=deque();calls=0;new_rows=0;count=0;started=time.monotonic();group=[];images=[];anchor=None;groups=0
    def accept():
        nonlocal new_rows,calls,groups,last_commit,last_emit,uncommitted,commits
        items,future=pending.popleft();results,n,verified=future.result();calls+=n;groups+=int(verified)
        for (idx,t,end),result in zip(items,results):db.execute('INSERT OR REPLACE INTO frames VALUES (?,?,?,?)',(idx,t,end,json.dumps(result,ensure_ascii=False)));new_rows+=1
        now=time.monotonic();uncommitted+=len(items)
        if uncommitted>=64 or now-last_commit>=.5:
            db.commit();last_commit=now;uncommitted=0;commits+=1
        if now-last_emit>=.2:
            core.control.emit('progress',seconds=items[-1][2],duration=meta['duration'],new_frames=new_rows,fps=round(new_rows/max(.001,now-started),1));last_emit=now
    try:
        with av.open(str(path)) as c,ThreadPoolExecutor(max_workers=workers) as ex:
            stream=c.streams[meta['stream_index']];stream.codec_context.thread_count=2;last=None
            def submit():
                nonlocal group,images,anchor
                if group:
                    pending.append((group,ex.submit(recognize_group,memo,images,scale)));group=[];images=[];anchor=None
                    if len(pending)>=workers*2:accept()
            def add(idx,t,end,image):
                nonlocal anchor,last_emit
                if idx in done:
                    submit();now=time.monotonic()
                    if now-last_emit>=.2:
                        core.control.emit('progress',seconds=end,duration=meta['duration'],new_frames=new_rows,cache_frames=len(done));last_emit=now
                    return
                crop=cropper.crop(image);mask=text_mask(crop)
                crop.info['ellapuede_text_mask']=mask
                if group and (not compatible(mask,anchor) or t-group[0][1]>=1.5 or len(images)>=group_capacity(crop)):submit()
                if not group:anchor=mask
                group.append((idx,t,end));images.append(crop)
            for idx,f in enumerate(c.decode(stream)):
                core.control.check()
                if f.pts is None:raise ValueError('视频帧缺少时间戳，无法可靠定位字幕。')
                t=float(f.pts*f.time_base)-meta['origin']
                if last:
                    if t<=last[1]:raise ValueError('视频时间戳不递增，请检查素材。')
                    add(last[0],max(0,last[1]),t,last[2])
                duration=float(f.duration*f.time_base) if f.duration else 1/meta['fps_hint']
                last=(idx,t,f if idx not in done else None,duration);count=idx+1
            if last:add(last[0],max(0,last[1]),min(meta['duration'],last[1]+last[3]),last[2])
            submit()
            while pending:accept()
        db.commit();commits+=1
        core.control.emit('progress',seconds=meta['duration'],duration=meta['duration'],new_frames=new_rows,fps=round(new_rows/max(.001,time.monotonic()-started),1))
        rows=[]
        for idx,t,end,data in db.execute('SELECT idx,t,end,data FROM frames ORDER BY idx'):
            result=json.loads(data);text,confidence=core.read_lines(result);rows.append({'frame':idx,'start':t,'end':end,'text':text,'confidence':confidence,'ocr':result})
        if len(rows)!=count:raise ValueError('帧缓存不完整，已保留可恢复部分。')
        return rows,{'decoded_frames':count,'new_ocr_frames':memo.calls,'identical_frames_reused':memo.reused,'verified_groups':groups,'new_frame_rows':new_rows,'cache_frames':len(done),'seconds':round(time.monotonic()-started,2),'cache_commits':commits,'strategy':'verified-text-shapes'}
    finally:db.commit();db.close()
