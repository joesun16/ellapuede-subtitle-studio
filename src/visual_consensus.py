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
    """Return image-verifiable islands bracketed by the same observed caption."""
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
        if _protected_for_visual_check(left,variant):continue
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
    # Several different one-frame OCR readings can appear inside one held
    # caption (A-B-C-A). A single-variant A-B-A detector cannot see that
    # island, but every suspect can still be checked against the actual glyphs.
    for n in range(len(runs)-3):
        left,ls,le=runs[n]
        if not left:continue
        for right_index in range(n+3,min(len(runs),n+5)):
            right,rs,re=runs[right_index]
            middle=runs[n+1:right_index]
            if (not right or not all(value and not _protected_for_visual_check(left,value)
                                      for value,_,_ in middle)):
                break
            if rows[rs]['start']-rows[le-1]['end']>.65:break
            if right!=left:continue
            suspects=[i for _,start,end in middle for i in range(start,end)]
            if (rows[suspects[-1]]['end']-rows[suspects[0]]['start']>.45 or
                    rows[le-1]['end']-rows[ls]['start']+
                    rows[re-1]['end']-rows[rs]['start']<.20 or
                    not core._same_caption_geometry(rows[ls:le],rows[rs:re])):
                break
            if any(SequenceMatcher(None,left.casefold(),value.casefold()).ratio()<.55
                   and rows[end-1]['end']-rows[start]['start']>.08
                   for value,start,end in middle):break
            bounds=_bounds(rows[le-1],rows[rs])
            if bounds is not None:
                found.append({'kind':'substitution','reference':left,'left':le-1,
                              'right':rs,'suspects':suspects,'bounds':bounds})
            break
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


def _held_line(row):
    """A provisional reading, including a low-confidence line already seen by OCR.

    The provisional reading is never exported on its own. It only connects a
    visually verified held caption across an OCR confidence dip.
    """
    import subtitle_ocr as core
    lines=[line for line in row.get('ocr',{}).get('lines',[])
           if line.get('candidates') and
           line['candidates'][0].get('confidence',0)>=.29 and
           core.normalize(line['candidates'][0].get('text',''))]
    if len(lines)!=1:return None
    text=core.normalize(lines[0]['candidates'][0]['text'])
    if not any(char.isalnum() for char in text):return None
    return core.key(text),lines[0]['box']


def _held_variant_groups(rows,include_high_confidence=False):
    """Find repeated OCR flips in one line, without deciding from text alone."""
    import subtitle_ocr as core
    readings=[_held_line(row) for row in rows]
    groups=[];i=0
    while i<len(rows):
        first=readings[i]
        if first is None:
            i+=1;continue
        start=i;indices=[i];i+=1
        while i<len(rows) and readings[i] is not None:
            text,box=readings[i];previous=readings[indices[-1]]
            reference,anchor_box=first
            cx=lambda b:b[0]+b[2]/2
            cy=lambda b:b[1]+b[3]/2
            if (rows[i]['start']-rows[indices[-1]]['end']>.05 or
                    rows[i]['end']-rows[start]['start']>2.5 or
                    core._protected_text_change(reference,text) or
                    core._protected_text_change(previous[0],text) or
                    min(SequenceMatcher(None,reference.casefold(),text.casefold()).ratio(),
                        SequenceMatcher(None,previous[0].casefold(),text.casefold()).ratio())<.78 or
                    abs(cx(box)-cx(anchor_box))>.075 or abs(cy(box)-cy(anchor_box))>.085 or
                    not .65<=box[3]/max(anchor_box[3],1e-9)<=1.55):
                break
            indices.append(i);i+=1
        values=[readings[index][0] for index in indices]
        switches=sum(a!=b for a,b in zip(values,values[1:]))
        if (len(indices)>=6 and switches>=3 and len(set(values))>=2 and
                rows[indices[-1]]['end']-rows[start]['start']>=.20 and
                (include_high_confidence or
                 sum(rows[index]['confidence']<.5 for index in indices)>=2) and
                sum(rows[index]['confidence']>=.5 for index in indices)>=3):
            runs=[]
            for index in indices:
                if runs and readings[index][0]==readings[runs[-1][-1]][0]:runs[-1].append(index)
                else:runs.append([index])
            if len(runs)<=24:groups.append((indices,runs,readings))
        if i==start:i+=1
    return groups


