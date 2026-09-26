"""Resolve short OCR substitutions only when the actual subtitle glyphs match.

The video is decoded once for a small set of suspect frames. No language model,
dictionary, or guessed text enters the export: the replacement was read by OCR
on both sides of the suspect frame, and the subtitle pixels must agree.
"""
from __future__ import annotations

from contextlib import ExitStack
from difflib import SequenceMatcher

import numpy as np


def _runs(rows):
    import subtitle_ocr as core
    runs=[]
    for i,row in enumerate(rows):
        value=core.key(row['text'])
        if runs and runs[-1][0]==value:runs[-1][2]=i+1
        else:runs.append([value,i,i+1])
    return runs


def _bounds(*rows):
    boxes=[]
    for row in rows:
        wanted=row['text']
        for line in row.get('ocr',{}).get('lines',[]):
            if not line.get('candidates'):continue
            candidate=line['candidates'][0]
            if candidate.get('confidence',0)<.5 or candidate.get('text','') not in wanted:continue
            boxes.append(line['box'])
    if not boxes:return None
    x1=max(0,min(box[0] for box in boxes)-.025)
    y1=max(0,min(box[1] for box in boxes)-.04)
    x2=min(1,max(box[0]+box[2] for box in boxes)+.025)
    y2=min(1,max(box[1]+box[3] for box in boxes)+.04)
    return (x1,y1,x2,y2)


def _tight_bounds(row):
    """Include the complete observed glyph box with little moving scenery."""
    boxes=[line['box'] for line in row.get('ocr',{}).get('lines',[])
           if line.get('candidates') and
           line['candidates'][0].get('confidence',0)>=.5 and
           line['candidates'][0].get('text','') in row['text']]
    if not boxes:return None
    return (max(0,min(box[0] for box in boxes)-.005),
            max(0,min(box[1] for box in boxes)-.01),
            min(1,max(box[0]+box[2] for box in boxes)+.005),
            min(1,max(box[1]+box[3] for box in boxes)+.01))


def _blank_targets(rows,runs):
    """Recheck brief OCR-empty intervals against nearby actually read glyphs."""
    found=[]
    for n,(value,start,end) in enumerate(runs):
        if value or rows[end-1]['end']-rows[start]['start']>.60:continue
        anchors=[]
        bracketed_text=None
        if 0<n<len(runs)-1 and runs[n-1][0] and runs[n-1][0]==runs[n+1][0]:
            left,right=runs[n-1],runs[n+1]
            if all(last-first>=2 and sum(rows[i]['confidence']>=.8 for i in range(first,last))>=2
                   for _,first,last in (left,right)):
                bracketed_text=left[0]
        for adjacent in (n-1,n+1):
            if not 0<=adjacent<len(runs):continue
            text,first,last=runs[adjacent]
            if not text or last-first<2:continue
            # A single high-confidence guess is not enough to fill missing PTS.
            confident=[i for i in range(first,last) if rows[i]['confidence']>=.8]
            if len(confident)<2:continue
            # A preceding repair may have restored the nearest frame's text
            # while its original OCR boxes remain empty. Use the closest
            # observed glyph box in this same anchored run.
            references=reversed(confident) if adjacent<n else confident
            for reference in references:
                bounds=_tight_bounds(rows[reference])
                if bounds:
                    anchors.append((reference,text,bounds))
                    break
        if not anchors:continue
        found.append({'kind':'blank','suspects':list(range(start,end)),
                      'anchors':anchors,'bracketed_text':bracketed_text,
                      'last':max(end-1,*(item[0] for item in anchors))})
    return found


