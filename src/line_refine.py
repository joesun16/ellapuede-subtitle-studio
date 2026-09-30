"""Recheck missing lines in a single decode pass, with bounded OCR work."""
from collections import deque,OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import BoundedSemaphore

def confidence_tracks(rows):
    """Track already-read individual lines through confidence dips, not blanks."""
    import subtitle_ocr as core
    tracks=[];active=[]
    for index,row in enumerate(rows):
        current=[];used=set()
        for line in row['ocr']['lines']:
            candidates=line.get('candidates') or []
            if not candidates or candidates[0].get('confidence',0)<.29:continue
            value=core.key(candidates[0].get('text',''))
            if not any(c.isalnum() for c in value):continue
            x,y,w,h=line['box'];match=None
            for track in active:
                if id(track) in used or track['text']!=value:continue
                last,previous=track['items'][-1];px,py,pw,ph=previous['box']
                if (row['start']-rows[last]['end']<=.05 and
                    row['end']-rows[track['items'][0][0]]['start']<=15 and
                    abs(x+w/2-px-pw/2)<=.035 and abs(y+h/2-py-ph/2)<=.055 and
                    .7<=h/max(ph,1e-9)<=1.4):match=track;break
            if match is None:
                match={'text':value,'items':[]};tracks.append(match)
            match['items'].append((index,line));current.append(match);used.add(id(match))
        active=current
    return [track for track in tracks if len(track['items'])>=5 and
            sum(line['candidates'][0]['confidence']>=.5 for _,line in track['items'])>=3 and
            any(track['text'] not in core.key(rows[i]['text']) for i,_ in track['items'])]


def restore_low_confidence_lines(rows,path,meta,roi):
    """Every restored line must match visible glyphs on its own source frame.

    Unlike sentence voting this also works when just the upper or lower line
    drops below the engine threshold. The low-score OCR must already read the
    same string; true blanks, changed words, marks and digits are not filled.
    """
    import av
    import subtitle_ocr as core
    from frame_features import text_mask
    from video_crops import requested_frames,FrameCropper,configure_decoder
    from visual_consensus import _similar_gap_mask
    tracks=confidence_tracks(rows)
    if not tracks:return 0
    # Earlier full-caption checks can keep only one line. Adding an observed
    # missing line is safe only if EVERY existing word remains in the proposal;
    # stale raw boxes must never overwrite a previous image-backed correction.
    eligible=set()
    for i,row in enumerate(rows):
        proposal={'lines':[dict(line,candidates=[dict(line['candidates'][0],confidence=max(.5,line['candidates'][0].get('confidence',0)))])
                           for line in row['ocr']['lines'] if line.get('candidates')]}
        if core.key(row['text']) in core.key(core.read_lines(proposal)[0]):eligible.add(i)
    needed={};recovered=0
    for track in tracks:
        anchors=[i for i,line in track['items'] if line['candidates'][0]['confidence']>=.5]
        suspects=[(i,line) for i,line in track['items'] if i in eligible and track['text'] not in core.key(rows[i]['text'])]
        if not suspects:continue
        references={i:sorted(anchors,key=lambda a:abs(a-i))[:2] for i,_ in suspects}
        boxes=[line['box'] for _,line in track['items']]
        track.update(suspects=suspects,references=references,masks={},bounds=(
            max(0,min(b[0] for b in boxes)-.005),max(0,min(b[1] for b in boxes)-.01),
            min(1,max(b[0]+b[2] for b in boxes)+.005),min(1,max(b[1]+b[3] for b in boxes)+.01)))
        indices=set(references)|{a for values in references.values() for a in values}
        track['last']=max(indices)
        for i in indices:needed.setdefault(i,[]).append(track)
    if not needed:return 0
    cropper=FrameCropper(roi)
    with av.open(str(path)) as container:
        stream=configure_decoder(container.streams[meta['stream_index']])
        for i,frame in requested_frames(container,stream,rows,needed,meta):
            mask=text_mask(cropper.crop(frame));height,width=mask.shape
            for track in needed[i]:
                a,b,c,d=track['bounds']
                track['masks'][i]=mask[round(b*height):round(d*height),round(a*width):round(c*width)].copy()
                if i!=track['last']:continue
                for index,line in track['suspects']:
                    if not any(_similar_gap_mask(track['masks'][index],track['masks'][anchor])
                               for anchor in track['references'][index]):continue
                    row=rows[index]
                    candidates=[dict(line['candidates'][0],confidence=max(.5,line['candidates'][0]['confidence'])),*line['candidates'][1:]]
                    proposal=dict(row['ocr'],lines=[dict(item,candidates=candidates) if item is line else item for item in row['ocr']['lines']])
                    text,confidence=core.read_lines(proposal)
                    if core.key(row['text']) not in core.key(text):continue
                    line['candidates']=candidates;row.setdefault('primary_text',row['text'])
                    row['text'],row['confidence']=text,confidence
                    row['line_recovered']=True;row['image_verified']=True;recovered+=1
                track['masks'].clear()
    return recovered

