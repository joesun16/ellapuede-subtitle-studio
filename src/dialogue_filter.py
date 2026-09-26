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

def prune_isolated_small_lines(result):
    """Discard tiny detector fragments attached to a full dialogue line.

    The check is geometric and works on cached OCR rows too. A one-character
    subtitle by itself, or a second line in the same font, remains untouched.
    """
    lines=result.get('lines',[])
    if len(lines)<2:return result
    largest=max(line['box'][3] for line in lines)
    substantial=[]
    for line in lines:
        candidates=line.get('candidates') or []
        caption=candidates[0].get('text','').strip() if candidates else ''
        if line['box'][3]>=largest*.8 and len(caption)>=3:
            substantial.append(line)
    if not substantial:return result
    retained=[];excluded=[]
    for line in lines:
        candidates=line.get('candidates') or []
        value=candidates[0].get('text','').strip() if candidates else ''
        x,y,w,h=line['box'];cx=x+w/2;cy=y+h/2
        fragment=(len(value)==1 and value.isalnum() and h<largest*.65 and w<.08)
        attached=fragment and any(
            main['box'][0]-.04<=cx<=main['box'][0]+main['box'][2]+.04 and
            abs(cy-(main['box'][1]+main['box'][3]/2))<=max(.12,main['box'][3]*.75)
            for main in substantial)
        (excluded if attached else retained).append(line)
    if not excluded:return result
    return dict(result,lines=retained,
                excluded_small_overlay_lines=list(result.get('excluded_small_overlay_lines',[]))+excluded)

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
    if excluded:
        result=dict(result,lines=kept,excluded_small_overlay_lines=excluded,
                    excluded_mask_lines=excluded_mask)
    return prune_isolated_small_lines(result)

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