def targets(rows):
    """Return narrow A-B-A OCR anomalies, never ordinary caption transitions."""
    import subtitle_ocr as core
    found=[];runs=_runs(rows)
    for n in range(1,len(runs)-1):
        variant,start,end=runs[n]
        left,ls,le=runs[n-1];right,rs,re=runs[n+1]
        if not variant or not left or left!=right or variant==left:continue
        if rows[end-1]['end']-rows[start]['start']>.45:continue
        if rows[rs]['start']-rows[le-1]['end']>.60:continue
        if (rows[le-1]['end']-rows[ls]['start']+
                rows[re-1]['end']-rows[rs]['start']<.20):continue
        if core._protected_text_change(left,variant):continue
        # A one-frame OCR hallucination can be wholly unrelated to the held
        # glyph (for example 哥 -> f -> 哥). Its pixels, not its text similarity,
        # decide whether it is repaired below.
        if (SequenceMatcher(None,left.casefold(),variant.casefold()).ratio()<.55 and
                rows[end-1]['end']-rows[start]['start']>.08):continue
        # Even a prefix-only reading can survive the cheap temporal pass when
        # its OCR boxes move. Keep it for independent image verification.
        bounds=_bounds(rows[le-1],rows[rs])
        if bounds is None:continue
        found.append({'kind':'substitution','reference':left,'left':le-1,'right':rs,
                      'suspects':list(range(start,end)),'bounds':bounds})
    return found+_blank_targets(rows,runs)


