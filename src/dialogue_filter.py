"""Conservative removal of smaller overlay labels in a learned dialogue band."""
from statistics import median

def typical_height(observations):
    values=[o['box'][3] for o in observations if len(o.get('text','').strip())>=3]
    if len(values)<4:return None
    value=median(values);consistent=[v for v in values if .75*value<=v<=1.3*value]
    return median(consistent) if len(consistent)>=max(4,len(values)*.65) else None

def line_mask_density(mask,box):
    """Measure visible outlined glyph pixels inside one OCR box, not box height."""
    h,w=mask.shape;x,y,bw,bh=box
    x1=max(0,min(w,round(x*w)));x2=max(0,min(w,round((x+bw)*w)))
    y1=max(0,min(h,round(y*h)));y2=max(0,min(h,round((y+bh)*h)))
    if x2<=x1 or y2<=y1:return 0.
    return float(mask[y1:y2,x1:x2].mean())

def filter_lines(result,image,minimum_height,maximum_height=0,minimum_mask_density=0):
    # A mask retry removes surrounding background/padding from detector boxes.
    # It is accepted only against an already observed text hypothesis upstream.
    if image.info.get('ellapuede_recheck_mask'):minimum_height*=.5
    # A retry is checking a known neighboring reading on the current pixels;
    # cropped/resampled variants no longer share calibration density.
    if image.info.get('ellapuede_image_retry'):minimum_mask_density=0
    scale=image.info.get('ellapuede_pixel_scale',1)
    kept=[];excluded=[];excluded_mask=[];mask=None
    for line in result.get('lines',[]):
        height=line['box'][3]*image.height/scale
        fits_height=height>=minimum_height and (not maximum_height or height<=maximum_height)
        if fits_height and minimum_mask_density:
            if mask is None:
                from frame_features import text_mask
                mask=image.info.get('ellapuede_text_mask')
                if mask is None:mask=text_mask(image)
            fits_height=line_mask_density(mask,line['box'])>=minimum_mask_density
            if not fits_height:excluded_mask.append(line)
        (kept if fits_height else excluded).append(line)
    # A small, isolated glyph above an otherwise full-size dialogue line is
    # commonly a logo or a detector fragment. Do not let it become a second
    # subtitle line (or a one-frame numeric cue). A genuine one-character
    # subtitle shown alone is unaffected.
    if len(kept)>=2:
        largest=max(line['box'][3] for line in kept)
        substantial=[line for line in kept if line['box'][3]>=largest*.8]
        if substantial:
            top=min(line['box'][1] for line in substantial)
            retained=[]
            for line in kept:
                candidates=line.get('candidates') or []
                text=candidates[0].get('text','').strip() if candidates else ''
                box=line['box']
                orphan=(len(text)==1 and box[3]<largest*.65 and box[2]<.08
                        and box[1]+box[3]/2<top)
                if orphan:excluded.append(line)
                else:retained.append(line)
            kept=retained
    if not excluded:return result
    return dict(result,lines=kept,excluded_small_overlay_lines=excluded,
                excluded_mask_lines=excluded_mask)

def restore_connected_fades(rows,max_gap=.16):
    """Keep a fading caption only when its own OCR matches a nearby kept line."""
    import subtitle_ocr as core
    original=[(row['text'],row['ocr'].get('lines',[])) for row in rows]
    restored=0
    for i,row in enumerate(rows):
        if row['text']:continue
        excluded=row['ocr'].get('excluded_mask_lines',[])
        if len(excluded)!=1:continue
        candidate={'lines':excluded}
        text,confidence=core.read_lines(candidate)
        if not text:continue
        for direction in (-1,1):
            j=i+direction
            while 0<=j<len(rows) and abs(rows[j]['start']-row['start'])<=max_gap:
                neighbor_text,neighbor_lines=original[j]
                if neighbor_text and core.key(neighbor_text)==core.key(text) and len(neighbor_lines)==1:
                    box=excluded[0]['box'];reference=neighbor_lines[0]['box']
                    cy=box[1]+box[3]/2;ry=reference[1]+reference[3]/2
                    if abs(cy-ry)<=.06 and .7<=box[3]/max(reference[3],1e-9)<=1.4:
                        row['text']=text;row['confidence']=confidence
                        row['ocr']['lines']=excluded;row['fade_restored']=True;restored+=1
                        break
                j+=direction
            if row['text']:break
    return restored
