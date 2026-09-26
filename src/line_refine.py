"""Recheck missing lines in a single decode pass, with bounded OCR work."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor

def targets(rows,roi):
    import subtitle_ocr as core
    groups=[];jobs={}
    for row in rows:
        first=core.key(row['text'].split('\n')[0])
        if groups and groups[-1][0]==first:groups[-1][1].append(row)
        else:groups.append((first,[row]))
    for first,group in groups:
        if not first or len(group)<4 or group[-1]['end']-group[0]['start']>15:continue
        candidates={}
        for row in group:
            for line in sorted(row['ocr']['lines'],key=lambda x:x['box'][1])[1:]:
                text=line['candidates'][0]['text']
                if sum(c.isalpha() for c in text)>=2:candidates.setdefault(core.key(text),[]).append(line)
        for candidate,observations in sorted(candidates.items(),key=lambda item:len(item[1]),reverse=True)[:2]:
            if len(observations)<3:continue
            box=observations[len(observations)//2]['box'];x,y,w,h=box
            tight=(max(0,x-.025),max(0,y-.035),min(1,x+w+.025),min(1,y+h+.035))
            area=(roi[0]+tight[0]*(roi[2]-roi[0]),roi[1]+tight[1]*(roi[3]-roi[1]),roi[0]+tight[2]*(roi[2]-roi[0]),roi[1]+tight[3]*(roi[3]-roi[1]))
            for row in group:
                if candidate in {core.key(s) for s in row['text'].splitlines()}:continue
                if any(abs((line['box'][1]+line['box'][3]/2)-(y+h/2))<max(h,line['box'][3])*.45 for line in row['ocr']['lines']):continue
                jobs.setdefault(row['frame'],(row,[]))[1].append((candidate,box,area))
    return jobs

def refine(rows,path,meta,roi,pool,scale,workers=2):
    import av
    import subtitle_ocr as core
    jobs=targets(rows,roi)
    if not jobs:return 0
    pending=deque();recovered=0;last=max(jobs)
    def recognize(image,items):
        results=[]
        for candidate,box,area in items:
            result=pool.recognize(core.image_crop(image,area,scale));text,confidence=core.read_lines(result)
            if core.key(text)==candidate and confidence>=.8:results.append((box,text,confidence))
        return results
    def accept():
        nonlocal recovered
        row,future=pending.popleft()
        for box,text,confidence in future.result():
            row.setdefault('primary_text',row['text']);row['ocr']=dict(row['ocr'],lines=list(row['ocr']['lines'])+[{'box':box,'candidates':[{'text':text,'confidence':confidence}]}])
            row['text'],row['confidence']=core.read_lines(row['ocr']);row['line_recovered']=True;recovered+=1
    core.control.emit('phase',phase=f'图像复查缺行：{len(jobs)} 帧')
    with av.open(str(path)) as container,ThreadPoolExecutor(max_workers=workers) as executor:
        stream=container.streams[meta['stream_index']];stream.codec_context.thread_count=2
        for index,frame in enumerate(container.decode(stream)):
            core.control.check()
            if index not in jobs:continue
            row,items=jobs[index];pending.append((row,executor.submit(recognize,core.oriented_image(frame),items)))
            if len(pending)>=workers*2:accept()
            if index>=last:break
        while pending:accept()
    return recovered