def refine_low_confidence_holds(rows,path,meta,roi):
    """Restore a repeatedly observed line while its OCR score flickers.

    A single accepted OCR frame alone is not evidence of the whole duration:
    the same provisional text must recur on at least five contiguous source
    frames, and its actual glyph mask must agree across the interval.
    """
    import av
    import subtitle_ocr as core
    from frame_features import text_mask
    from video_crops import FrameCropper
    readings=[_held_line(row) for row in rows]
    groups=[];i=0
    while i<len(rows):
        first=readings[i]
        if first is None:
            i+=1;continue
        indices=[i];i+=1
        while i<len(rows) and readings[i] is not None:
            text,box=readings[i];reference,base=first
            if (text!=reference or rows[i]['start']-rows[indices[-1]]['end']>.05 or
                    abs(box[0]+box[2]/2-base[0]-base[2]/2)>.045 or
                    abs(box[1]+box[3]/2-base[1]-base[3]/2)>.065):
                break
            indices.append(i);i+=1
        missing=[index for index in indices if not rows[index]['text']]
        if (len(indices)>=5 and len(missing)>=3 and
                rows[indices[-1]]['end']-rows[indices[0]]['start']>=.15 and
                all(not rows[index]['text'] or core.key(rows[index]['text'])==first[0]
                    for index in indices) and
                any(core.key(rows[index]['text'])==first[0] for index in indices)):
            groups.append((indices,first[0]))
    if not groups:return 0
    cropper=FrameCropper(roi);repaired=0
    with av.open(str(path)) as container:
        stream=container.streams[meta['stream_index']];stream.codec_context.thread_count=2
        for indices,reading in groups:
            core.control.check()
            accepted=[index for index in indices if core.key(rows[index]['text'])==reading]
            samples=sorted({indices[0],indices[len(indices)//2],indices[-1],
                            accepted[len(accepted)//2]})
            boxes=[readings[index][1] for index in indices]
            bounds=(max(0,min(box[0] for box in boxes)-.008),
                    max(0,min(box[1] for box in boxes)-.015),
                    min(1,max(box[0]+box[2] for box in boxes)+.008),
                    min(1,max(box[1]+box[3] for box in boxes)+.015))
            masks={}
            for index,frame in _needed_frames(container,stream,rows,samples,meta):
                mask=text_mask(cropper.crop(frame));h,w=mask.shape
                x1,y1,x2,y2=bounds
                masks[index]=mask[round(y1*h):round(y2*h),
                                  round(x1*w):round(x2*w)].copy()
            if len(masks)!=len(samples) or not all(_similar_gap_mask(masks[a],masks[b])
                                                    for a,b in zip(samples,samples[1:])):
                continue
            for index in indices:
                if rows[index]['text']:continue
                rows[index]['text']=reading
                rows[index]['confidence']=.5
                rows[index]['image_verified']=True
                rows[index]['held_caption_verified']=True
                repaired+=1
    return repaired


def refine_sparse_visible_holds(rows,path,meta,roi,skip_indices=()):
    """Extend a sparse OCR hit only across visibly identical subtitle glyphs.

    Some short Chinese or Thai captions are displayed for many frames while a
    recognizer returns text in only one or two. Source-frame masks establish
    the actual start/end; nearby dialogue or scene text cannot cross a changed
    glyph or a blank visual boundary.
    """
    import av
    import subtitle_ocr as core
    from frame_features import text_mask
    from video_crops import FrameCropper
    excluded=set(skip_indices);runs=_runs(rows);candidates=[]
    for value,start,end in runs:
        if (not value or start in excluded or end-start>4 or
                rows[end-1]['end']-rows[start]['start']>.18):continue
        anchor=next((i for i in range(start,end) if rows[i].get('confidence',0)>=.5 and
                     _tight_bounds(rows[i]) is not None),None)
        if anchor is None:continue
        bounds=_tight_bounds(rows[anchor])
        left=start
        while (left>0 and rows[start]['start']-rows[left-1]['start']<=1.5 and
               (not rows[left-1]['text'] or core.key(rows[left-1]['text'])==value) and
               left-1 not in excluded):
            left-=1
        right=end
        while (right<len(rows) and rows[right]['start']-rows[end-1]['end']<=1.5 and
               (not rows[right]['text'] or core.key(rows[right]['text'])==value) and
               right not in excluded):
            right+=1
        if right-left<5:continue
        candidates.append((value,start,end,anchor,left,right,bounds))
    if not candidates:return 0
    cropper=FrameCropper(roi);repaired=0
    core.control.emit('phase',phase=f'核验 {len(candidates)} 处持续字幕字形')
    core.control.emit('verify_progress',done=0,total=len(candidates),base=.96,span=.02)
    with av.open(str(path)) as container:
        stream=container.streams[meta['stream_index']];stream.codec_context.thread_count=2
        for candidate_number,(value,start,end,anchor,left,right,bounds) in enumerate(candidates,1):
            core.control.check()
            core.control.emit('verify_progress',done=candidate_number-1,total=len(candidates),
                              base=.96,span=.02)
            wanted=list(range(left,right));masks={}
            for index,frame in _needed_frames(container,stream,rows,wanted,meta):
                mask=text_mask(cropper.crop(frame));h,w=mask.shape
                x1,y1,x2,y2=bounds
                masks[index]=mask[round(y1*h):round(y2*h),
                                  round(x1*w):round(x2*w)].copy()
            reference=masks.get(anchor)
            if reference is None or np.count_nonzero(reference)<65:continue
            visual_left=start
            while visual_left>left and _similar_gap_mask(reference,masks.get(visual_left-1)):
                visual_left-=1
            visual_right=end
            while visual_right<right and _similar_gap_mask(reference,masks.get(visual_right)):
                visual_right+=1
            if visual_right-visual_left<5:continue
            for index in range(visual_left,visual_right):
                if rows[index]['text']:continue
                rows[index]['text']=rows[anchor]['text']
                rows[index]['confidence']=max(.5,rows[anchor]['confidence'])
                rows[index]['image_verified']=True
                rows[index]['held_caption_verified']=True
                repaired+=1
    core.control.emit('verify_progress',done=len(candidates),total=len(candidates),
                      base=.96,span=.02)
    return repaired


def refine_held_variants(rows,path,meta,roi,pool):
    """Coalesce a held line only after checking real pixels and repeated OCR.

    A true word, number, or subtitle boundary remains separate when its glyph
    mask changes. OCR correction only chooses among strings already observed
    in this same span, and must agree on at least two distinct source frames.
    """
    from video_crops import FrameCropper
    import subtitle_ocr as core
    import av
    from frame_features import text_mask
    groups=_held_variant_groups(rows,
        include_high_confidence=getattr(pool,'name','').startswith('RapidOCR'))
    if not groups:return 0
    cropper=FrameCropper(roi);repaired=0
    core.control.emit('phase',phase=f'核验 {len(groups)} 处连续字幕画面')
    with av.open(str(path)) as container, ExitStack() as cleanup:
        stream=container.streams[meta['stream_index']];stream.codec_context.thread_count=2
        secondary=None
        for indices,runs,readings in groups:
            core.control.check()
            # Every changed reading gets a representative frame. This rules
            # out a real short word change hiding between two long captions.
            representatives=[run[len(run)//2] for run in runs]
            xs=[readings[index][1][0] for index in indices]
            ys=[readings[index][1][1] for index in indices]
            rights=[readings[index][1][0]+readings[index][1][2] for index in indices]
            bottoms=[readings[index][1][1]+readings[index][1][3] for index in indices]
            bounds=(max(0,min(xs)-.008),max(0,min(ys)-.015),
                    min(1,max(rights)+.008),min(1,max(bottoms)+.015))
            masks={};crops={}
            for index,frame in _needed_frames(container,stream,rows,representatives,meta):
                crop=cropper.crop(frame);mask=text_mask(crop);h,w=mask.shape
                x1,y1,x2,y2=bounds
                masks[index]=mask[round(y1*h):round(y2*h),
                                  round(x1*w):round(x2*w)].copy()
                crops[index]=crop
            if len(masks)!=len(representatives):continue
            if not all(_similar_gap_mask(masks[a],masks[b])
                       for a,b in zip(representatives,representatives[1:])):
                continue
            observed=({readings[index][0] for index in indices} |
                      {core.key(rows[index]['text']) for index in indices if rows[index]['text']})
            eligible=[index for index in indices if rows[index]['confidence']>=.5]
            # Spread reads across the held interval instead of reading three
            # nearly identical adjacent frames.
            chosen=[]
            for part in (.2,.5,.8):
                target=rows[indices[0]]['start']+part*(rows[indices[-1]]['end']-rows[indices[0]]['start'])
                index=min(eligible,key=lambda candidate:abs(rows[candidate]['start']-target))
                if index not in chosen:chosen.append(index)
            votes=Counter();primary_readings={}
            for index in chosen:
                if index not in crops:
                    for found,frame in _needed_frames(container,stream,rows,[index],meta):
                        crops[found]=cropper.crop(frame)
                crop=crops.get(index)
                if crop is None:continue
                result=pool.recognize(core.image_crop(crop,(0,0,1,1),2),correction=True)
                text,confidence=core.read_lines(result)
                if confidence>=.8 and core.key(text) in observed:
                    votes[core.key(text)]+=1;primary_readings[index]=core.key(text)
            canonical,count=votes.most_common(1)[0] if votes else ('',0)
            # A second recognizer is useful only when the primary is visibly
            # inconsistent on these same pixels. Run it on three suspect
            # frames, never over the whole episode or as a blind replacement.
            if (len(set(primary_readings.values()))>1 and len(chosen)>=3 and
                    getattr(pool,'name','').startswith('AppleVision') and
                    len(getattr(pool,'languages',[]))==1 and pool.languages[0]!='auto'):
                if secondary is None:
                    from optional_ocr import OptionalOCR
                    secondary=OptionalOCR(pool,'连续字幕独立复核',
                        lambda:core.RapidPool(pool.languages,[],1,device='cpu'))
                    cleanup.callback(secondary.close)
                alternate=Counter()
                for index in chosen:
                    crop=crops.get(index)
                    if crop is None:continue
                    result=secondary.recognize(core.image_crop(crop,(0,0,1,1),2))
                    if result is None:break
                    text,confidence=core.read_lines(result)
                    if confidence>=.85 and core.key(text) in observed:
                        alternate[core.key(text)]+=1
                if alternate:
                    independent,independent_count=alternate.most_common(1)[0]
                    if independent_count==len(chosen):
                        canonical,count=independent,independent_count
            if count<2:continue
            spelling=Counter(readings[index][0] for index in indices)
            if canonical not in spelling:continue
            for index in indices:
                if core.key(rows[index]['text'])==canonical:continue
                rows[index].setdefault('primary_text',rows[index]['text'])
                rows[index]['text']=canonical
                rows[index]['confidence']=max(rows[index]['confidence'],.5)
                rows[index]['image_verified']=True
                rows[index]['held_caption_verified']=True
                repaired+=1
    return repaired


def refine_short_multiline_openings(rows,path,meta,roi):
    """Repair a brief OCR slip in one line of a two-line held caption.

    The longer observed reading only becomes the replacement if the disputed
    glyph itself has the same pixels before and after the OCR text switch.
    This leaves genuine short on-screen word changes as separate subtitles.
    """
    import av
    import subtitle_ocr as core
    from video_crops import FrameCropper
    runs=_runs(rows);candidates=[]
    def observed(row):
        lines=[line for line in row.get('ocr',{}).get('lines',[])
               if line.get('candidates') and line['candidates'][0].get('confidence',0)>=.5]
        if len(lines)!=2:return None
        lines.sort(key=lambda line:line['box'][1]+line['box'][3]/2)
        values=[core.normalize(line['candidates'][0]['text']) for line in lines]
        if core.key('\n'.join(values))!=core.key(row['text']):return None
        return values,lines
    for n,(reading,start,end) in enumerate(runs):
        if (not reading or end-start<3 or
                not .08<=rows[end-1]['end']-rows[start]['start']<=.30):continue
        first=observed(rows[start])
        if first is None:continue
        first_values,first_lines=first
        later={};limit=rows[end-1]['end']+2.0
        for index in range(end,len(rows)):
            row=rows[index]
            if row['start']>limit or row['start']-rows[index-1]['end']>.06 or not row['text']:
                break
            item=observed(row)
            if item is None:continue
            values,lines=item
            changed=[part for part in (0,1) if values[part]!=first_values[part]]
            if len(changed)!=1:continue
            part=changed[0]
            if (_single_glyph_disagreement(first_values[part],values[part]) is None or
                    values[1-part]!=first_values[1-part]):continue
            entry=later.setdefault(tuple(values),[]);entry.append(index)
        if not later:continue
        replacement,indices=max(later.items(),key=lambda item:len(item[1]))
        if len(indices)<max(8,(end-start)*2):continue
        part=next(part for part in (0,1) if replacement[part]!=first_values[part])
        disagreement=_single_glyph_disagreement(first_values[part],replacement[part])
        if disagreement is None:continue
        candidates.append((start,end,indices[len(indices)//2],part,first_values[part],
                           '\n'.join(replacement),disagreement))
    if not candidates:return 0
    cropper=FrameCropper(roi);repaired=0
    with av.open(str(path)) as container:
        stream=container.streams[meta['stream_index']];stream.codec_context.thread_count=2
        for start,end,reference,part,old_text,new_text,disagreement in candidates:
            core.control.check()
            source=start+(end-start)//2
            images={index:cropper.crop(frame) for index,frame in
                    _needed_frames(container,stream,rows,[source,reference],meta)}
            if len(images)!=2:continue
            before=observed(rows[source]);after=observed(rows[reference])
            if before is None or after is None:continue
            pairs=[]
            for index,item in ((source,before),(reference,after)):
                line=item[1][part]
                pairs.append(({'ocr':{'lines':[line]}},images[index]))
            if not _glyph_region_match(pairs[0],pairs[1],old_text,disagreement):continue
            for index in range(start,end):
                rows[index].setdefault('primary_text',rows[index]['text'])
                rows[index]['text']=new_text
                rows[index]['confidence']=max(.5,rows[index]['confidence'])
                rows[index]['image_verified']=True
                repaired+=1
    return repaired


def refine_combining_mark_variants(rows,path,meta,roi):
    """Join a held caption split solely by an OCR combining-mark omission.

    Thai and other combining-script diacritics can disappear from OCR when a
    scene cuts behind unchanged subtitles. Both sides must contain the same
    source glyphs in the disputed character region; a real mark change stays
    split. The chosen spelling was observed on the source frames, never made
    up from a language model.
    """
    import av
    import subtitle_ocr as core
    from video_crops import FrameCropper

    runs=_runs(rows);candidates=[]
    for left,right in zip(runs,runs[1:]):
        first,start,middle=left;second,other,end=right
        if (not first or not second or other!=middle or
                middle-start<3 or end-other<8 or
                not .08<=rows[middle-1]['end']-rows[start]['start']<=.30 or
                rows[end-1]['end']-rows[start]['start']>3.0 or
                rows[other]['start']-rows[middle-1]['end']>.06 or
                not core._same_caption_geometry(rows[start:middle],rows[other:end])):
            continue
        disagreement=_single_glyph_disagreement(first,second)
        if disagreement is None or len(first)==len(second):continue
        edits=[part for part in SequenceMatcher(None,first,second,autojunk=False).get_opcodes()
               if part[0]!='equal']
        if len(edits)!=1 or edits[0][0] not in ('insert','delete'):continue
        if (len(first.splitlines())!=1 or len(second.splitlines())!=1):continue
        candidates.append((start,middle,other,end,first,second,disagreement))
    if not candidates:return 0
    cropper=FrameCropper(roi);repaired=0
    with av.open(str(path)) as container:
        stream=container.streams[meta['stream_index']];stream.codec_context.thread_count=2
        for start,middle,other,end,first,second,disagreement in candidates:
            core.control.check()
            anchors=(start+(middle-start)//2,
                     other+(end-other)//2,end-1)
            images={index:cropper.crop(frame) for index,frame in
                    _needed_frames(container,stream,rows,anchors,meta)}
            if len(images)!=len(anchors):continue
            pairs=[]
            for index in anchors:
                lines=[line for line in rows[index].get('ocr',{}).get('lines',[])
                       if line.get('candidates')]
                if len(lines)!=1:break
                pairs.append(({'ocr':{'lines':lines}},images[index]))
            if len(pairs)!=3 or not all(
                    _glyph_region_match(pairs[0],pair,first,disagreement)
                    for pair in pairs[1:]):continue
            # A missing combining mark is a common OCR omission. This merely
            # selects one of two observed readings after confirming identical
            # physical glyphs; it is not a claim of character-level certainty.
            spelling=first if len(first)>len(second) else second
            for index in range(start,end):
                if core.key(rows[index]['text'])==spelling:continue
                rows[index].setdefault('primary_text',rows[index]['text'])
                rows[index]['text']=spelling
                rows[index]['confidence']=max(.5,rows[index]['confidence'])
                rows[index]['image_verified']=True
                repaired+=1
    return repaired


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


def _protected_for_visual_check(left,right):
    """A punctuation OCR slip may be checked against pixels, never text alone."""
    import subtitle_ocr as core
    return core._protected_text_change(left,right) and _letters(left)!=_letters(right)


def _single_glyph_disagreement(left, right):
    """Locate one OCR glyph substitution or omitted combining mark."""
    import subtitle_ocr as core
    if (not left or not right or '\n' in left+right or min(len(left),len(right))<12 or
            core._protected_text_change(left,right)):
        return None
    edits=[(tag,a,b,c,d) for tag,a,b,c,d in
           SequenceMatcher(None,left,right,autojunk=False).get_opcodes() if tag!='equal']
    if len(edits)!=1:return None
    tag,a,b,c,d=edits[0]
    replacement=(tag=='replace' and b-a==1 and d-c==1 and
                 left[a].isalnum() and right[c].isalnum())
    combining_slip=(tag=='delete' and b-a==1 and unicodedata.combining(left[a])) or\
                   (tag=='insert' and d-c==1 and unicodedata.combining(right[c]))
    if not (replacement or combining_slip):return None
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
        item['suspect_crops']={}
    cropper=FrameCropper(roi);repaired=0;secondary=None;completed=0
    core.control.emit('phase',phase=f'核验 {len(candidates)} 处短时字幕画面')
    core.control.emit('verify_progress',done=0,total=len(candidates),base=.90,span=.06)
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
                if row_index in item['suspects']:
                    item['suspect_crops'][row_index]=crop
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
                            score=independent_score(item['suspect_crops'][i],item['reference'],rows[i]['text'])
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
                            score=independent_score(item['suspect_crops'][i],reference,rows[i]['text'])
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
                item['suspect_crops'].clear()
                completed+=1
                if completed%max(1,len(candidates)//20)==0 or completed==len(candidates):
                    core.control.emit('verify_progress',done=completed,total=len(candidates),
                                      base=.90,span=.06)
    # An initially empty stretch can gain a short OCR-backed edge during this
    # pass. Rebuild candidates once so the remaining held frames are checked
    # against the newly established anchors; never fill by inference alone.
    if repaired and _pass==0:
        repaired+=refine(rows,path,meta,roi,pool,_pass=1)
    return repaired
