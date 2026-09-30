"""Resolve OCR whitespace variation only when the visible glyph layout agrees."""
from collections import Counter
from itertools import groupby
import numpy as np
from frame_features import text_mask,changed


def same_layout(first,second,boxes):
    if first.shape!=second.shape or not boxes:return False
    h,w=first.shape
    x1=max(0,int(min(b[0] for b in boxes)*w)-2);x2=min(w,int(max(b[0]+b[2] for b in boxes)*w)+3)
    y1=max(0,int(min(b[1] for b in boxes)*h)-2);y2=min(h,int(max(b[1]+b[3] for b in boxes)*h)+3)
    a=first[y1:y2,x1:x2];b=second[y1:y2,x1:x2]
    return min(np.count_nonzero(a),np.count_nonzero(b))>=40 and not changed(a,b)


def refine(rows,path,meta,roi):
    import av
    import subtitle_ocr as core
    from video_crops import requested_frames,configure_decoder,FrameCropper
    targets={};reference_masks={}
    for compact,items in groupby(enumerate(rows),lambda item:''.join(core.key(item[1]['text']).split())):
        if not compact:continue
        group=list(items);votes=Counter(r['text'] for _,r in group)
        if len(votes)<2:continue
        text,count=votes.most_common(1)[0]
        if count<3:continue
        reference=min((r for _,r in group if r['text']==text),key=lambda r:-r['confidence'])
        boxes=[line['box'] for line in reference.get('ocr',{}).get('lines',[])]
        if not boxes:continue
        mask=text_mask(core.image_crop(core.frame_at(path,meta,reference['start']),roi,1))
        identifier=reference['frame'];reference_masks[identifier]=(mask,boxes,reference)
        for i,row in group:
            if row['text']!=text:targets[i]=identifier
    if not targets:return 0
    repaired=0;cropper=FrameCropper(roi)
    with av.open(str(path)) as container:
        stream=configure_decoder(container.streams[meta['stream_index']])
        for i,frame in requested_frames(container,stream,rows,targets,meta):
            mask,boxes,reference=reference_masks[targets[i]];row=rows[i]
            current=text_mask(cropper.crop(frame))
            # Only whitespace changes here: all recognized characters already agree.
            # A noisy detector may extend its box into clothing; compare the
            # observed reference glyph area so scenery cannot veto a space repair.
            if same_layout(mask,current,boxes):
                row['primary_text']=row['text'];row['text']=reference['text'];row['image_verified']=True;repaired+=1
    return repaired
