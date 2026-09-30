"""Image-backed retry of brief unstable OCR; no fuzzy text replacement."""
from collections import deque,Counter
from contextlib import ExitStack
from threading import BoundedSemaphore
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

def comparison_key(text):
    import subtitle_ocr as core
    text=core.key(text)
    return "".join(text.split()) if any("가"<=ch<="힣" for ch in text) else text

def related_readings(a,b):
    """Find retry candidates only; a replacement still needs current-image OCR."""
    a,b=comparison_key(a),comparison_key(b)
    if not a or not b:return False
    if SequenceMatcher(None,a,b).ratio()>=.8:return True
    short,long=(a,b) if len(a)<len(b) else (b,a)
    return len(short)>=3 and short in long

def unstable_frames(rows):
    import subtitle_ocr as core
    runs=[]
    for i,row in enumerate(rows):
        k=comparison_key(row['text'])
        if runs and runs[-1][0]==k:runs[-1][1].append(i)
        else:runs.append((k,[i]))
    candidates=set()
    for n,(text,indices) in enumerate(runs):
        duration=rows[indices[-1]]['end']-rows[indices[0]]['start']
        if duration>.60:continue
        if not text:
            # A blank at the start/end of a caption is real until both sides
            # show the *same* held subtitle. Rechecking ordinary transition
            # gaps costs many OCR calls and can stretch text into silence.
            if (n==0 or n==len(runs)-1 or
                    not runs[n-1][0] or runs[n-1][0]!=runs[n+1][0]):continue
            candidates.update(indices);continue
        neighbors=[runs[j][0] for j in range(max(0,n-2),min(len(runs),n+3)) if j!=n and runs[j][0]]
        if any(related_readings(text,t) for t in neighbors):candidates.update(indices)
    return sorted(candidates)

def reference_band(crop,reference):
    import subtitle_ocr as core
    lines=reference.get('ocr',{}).get('lines',[])
    if not lines:return crop
    height=max(x['box'][3] for x in lines);pad=max(.025,height*.3)
    y1=max(0,min(x['box'][1] for x in lines)-pad)
    y2=min(1,max(x['box'][1]+x['box'][3] for x in lines)+pad)
    return core.image_crop(crop,(0,y1,1,y2),1)

def retry_image(pool,crop,scale,reference):
    import subtitle_ocr as core
    from frame_features import text_mask
    from PIL import Image
    import numpy as np
    variants=[crop];band=None
    lines=reference.get('ocr',{}).get('lines',[])
    if lines:
        left=max(0,min(x['box'][0] for x in lines)-.008);top=max(0,min(x['box'][1] for x in lines)-.02)
        right=min(1,max(x['box'][0]+x['box'][2] for x in lines)+.008);bottom=min(1,max(x['box'][1]+x['box'][3] for x in lines)+.02)
        variants.insert(0,core.image_crop(crop,(left,top,right,bottom),1))
        # Keep horizontal context; changing background outside the text line can
        # corrupt otherwise stable glyphs. Padding scales with actual glyph height.
        band=reference_band(crop,reference)
    expected=comparison_key(reference['text']);votes=0
    # A higher resolution can *lose* a line in Apple's Thai OCR even when the
    # unscaled pixels recognize both lines. Retry the complete subtitle band
    # at the other size before narrow crops or monochrome masks.
    alternate=1 if scale>1 else 2
    attempts=[(crop,alternate)]+ ([(band,scale),(band,alternate)] if band is not None else [])+[(im,max(scale,3)) for im in variants]
    seen=set()
    for im,factor in attempts:
        signature=(im.size,factor,__import__('hashlib').sha256(im.tobytes()).digest())
        if signature in seen:continue
        seen.add(signature)
        prepared=core.image_crop(im,(0,0,1,1),factor)
        prepared.info['ellapuede_image_retry']=True
        result=pool.recognize(prepared);text,confidence=core.read_lines(result)
        if comparison_key(text)==expected and confidence>=.75:return text,confidence
        votes+=int(comparison_key(text)==expected and confidence>=.5)
    mask=text_mask(crop)
    if np.count_nonzero(mask)>20:
        im=Image.fromarray(np.uint8(mask)*255).convert('RGB')
        im.info['ellapuede_recheck_mask']=True
        for factor in (2,3):
            prepared=core.image_crop(im,(0,0,1,1),factor)
            prepared.info['ellapuede_image_retry']=True
            result=pool.recognize(prepared);text,confidence=core.read_lines(result)
            if comparison_key(text)==expected and confidence>=.5:
                votes+=1
                if votes>=2:return text,confidence
    return None

def retry_blank(pool,crop):
    """An isolated OCR hit is removed only if three current-image retries are empty."""
    import subtitle_ocr as core
    from frame_features import text_mask
    from PIL import Image
    import numpy as np
    for factor in (1,3):
        text,_=core.read_lines(pool.recognize(core.image_crop(crop,(0,0,1,1),factor)))
        if text:return None
    mask=Image.fromarray(np.uint8(text_mask(crop))*255).convert('RGB')
    text,_=core.read_lines(pool.recognize(core.image_crop(mask,(0,0,1,1),2)))
    return None if text else ('',1.)

def retry_punctuation(secondary,crop,expected):
    """Resolve a punctuation-only retry from two complete current-frame crops.

    Keep the full ROI so a real speaker dash cannot be hidden by the neighbor's
    narrower box. Both readings must exactly reproduce the observed reference.
    """
    import subtitle_ocr as core
    readings=[]
    for factor in (1,2):
        result=secondary.recognize(core.image_crop(crop,(0,0,1,1),factor))
        if result is None:return None
        text,score=core.read_lines(result)
        if score<.85 or core.key(text)!=core.key(expected):return None
        readings.append((text,score))
    return readings[0][0],min(score for _,score in readings)

