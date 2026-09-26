"""Resolve short OCR substitutions only when the actual subtitle glyphs match.

The video is decoded once for a small set of suspect frames. No language model,
dictionary, or guessed text enters the export: the replacement was read by OCR
on both sides of the suspect frame, and the subtitle pixels must agree.
"""
from __future__ import annotations

from contextlib import ExitStack
from collections import Counter
from difflib import SequenceMatcher
import unicodedata

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


def _single_glyph_disagreement(left, right):
    """Locate one OCR glyph substitution in an otherwise long held line."""
    import subtitle_ocr as core
    if (not left or not right or '\n' in left+right or min(len(left),len(right))<12 or
            core._protected_text_change(left,right)):
        return None
    edits=[(tag,a,b,c,d) for tag,a,b,c,d in
           SequenceMatcher(None,left,right,autojunk=False).get_opcodes() if tag!='equal']
    if len(edits)!=1:return None
    tag,a,b,c,d=edits[0]
    if (tag!='replace' or b-a!=1 or d-c!=1 or
            not left[a].isalnum() or not right[c].isalnum()):return None
    return a,b


def _glyph_region_match(first, second, left, disagreement):
    """Compare the changed glyph's actual pixels, not OCR edit distance."""
    from frame_features import text_mask
    boxes=[]
    for row in (first[0],second[0]):
        lines=row.get('ocr',{}).get('lines',[])
        if len(lines)!=1 or not lines[0].get('candidates'):return False
        boxes.append(lines[0]['box'])
    if not all(abs(boxes[0][i]-boxes[1][i])<(.055 if i in (0,2) else .09)
               for i in range(4)):return False
    width=first[1].width;height=first[1].height
    if second[1].size!=first[1].size:return False
    x=min(box[0] for box in boxes);y=min(box[1] for box in boxes)
    w=max(box[0]+box[2] for box in boxes)-x
    bottom=max(box[1]+box[3] for box in boxes)
    def weight(char):
        if unicodedata.combining(char):return 0
        if char.isspace():return .42
        return 1 if unicodedata.east_asian_width(char) in ('W','F') else .62
    total=sum(map(weight,left))
    if total<=0:return False
    a,b=disagreement;before=sum(map(weight,left[:a]));after=sum(map(weight,left[:b]))
    margin=max(1,total/len(left))
    x1=max(0,round((x+w*max(0,(before-margin)/total))*width))
    x2=min(width,round((x+w*min(1,(after+margin)/total))*width))
    y1=max(0,round((y-.015)*height));y2=min(height,round((bottom+.015)*height))
    if x2-x1<12 or y2-y1<8:return False
    masks=[text_mask(image)[y1:y2,x1:x2] for _,image in (first,second)]
    common=np.count_nonzero(masks[0]&masks[1])
    smaller=min(np.count_nonzero(mask) for mask in masks)
    union=np.count_nonzero(masks[0]|masks[1])
    return smaller>=65 and common/smaller>=.985 and common/union>=.85


def refine_recurrent_variant(rows,path,meta,roi,pool):
    """Resolve A/B/A/B OCR readings only after verifying the changed glyph.

    A real subtitle word change can make the same text pattern. The video
    pixels in the disputed character must match before one cue is exported.
    """
    import subtitle_ocr as core
    runs=_runs(rows);repaired=0;last_end=0
    for n in range(len(runs)-3):
        a,b,c,d=runs[n:n+4]
        if a[1]<last_end or not (a[0] and a[0]==c[0] and b[0] and b[0]==d[0] and a[0]!=b[0]):continue
        disagreement=_single_glyph_disagreement(a[0],b[0])
        if disagreement is None:continue
        duration=lambda run:rows[run[2]-1]['end']-rows[run[1]]['start']
        if (duration(a)<.20 or duration(b)>.18 or duration(c)>.18 or
                duration(d)<.24 or rows[d[2]-1]['end']-rows[a[1]]['start']>3.5):continue
        if not all(rows[right[1]]['start']-rows[left[2]-1]['end']<=.08
                   for left,right in ((a,b),(b,c),(c,d))):continue
        if not core._same_caption_geometry(rows[a[1]:a[2]],rows[d[1]:d[2]]):continue
        # Use frames that independently produced the two readings. A changed
        # scene behind an unchanged subtitle is fine; a changed glyph is not.
        ia=max(range(a[1],a[2]),key=lambda i:rows[i]['confidence'])
        ib=max(range(d[1],d[2]),key=lambda i:rows[i]['confidence'])
        images=[]
        for index in (ia,ib):
            core.control.check()
            frame=core.frame_at(path,meta,rows[index]['start'])
            images.append((rows[index],core.image_crop(frame,roi,1)))
        if not _glyph_region_match(images[0],images[1],a[0],disagreement):continue
        # Remove the changing scene behind the *observed* outlined glyphs,
        # then read that real image evidence twice. This recovers a Korean
        # syllable that the same OCR model misreads when clothing changes.
        # Never form a word from a dictionary or accept text absent from OCR.
        from PIL import Image
        from frame_features import text_mask
        samples=list(images)
        for run,chosen in ((a,ia),(d,ib)):
            alternatives=sorted((index for index in range(run[1],run[2]) if index!=chosen),
                                key=lambda index:rows[index]['confidence'],reverse=True)
            if alternatives:
                distant=next((index for index in alternatives
                              if abs(rows[index]['start']-rows[chosen]['start'])>=.12),
                             alternatives[0])
                frame=core.frame_at(path,meta,rows[distant]['start'])
                samples.append((rows[distant],core.image_crop(frame,roi,1)))
        masked=[]
        for row,image in samples:
            binary=np.where(text_mask(image),255,0).astype(np.uint8)
            clean=Image.fromarray(binary,'L').convert('RGB')
            clean.info['ellapuede_dialogue_crop']=True
            text,score=core.read_lines(pool.recognize(clean))
            masked.append((core.key(text),score))
        masked_votes=Counter(text for text,score in masked
                             if text in (a[0],b[0]) and score>=.80)
        winner,count=masked_votes.most_common(1)[0] if masked_votes else ('',0)
        if count>=2 and count>masked_votes.get(b[0] if winner==a[0] else a[0],0):
            canonical=winner
        else:
            # A second rasterization can still select between the two words
            # actually seen in the source frames; ties keep the longer run.
            scores={a[0]:[],b[0]:[]}
            for row,image in images:
                text,score=core.read_lines(pool.recognize(image))
                if core.key(text) in scores:scores[core.key(text)].append(score)
            first_score=max(scores[a[0]],default=0)
            second_score=max(scores[b[0]],default=0)
            canonical=a[0] if first_score>second_score+.02 else b[0]
        end=d[2]
        visible=lambda value:''.join(core.key(value).split()).casefold()
        while end<len(rows) and visible(rows[end]['text'])==visible(b[0]):
            if (rows[end]['start']-rows[end-1]['end']>.08 or
                    rows[end]['end']-rows[a[1]]['start']>3.5 or
                    not core._same_caption_geometry(rows[d[1]:d[2]],rows[end:end+1])):
                break
            end+=1
        for row in rows[a[1]:end]:
            if core.key(row['text'])!=canonical:
                row.setdefault('primary_text',row['text'])
                row['text']=canonical;row['image_verified']=True
                row['visual_consensus']=True;row['recurrent_variant']=True
                repaired+=1
        last_end=end
    return repaired


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
