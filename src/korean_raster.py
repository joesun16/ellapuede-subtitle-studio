"""Image-backed Korean spacing and outlined exclamation separation.
No dictionary corrections: every replacement is recognized from the current image.
"""
import re
import numpy as np
from PIL import Image,ImageOps
from frame_features import text_mask


def compact(text):
    return ''.join(text.split())


def runs(values):
    edge=np.diff(np.pad(values.astype(np.int8),(1,1)))
    return list(zip(np.flatnonzero(edge==1).tolist(),np.flatnonzero(edge==-1).tolist()))


def prepare(image,box,mask=None):
    mask=text_mask(image) if mask is None else mask
    x,y,w,h=box;pad=max(2,int(h*image.height*.12))
    x1=max(0,int(x*image.width)-pad);x2=min(image.width,int((x+w)*image.width)+pad)
    y1=max(0,int(y*image.height)-pad);y2=min(image.height,int((y+h)*image.height)+pad)
    m=mask[y1:y2,x1:x2]
    if m.size==0:return None
    rows=m.sum(axis=1)
    if rows.max()<4:return None
    ys=np.flatnonzero(rows>max(2,rows.max()*.25))
    if not len(ys):return None
    top=max(0,int(ys.min())-pad);bottom=min(m.shape[0],int(ys.max())+pad+1)
    m=m[top:bottom];xs=np.flatnonzero(m.any(axis=0))
    if len(xs)<5:return None
    left=int(xs.min());right=int(xs.max())+1;m=m[:,left:right]
    yy=np.flatnonzero(m.any(axis=1));height=int(yy[-1]-yy[0]+1)
    if height<8 or not .08<=float(m.mean())<=.65:return None
    # One horizontal text line only; fragmented scene highlights use normal OCR.
    row_runs=runs(m.any(axis=1))
    if any(b-a>height*.3 for a,b in runs(~m.any(axis=1)) if a>0 and b<m.shape[0]):return None
    band=image.crop((x1+left,y1+top,x1+right,y1+top+m.shape[0]))
    occupied=m.any(axis=0)
    gaps=[(a,b) for a,b in runs(~occupied) if a>0 and b<band.width]
    threshold=max(4,height*.22,float(np.median([b-a for a,b in gaps]))*2.4) if len(gaps)>=3 else max(4,height*.28)
    cuts=[(a+b)//2 for a,b in gaps if b-a>=threshold]
    words=[ImageOps.expand(band.crop((a,0,b,band.height)),border=5,fill='black') for a,b in zip([0]+cuts,cuts+[band.width])]
    # A narrow stem above a detached dot, after a complete preceding glyph.
    spans=runs(occupied);punct=[]
    if len(spans)>=2:
        a,b=spans[-1];previous_end=spans[-2][1];vertical=runs(m[:,a:b].any(axis=1))
        if (b-a<=height*.27 and a-previous_end<=height*.3 and len(vertical)==2
                and vertical[0][1]-vertical[0][0]>=height*.4
                and vertical[1][1]-vertical[1][0]<=height*.28):
            cut=(a+previous_end)//2;binary=Image.fromarray(np.uint8(m)*255).convert('RGB')
            for gap in [max(4,round(height*.15)),max(8,round(height*.3))]:
                variant=Image.new('RGB',(binary.width+gap,binary.height))
                variant.paste(binary.crop((0,0,cut,binary.height)),(0,0))
                variant.paste(binary.crop((cut,0,binary.width,binary.height)),(cut+gap,0))
                punct.append(ImageOps.expand(variant,border=8,fill='black'))
    return {'words':words,'word_count':len(words),'punctuation':punct}


def repair(image,lines,recognize_batch):
    """recognize_batch accepts PIL images and returns (text, confidence) pairs."""
    plans=[];images=[];mask=None
    for i,line in enumerate(lines):
        if not line.get('candidates'):continue
        original=line['candidates'][0]['text']
        if not any('가'<=c<='힣' for c in original):continue
        if mask is None:
            pixels=np.asarray(image.convert('RGB')).astype(np.int16)
            mask=text_mask(image)&((pixels.max(axis=2)-pixels.min(axis=2))<=24)
        plan=prepare(image,line['box'],mask)
        if not plan:continue
        word_indexes=[];punct_indexes=[]
        if 1<plan['word_count']<=12 and plan['word_count']!=len(original.split()):
            for im in plan['words']:word_indexes.append(len(images));images.append(im)
        # Only re-evaluate a visibly detached exclamation; no punctuation guessing.
        if plan['punctuation'] and re.search(r'[가-힣]!?$',original.rstrip()):
            for im in plan['punctuation']:punct_indexes.append(len(images));images.append(im)
        if word_indexes or punct_indexes:plans.append((i,original,word_indexes,punct_indexes))
    if not images:return lines
    results=recognize_batch(images);updated=list(lines)
    for i,original,word_indexes,punct_indexes in plans:
        replacement=original;confidence=lines[i]['candidates'][0]['confidence'];evidence=[]
        if word_indexes:
            pieces=[results[j][0].strip() for j in word_indexes];scores=[results[j][1] for j in word_indexes]
            proposal=' '.join(pieces)
            if all(pieces) and min(scores)>=.90 and compact(proposal)==compact(original):
                replacement=proposal;confidence=min(scores);evidence.append('visible_word_gaps')
        if punct_indexes:
            readings=[results[j] for j in punct_indexes]
            if (len(readings)==2 and readings[0][0]==readings[1][0] and min(x[1] for x in readings)>=.90
                    and readings[0][0].endswith('!')):
                proposal=compact(readings[0][0])[:-1];before=compact(original).removesuffix('!')
                changes=[(a,b) for a,b in zip(before,proposal) if a!=b]
                if (len(before)==len(proposal) and len(changes)<=1
                        and all('가'<=a<='힣' and '가'<=b<='힣' for a,b in changes)):
                    chars=iter(proposal)
                    replacement=''.join(c if c.isspace() else next(chars) for c in replacement.removesuffix('!'))+'!'
                    confidence=min(x[1] for x in readings);evidence.append('separated_exclamation')
        if replacement!=original:
            updated[i]=dict(lines[i],candidates=[{'text':replacement,'confidence':confidence}],primary_text=original,image_repairs=evidence)
    return updated