def _similar_mask(a,b):
    if a is None or b is None or a.shape!=b.shape:return False
    union=np.count_nonzero(a|b)
    if union<20:return False
    diff=a^b
    if np.count_nonzero(diff)/union>.045:return False
    # A changed final letter can be under 4% of a long sentence's pixels.
    # The local check stops that real change from being swallowed.
    h,w=diff.shape;tile=np.pad(diff,((0,(-h)%16),(0,(-w)%16)))
    return not np.any(tile.reshape(tile.shape[0]//16,16,
                                   tile.shape[1]//16,16).sum(axis=(1,3))>5)


def _similar_gap_mask(a,b):
    """Allow a few moving-background pixels around a held outlined caption."""
    if _similar_mask(a,b):return True
    if a is None or b is None or a.shape!=b.shape:return False
    diff=a^b;union=np.count_nonzero(a|b)
    if union<100 or np.count_nonzero(diff)/union>.03:return False
    h,w=diff.shape;tile=np.pad(diff,((0,(-h)%16),(0,(-w)%16)))
    counts=tile.reshape(tile.shape[0]//16,16,
                        tile.shape[1]//16,16).sum(axis=(1,3))
    return bool(counts.max()<=12 and np.count_nonzero(counts>5)<=2)


def _needed_frames(container,stream,rows,needed,meta):
    """Seek to sparse suspect windows while retaining each source frame's PTS."""
    from subtitle_ocr import control
    ordered=sorted(needed,key=lambda index:rows[index]['start'])
    windows=[]
    for index in ordered:
        if windows and rows[index]['start']-rows[windows[-1][-1]]['start']<=1.2:
            windows[-1].append(index)
        else:windows.append([index])
    time_base=float(stream.time_base)
    for window in windows:
        first=round((rows[window[0]]['start']+meta['origin'])/time_base)
        last=round((rows[window[-1]]['start']+meta['origin'])/time_base)
        by_pts={round((rows[index]['start']+meta['origin'])/time_base):index
                for index in window}
        container.seek(max(0,first),stream=stream,backward=True)
        for frame in container.decode(stream):
            control.check()
            if frame.pts is None:continue
            if frame.pts>last:break
            index=by_pts.pop(frame.pts,None)
            if index is not None:yield index,frame
        # A seek near the stream tail can miss a truncated final frame. Leave
        # those rows unchanged instead of assigning pixels from a wrong PTS.


def _letters(text):
    """Compare independent OCR words despite uncertain terminal punctuation."""
    import unicodedata
    return ''.join(char.casefold() for char in unicodedata.normalize('NFC',text) if char.isalnum())


def refine(rows,path,meta,roi,pool=None,_pass=0):
    import av
    import subtitle_ocr as core
    from frame_features import text_mask
    from video_crops import FrameCropper
    candidates=targets(rows)
    if not candidates:return 0
    needed={}
    for candidate_index,item in enumerate(candidates):
        indices=([item['left'],*item['suspects'],item['right']]
                 if item['kind']=='substitution' else
                 [*(anchor[0] for anchor in item['anchors']),*item['suspects']])
        item['last']=max(indices)
        for row_index in indices:
            needed.setdefault(rows[row_index]['frame'],[]).append((candidate_index,row_index))
        item['masks']={}
    cropper=FrameCropper(roi);repaired=0;secondary=None
    core.control.emit('phase',phase=f'核验 {len(candidates)} 处短时字幕画面')
    with av.open(str(path)) as container, ExitStack() as cleanup:
        def independent_score(crop, reference, variant):
            nonlocal secondary
            if pool is None or not getattr(pool,'name','').startswith('AppleVision'):
                return None
            languages=getattr(pool,'languages',[])
            if len(languages)!=1 or languages[0]=='auto' or _letters(reference)==_letters(variant):
                return None
            if secondary is None:
                from optional_ocr import OptionalOCR
                secondary=OptionalOCR(pool,'短时字幕独立复核',lambda:core.RapidPool(languages,[],1,device='cpu'))
                cleanup.callback(secondary.close)
            readings=[]
            for scale in (1,2):
                image=core.image_crop(crop,(0,0,1,1),scale)
                result=secondary.recognize(image,
                    dialogue_min_height=getattr(pool,'dialogue_min_height',0),
                    dialogue_max_height=getattr(pool,'dialogue_max_height',0),
                    dialogue_min_mask_density=getattr(pool,'dialogue_min_mask_density',0))
                if result is None:return None
                readings.append(core.read_lines(result))
            if all(score>=.80 and _letters(text)==_letters(reference) for text,score in readings):
                return min(score for _,score in readings)
            return None

        stream=container.streams[meta['stream_index']];stream.codec_context.thread_count=2
        for frame_index,frame in _needed_frames(container,stream,rows,needed,meta):
            crop=cropper.crop(frame)
            mask=text_mask(crop)
            h,w=mask.shape
            for candidate_index,row_index in needed[frame_index]:
                item=candidates[candidate_index]
                bounds=([item['bounds']] if item['kind']=='substitution' else
                        [anchor[2] for anchor in item['anchors']])
                item['masks'][row_index]=[
                    mask[round(y1*h):round(y2*h),round(x1*w):round(x2*w)].copy()
                    for x1,y1,x2,y2 in bounds]
                if row_index!=item['last']:continue
                for i in item['suspects']:
                    if item['kind']=='substitution':
                        # One neighboring frame can have different scenery
                        # behind unchanged text. Matching either observed
                        # anchor still requires the suspect's actual glyphs.
                        candidate_mask=item['masks'].get(i,[None])[0]
                        matching=(_similar_mask(item['masks'].get(item['left'],[None])[0],candidate_mask) or
                                  _similar_mask(item['masks'].get(item['right'],[None])[0],candidate_mask))
                        replacement=item['reference'] if matching else None
                        confidence=min(rows[item['left']]['confidence'],rows[item['right']]['confidence'])
                        if replacement is None:
                            score=independent_score(crop,item['reference'],rows[i]['text'])
                            if score is not None:replacement=item['reference'];confidence=score
                    else:
                        matches=[(text,rows[index]['confidence'])
                                 for anchor_index,(index,text,_) in enumerate(item['anchors'])
                                 if _similar_gap_mask(item['masks'].get(index,[None]*len(bounds))[anchor_index],
                                                      item['masks'].get(i,[None]*len(bounds))[anchor_index])]
                        readings={text for text,_ in matches}
                        replacement=next(iter(readings)) if len(readings)==1 else None
                        confidence=min((score for _,score in matches),default=0)
                        if replacement is None and item.get('bracketed_text'):
                            reference=item['bracketed_text']
                            score=independent_score(crop,reference,rows[i]['text'])
                            if score is not None:replacement=reference;confidence=score
                    if replacement is None:continue
                    row=rows[i]
                    row.setdefault('primary_text',row['text'])
                    row['text']=replacement
                    row['confidence']=confidence
                    row['image_verified']=True
                    row['visual_consensus']=True
                    repaired+=1
                item['masks'].clear()
    # An initially empty stretch can gain a short OCR-backed edge during this
    # pass. Rebuild candidates once so the remaining held frames are checked
    # against the newly established anchors; never fill by inference alone.
    if repaired and _pass==0:
        repaired+=refine(rows,path,meta,roi,pool,_pass=1)
    return repaired