def targets(rows,roi):
    import subtitle_ocr as core
    groups=[];jobs={}
    for row in rows:
        observed={core.key(line) for line in row['text'].splitlines() if core.key(line)}
        # Missing UPPER lines used to change the first-line key and break this
        # group, making those frames impossible to recover. Any shared visible
        # line connects adjacent frames; a genuine blank still breaks the track.
        if (groups and observed and groups[-1][0]&observed and
                row['start']-groups[-1][1][-1]['end']<=.05 and
                row['end']-groups[-1][1][0]['start']<=15):
            groups[-1][1].append(row);groups[-1]=(observed,groups[-1][1])
        else:groups.append((observed,[row]))
    for observed,group in groups:
        if not observed or len(group)<4:continue
        candidates={}
        for row in group:
            for line in row['ocr']['lines']:
                if not line.get('candidates') or line['candidates'][0].get('confidence',0)<.5:continue
                text=line['candidates'][0]['text']
                if sum(c.isalpha() for c in text)>=2:candidates.setdefault(core.key(text),[]).append(line)
        for candidate,observations in sorted(candidates.items(),key=lambda item:len(item[1]),reverse=True):
            if len(observations)<3:continue
            box=observations[len(observations)//2]['box'];x,y,w,h=box
            tight=(max(0,x-.025),max(0,y-.035),min(1,x+w+.025),min(1,y+h+.035))
            # Keep the entire selected width: a real prefix change must not be
            # hidden by cropping to a neighboring line's narrower text box.
            area=(roi[0],roi[1]+tight[1]*(roi[3]-roi[1]),roi[2],roi[1]+tight[3]*(roi[3]-roi[1]))
            for row in group:
                if core.key(row['text'])!=core.key(core.read_lines(row['ocr'])[0]):continue
                if candidate in {core.key(s) for s in row['text'].splitlines()}:continue
                if any(line.get('candidates') and line['candidates'][0].get('confidence',0)>=.5 and
                       abs((line['box'][1]+line['box'][3]/2)-(y+h/2))<max(h,line['box'][3])*.45
                       for line in row['ocr']['lines']):continue
                jobs.setdefault(row['frame'],(row,[]))[1].append((candidate,box,area))
    return jobs

def refine(rows,path,meta,roi,pool,scale,workers=2):
    import av
    import subtitle_ocr as core
    from video_crops import requested_frames,FrameCropper,configure_decoder
    recovered=restore_low_confidence_lines(rows,path,meta,roi)
    jobs=targets(rows,roi)
    if not jobs:return recovered
    pending=deque();croppers=OrderedDict();secondary=None;slots=BoundedSemaphore(1)
    if getattr(pool,'name','').startswith('AppleVision') and getattr(pool,'languages',[])==['th-TH']:
        from optional_ocr import OptionalOCR
        secondary=OptionalOCR(pool,'缺行独立复核',lambda:core.RapidPool(pool.languages,[],1,device='cpu'))
    def recognize(items):
        results=[]
        for candidate,box,image in items:
            result=pool.recognize(core.image_crop(image,(0,0,1,1),scale));text,confidence=core.read_lines(result)
            accepted=core.key(text)==candidate and confidence>=.8
            # Vision's Thai route reports 0.5 even for correct text. Two sizes
            # of THIS missing line must independently read the observed string;
            # do not copy a neighboring line merely on temporal similarity.
            if not accepted and core.key(text)==candidate and confidence>=.5 and secondary is not None:
                other=core.image_crop(image,(0,0,1,1),1 if scale>1 else 2)
                value,score=core.read_lines(pool.recognize(other))
                accepted=core.key(value)==candidate and score>=.5
            if not accepted and secondary is not None:
                # Only unresolved missing lines pay for a second model. It
                # must read this same observed line twice on THIS frame.
                readings=[]
                with slots:
                    for factor in (1,2):
                        result=secondary.recognize(core.image_crop(image,(0,0,1,1),factor))
                        if result is None:break
                        value,score=core.read_lines(result)
                        if core.key(value)!=candidate or score<.85:break
                        readings.append((value,score))
                if len(readings)==2:
                    text=readings[0][0];confidence=min(score for _,score in readings);accepted=True
            if accepted:results.append((box,text,confidence))
        return results
    def accept():
        nonlocal recovered
        row,future=pending.popleft()
        for box,text,confidence in future.result():
            lines=[line for line in row['ocr']['lines'] if not (
                line.get('candidates') and line['candidates'][0].get('confidence',0)<.5 and
                abs(line['box'][1]+line['box'][3]/2-box[1]-box[3]/2)<max(line['box'][3],box[3])*.45)]
            row.setdefault('primary_text',row['text']);row['ocr']=dict(row['ocr'],lines=lines+[{'box':box,'candidates':[{'text':text,'confidence':confidence}]}])
            row['text'],row['confidence']=core.read_lines(row['ocr']);row['line_recovered']=True;recovered+=1
    core.control.emit('phase',phase=f'图像复查缺行：{len(jobs)} 帧')
    with ExitStack() as cleanup, av.open(str(path)) as container,ThreadPoolExecutor(max_workers=workers) as executor:
        if secondary is not None:cleanup.callback(secondary.close)
        stream=configure_decoder(container.streams[meta['stream_index']])
        for index,frame in requested_frames(container,stream,rows,jobs,meta):
            row,items=jobs[index];inputs=[]
            for candidate,box,area in items:
                if area not in croppers:croppers[area]=FrameCropper(area)
                croppers.move_to_end(area)
                while len(croppers)>16:croppers.popitem(last=False)
                inputs.append((candidate,box,croppers[area].crop(frame)))
            pending.append((row,executor.submit(recognize,inputs)))
            if len(pending)>=workers*2:accept()
        while pending:accept()
    return recovered