def refine(rows,path,meta,roi,pool,scale,workers=2,skip_indices=()):
    import av
    import subtitle_ocr as core
    from video_crops import FrameCropper,requested_frames,configure_decoder
    spacing_repairs=0
    if getattr(pool,'languages',[])==['ko-KR']:
        from spacing_refine import refine as refine_spacing
        spacing_repairs=refine_spacing(rows,path,meta,roi)
    skip_indices=set(skip_indices)
    candidates=set(unstable_frames(rows))-skip_indices
    original=[r['text'] for r in rows];references={};allowed={}
    if getattr(pool,'languages',[])==['ko-KR']:
        i=1
        while i<len(rows)-1:
            if not original[i] or original[i-1]:i+=1;continue
            end=i
            while end+1<len(rows) and original[end+1]:end+=1
            if end+1<len(rows) and rows[end]['end']-rows[i]['start']<=.081:
                for j in range(i,end+1):
                    if j not in skip_indices:
                        references[j]={'text':'','ocr':{'lines':[]}};allowed[j]={''}
            i=end+1
    for i in candidates:
        indexes=range(max(0,i-20),min(len(rows),i+21));counts=Counter(original[j] for j in indexes if j!=i and original[j] and original[j]!=original[i] and (not original[i] or related_readings(original[i],original[j])))
        if not counts:continue
        expected,n=counts.most_common(1)[0]
        own=sum(original[j]==original[i] for j in indexes)
        if n<3 or expected==original[i] or len(expected.splitlines())<len(original[i].splitlines()):continue
        if original[i]:
            if n<own:continue
            if n==own:
                # A tie is only a retry candidate when one observed reading has
                # clearly stronger confidence. Never copy it without recognizing
                # that same text from the current image below.
                expected_score=sum(rows[j].get('confidence',0) for j in indexes if original[j]==expected)/n
                own_score=sum(rows[j].get('confidence',0) for j in indexes if original[j]==original[i])/own
                if expected_score<=own_score+.05:continue
        j=min((j for j in indexes if original[j]==expected),key=lambda j:abs(i-j));references[i]=dict(rows[j]);allowed[i]={core.key(original[k]) for k in indexes if original[k]}
    if not references:return spacing_repairs
    repaired=spacing_repairs;done=0;pending=deque();last=max(references)
    core.control.emit('phase',phase=f'自动核验 {len(references)} 个可疑画面')
    core.control.emit('verify_progress',done=0,total=len(references),base=.8,span=.10)
    def accept():
        nonlocal repaired,done
        i,future=pending.popleft();result=future.result();row=rows[i]
        if result and core.key(result[0])!=core.key(row['text']):
            text,confidence=result;row['primary_text']=row['text'];row['text']=text;row['confidence']=confidence;row['image_verified']=True;repaired+=1
        done+=1
        if done%16==0 or done==len(references):
            core.control.emit('verify_progress',done=done,total=len(references),base=.8,span=.10)
    with ExitStack() as stack:
        cropper=FrameCropper(roi)
        # Independent English OCR is used only on unstable Apple Vision frames.
        # It must recognize a string on THIS image that was also observed nearby.
        secondary=None;punctuation_secondary=None;slots=BoundedSemaphore(min(2,workers))
        if getattr(pool,'name','').startswith('AppleVision') and pool.languages==['en-US']:
            from optional_ocr import OptionalOCR
            secondary=OptionalOCR(pool,'英语第二引擎复核',lambda:core.RapidPool(['en-US'],[],1))
            stack.callback(secondary.close)
        if (getattr(pool,'name','').startswith('AppleVision') and
                len(getattr(pool,'languages',[]))==1 and pool.languages[0] not in ('auto','en-US')):
            from optional_ocr import OptionalOCR
            punctuation_secondary=OptionalOCR(pool,'标点独立复核',lambda:core.RapidPool(pool.languages,[],1,device='cpu'))
            stack.callback(punctuation_secondary.close)
        def verify(i,crop):
            if not references[i]['text']:return retry_blank(pool,crop)
            if secondary:
                with slots:
                    band=reference_band(crop,references[i])
                    seen=set()
                    for image,factor in [(crop,scale),(band,scale),(band,2)]:
                        # With scale=2 the last two inputs are the same object
                        # and transform. Re-running them adds no image evidence.
                        signature=(id(image),factor)
                        if signature in seen:continue
                        seen.add(signature)
                        result=secondary.recognize(core.image_crop(image,(0,0,1,1),factor),
                                                   dialogue_min_height=getattr(pool,'dialogue_min_height',0))
                        if result is None:break
                        text,confidence=core.read_lines(result)
                        if confidence>=.85 and core.key(text) in allowed[i]:return text,confidence
            result=retry_image(pool,crop,scale,references[i])
            letters=lambda text:''.join(char for char in core.key(text) if char.isalnum())
            if (result is None and punctuation_secondary and original[i] and
                    letters(original[i])==letters(references[i]['text'])):
                with slots:return retry_punctuation(punctuation_secondary,crop,references[i]['text'])
            return result
        container=stack.enter_context(av.open(str(path)))
        executor=stack.enter_context(ThreadPoolExecutor(max_workers=workers))
        stream=configure_decoder(container.streams[meta['stream_index']])
        for i,frame in requested_frames(container,stream,rows,references,meta):
            crop=cropper.crop(frame)
            pending.append((i,executor.submit(verify,i,crop)))
            if len(pending)>=workers*2:accept()
        while pending:accept()
    if repaired>spacing_repairs and getattr(pool,'languages',[])==['ko-KR']:
        repaired+=refine_spacing(rows,path,meta,roi)
    return repaired
