#!/usr/bin/env python3
"""Local, frame-by-frame burned-in subtitle OCR for macOS and Windows."""
from __future__ import annotations

import argparse
import base64
from collections import Counter, deque, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import resource_control as control
from output_policy import aligned_stem, output_stems

from version import VERSION as RELEASE_VERSION
VERSION = RELEASE_VERSION + '-beta'
# Frame interpretation changed: discard isolated overlay glyphs before caching.
# Earlier OCR results must not be reused with the new dialogue filter.
OCR_CACHE_REVISION = '0.14.4-beta'
# SRC holds the Python/Swift sources; ROOT holds bundled resources (models, assets,
# .runtime). PyInstaller flattens both into _MEIPASS, so they coincide when frozen.
SRC = Path(__file__).resolve().parent
ROOT = Path(getattr(sys, '_MEIPASS', SRC.parent))
VIDEO_EXTS = {'.mp4', '.mkv', '.mov', '.m4v', '.avi', '.webm', '.ts', '.m2ts'}


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def save_json(path, obj):
    atomic_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def natural_key(path):
    return [(0, int(x)) if x.isdigit() else (1, x.casefold())
            for x in re.split(r'(\d+)', str(path))]


def episode_info(name):
    for pattern in [r'(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]*e(\d{1,4})(?!\d)',
                    r'第\s*(\d{1,4})\s*[集话]',
                    r'(?i)(?<![a-z0-9])(?:ep|episode|e)[ ._-]*(\d{1,4})(?!\d)']:
        m = re.search(pattern, name)
        if m:
            if len(m.groups()) == 2:
                return {'season': int(m[1]), 'episode': int(m[2])}
            return {'season': None, 'episode': int(m[1])}
    return {'season': None, 'episode': None}


def normalize(text):
    text = unicodedata.normalize('NFC', text)
    text = ''.join(c for c in text if c == '\n' or unicodedata.category(c) != 'Cc')
    return '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()).strip()


def key(text):
    # Case, punctuation and words remain significant. Only typographic quotes and
    # line wrapping are equivalent; "can" and "can't" must NEVER fuzzy-merge.
    value=' '.join(normalize(text).translate(str.maketrans('‘’“”', "''\"\"")).split())
    # Han OCR intermittently inserts spaces between glyphs. Compare those runs
    # together while retaining an actually observed spelling in the export.
    # Hangul and Latin word boundaries remain significant.
    return re.sub(r'(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])', '', value)


def _line_geometry(row):
    """Return a conservative vertical signature for OCR text in one frame."""
    lines = [x for x in row.get('ocr', {}).get('lines', [])
             if x.get('candidates') and normalize(x['candidates'][0].get('text', ''))]
    if not lines:
        return None
    centers = [x['box'][1] + x['box'][3] / 2 for x in lines]
    heights = [x['box'][3] for x in lines]
    return (sum(centers) / len(centers), sum(heights) / len(heights), len(lines))


def _same_visual_line(left, right):
    signatures = [_line_geometry(row) for row in (left + right)]
    signatures = [x for x in signatures if x is not None]
    if not signatures:
        return False
    center = sum(x[0] for x in signatures) / len(signatures)
    height = sum(x[1] for x in signatures) / len(signatures)
    count = max(x[2] for x in signatures)
    return all(abs(x[0] - center) <= max(.018, height * .45) and
               abs(x[1] - height) <= max(.012, height * .45) and x[2] == count
               for x in signatures)


def _compact_identical_fragments(runs):
    """Join identical readings split by a tiny detector gap in one glyph band.

    Rows without OCR geometry are intentionally left untouched. A plain blank
    therefore remains a real caption boundary in conservative callers/tests.
    """
    compact = []
    for run in runs:
        if not run['key']:
            compact.append(run)
            continue
        previous_index = next((i for i in range(len(compact) - 1, -1, -1)
                               if compact[i]['key']), None)
        if previous_index is None:
            compact.append(run)
            continue
        previous = compact[previous_index]
        gap = run['rows'][0]['start'] - previous['rows'][-1]['end']
        between_blank = all(not item['key'] for item in compact[previous_index + 1:])
        if (between_blank and previous['key'] == run['key'] and -1e-9 <= gap <= .12 + 1e-9 and
                _same_visual_line(previous['rows'], run['rows'])):
            previous['rows'].extend(run['rows'])
            previous['flags'] = sorted(set(previous.get('flags', [])) | {'fragment_compacted'})
            del compact[previous_index + 1:]
            continue
        compact.append(run)
    return compact


def _same_caption_geometry(left, right):
    """Compare the typical glyph band, ignoring an occasional bad OCR box."""
    from statistics import median
    a=[value for row in left for value in [_line_geometry(row)] if value]
    b=[value for row in right for value in [_line_geometry(row)] if value]
    if not a or not b:return False
    ay,ah=median(x[0] for x in a),median(x[1] for x in a)
    by,bh=median(x[0] for x in b),median(x[1] for x in b)
    return abs(ay-by)<=max(.018,min(ah,bh)*.35) and .72<=ah/max(bh,1e-9)<=1.38


def _protected_text_change(left,right):
    """Keep numbers and negation changes as separate evidence, however brief."""
    a,b=key(left).casefold(),key(right).casefold()
    if re.findall(r'\d+',a)!=re.findall(r'\d+',b):return True
    # A short answer can change from a question to an exclamation while the
    # word glyphs remain identical. Do not infer punctuation from neighbors.
    if re.findall(r'[?!。！？]+$',a)!=re.findall(r'[?!。！？]+$',b):return True
    negation=r"\b(?:not|no|never|cannot|can['’]?t|won['’]?t|don['’]?t|didn['’]?t|isn['’]?t|aren['’]?t|wasn['’]?t|weren['’]?t|shouldn['’]?t|wouldn['’]?t|couldn['’]?t|n['’]?t|ne|pas|non|nicht|kein|sin)\b|[不没無无未안못않ないぬ]"
    return re.findall(negation,a)!=re.findall(negation,b)


def _compact_ocr_flicker(runs):
    """Collapse continuous spacing/case flicker of the same visible caption."""
    compact=[]
    for run in runs:
        if not run['key'] or not compact or not compact[-1]['key']:
            compact.append(run);continue
        previous=compact[-1]
        gap=run['rows'][0]['start']-previous['rows'][-1]['end']
        if gap<-.001 or gap>.08 or not _same_caption_geometry(previous['rows'],run['rows']):
            compact.append(run);continue
        a,b=previous['key'],run['key']
        if _protected_text_change(a,b):compact.append(run);continue
        # Word-spacing/case variation contains exactly the same visible glyphs.
        # It can persist for several frames on the Windows RapidOCR route, so
        # a short-duration limit would split one held subtitle repeatedly.
        # Keep punctuation significant and require a continuous visual band.
        spacing_equivalent=(''.join(c.casefold() for c in a if not c.isspace())==
                            ''.join(c.casefold() for c in b if not c.isspace()))
        if spacing_equivalent:
            previous['rows'].extend(run['rows'])
            previous['key']=Counter(key(row['text']) for row in previous['rows']).most_common(1)[0][0]
            previous['flags']=sorted(set(previous['flags'])|set(run['flags'])|{'ocr_spacing_compacted'})
            continue
        compact.append(run)
    return compact


def _raw_lines_support_caption(row, caption):
    """Check that a dropped line was still seen in this frame's OCR boxes."""
    expected=[key(line).casefold() for line in caption.splitlines() if key(line)]
    observed=[key(candidate.get('text','')).casefold()
              for line in row.get('ocr',{}).get('lines',[])
              for candidate in line.get('candidates',[])[:1]
              if candidate.get('confidence',0)>=.25]
    if len(observed)<len(expected):return False
    return all(any(SequenceMatcher(None,want,got).ratio()>=.84 for got in observed)
               for want in expected)


def _brief_caption_variant(anchor, variant):
    """Only bridge a short, visually stable OCR variant between two anchors."""
    if not variant['key'] or _protected_text_change(anchor['key'],variant['key']):return False
    if variant['key']==anchor['key']:return True
    duration=variant['rows'][-1]['end']-variant['rows'][0]['start']
    if duration>.45+1e-9:return False
    anchor_text=Counter(row['text'] for row in anchor['rows']).most_common(1)[0][0]
    variant_text=Counter(row['text'] for row in variant['rows']).most_common(1)[0][0]
    anchor_lines=normalize(anchor_text).splitlines()
    variant_lines=normalize(variant_text).splitlines()
    if len(variant_lines)<len(anchor_lines):
        # A low-confidence OCR line may have been filtered by read_lines(),
        # but its actual glyph box must still be present in every affected frame.
        return (_same_caption_geometry(anchor['rows'],variant['rows']) and
                all(_raw_lines_support_caption(row,anchor_text) for row in variant['rows']))
    if len(variant_lines)!=len(anchor_lines):return False
    # OCR can lose an edge glyph in any script. NFKD also exposes a partially
    # recognized Hangul syllable (ㅍ versus 피) as a prefix of its full form.
    # Substitutions inside words (car/cat, 가/나) must remain separate.
    def letters(line):
        return ''.join(c for c in unicodedata.normalize('NFKD',line.casefold())
                       if c.isalnum())
    for a,b in zip(anchor_lines,variant_lines):
        a,b=letters(a),letters(b)
        if not a or not b or abs(len(a)-len(b))>2 or not (a.startswith(b) or b.startswith(a)):
            return False
    a,b=letters(anchor_text),letters(variant_text)
    contains_cjk=any('\u3400'<=c<='\u9fff' or '\uac00'<=c<='\ud7a3'
                     for c in anchor_text+variant_text)
    threshold=.60 if min(len(a),len(b))<=2 else (.88 if contains_cjk else .90)
    return SequenceMatcher(None,a,b).ratio()>=threshold


def _compact_bracketed_ocr_noise(runs):
    """Join a held caption when the same observed reading brackets OCR flicker.

    A genuine change at either edge has no matching anchor on both sides, so it
    stays separate. Numbers and negation are protected even inside a caption.
    """
    compact=list(runs);i=0
    while i<len(compact):
        anchor=compact[i]
        if not anchor['key'] or anchor['rows'][-1]['end']-anchor['rows'][0]['start']<.15:
            i+=1;continue
        matched=None
        for j in range(i+2,len(compact)):
            right=compact[j]
            if not right['key'] or right['rows'][0]['start']-anchor['rows'][-1]['end']>1.50:break
            middle=compact[i+1:j]
            if not all(_brief_caption_variant(anchor,run) for run in middle):break
            if (right['key']==anchor['key'] and
                    right['rows'][-1]['end']-right['rows'][0]['start']>=.20 and
                    _same_caption_geometry(anchor['rows'],right['rows'])):matched=j
        if matched is None:
            i+=1;continue
        joined=compact[i:matched+1]
        compact[i:matched+1]=[{'key':anchor['key'],
                             'rows':[row for run in joined for row in run['rows']],
                             'flags':sorted(set().union(*(run['flags'] for run in joined))|
                                            {'bracketed_ocr_flicker'})}]
        # The longer observed anchor may bridge another brief defect.
    return compact


def _dominant_caption_box(row):
    """Ignore unrelated low-confidence detections when tracking a text band."""
    wanted=key(row['text']).casefold()
    lines=[line for line in row.get('ocr',{}).get('lines',[])
           if line.get('candidates') and
           line['candidates'][0].get('confidence',0)>=.5 and
           key(line['candidates'][0].get('text','')).casefold() in wanted]
    if not lines:return None
    return [(line['box'][1]+line['box'][3]/2,line['box'][3]) for line in lines]


def _stable_caption_band(anchor, variant):
    from statistics import median
    a=[box for row in anchor['rows'] for box in (_dominant_caption_box(row) or [])]
    b=[box for row in variant['rows'] for box in (_dominant_caption_box(row) or [])]
    if not a or not b:return False
    ay,ah=median(x[0] for x in a),median(x[1] for x in a)
    by,bh=median(x[0] for x in b),median(x[1] for x in b)
    return abs(ay-by)<=max(.018,min(ah,bh)*.35) and .72<=ah/max(bh,1e-9)<=1.38


def _compact_recurrent_ocr_noise(runs):
    """Collapse repeated OCR edge flicker across scripts without crossing a change.

    A held caption can alternate full/partial/full/partial faster than any
    single anchor run lasts. Require the exact full reading on both sides,
    strong total support, the same text band, and a short prefix-only defect.
    """
    compact=list(runs);i=0
    while i<len(compact):
        anchor=compact[i]
        if not anchor['key']:
            i+=1;continue
        chosen=None;canonical=anchor['rows'][-1]['end']-anchor['rows'][0]['start'];noise=0
        anchors=1
        for j in range(i+1,len(compact)):
            item=compact[j]
            if not item['key'] or item['rows'][0]['start']-anchor['rows'][-1]['end']>1.5:break
            duration=item['rows'][-1]['end']-item['rows'][0]['start']
            if item['key']==anchor['key']:
                if not _stable_caption_band(anchor,item):break
                canonical+=duration;anchors+=1
                if (anchors>=2 and canonical>=.25 and noise<=.45 and
                        canonical>=noise*1.5 and
                        item['rows'][-1]['end']-anchor['rows'][0]['start']>=.4):
                    chosen=j
            elif (_brief_caption_variant(anchor,item) and
                  _stable_caption_band(anchor,item)):
                noise+=duration
                if noise>.45:break
            else:break
        if chosen is None:
            i+=1;continue
        joined=compact[i:chosen+1]
        compact[i:chosen+1]=[{'key':anchor['key'],
                             'rows':[row for run in joined for row in run['rows']],
                             'flags':sorted(set().union(*(run['flags'] for run in joined))|
                                            {'recurrent_ocr_flicker'})}]
    return compact


def _coalesce_equal_runs(runs):
    """A prior OCR repair can make neighboring run keys identical."""
    compact=[]
    for run in runs:
        if compact and compact[-1]['key']==run['key']:
            compact[-1]['rows'].extend(run['rows'])
            compact[-1]['flags']=sorted(set(compact[-1]['flags'])|set(run['flags']))
        else:compact.append(run)
    return compact


def _volatile_near(left, right):
    """Admit likely OCR variants without admitting a short real word change.

    This is only a *candidate* relation. _compact_volatile_ocr_noise also
    requires repeated, rapidly alternating readings within the same glyph band.
    A simple A/B/A word substitution is deliberately left separate.
    """
    if _protected_text_change(left['key'], right['key']):return False
    a,b=left['key'],right['key']
    if not a or not b:return False
    al=Counter(row['text'] for row in left['rows']).most_common(1)[0][0].splitlines()
    bl=Counter(row['text'] for row in right['rows']).most_common(1)[0][0].splitlines()
    if len(al)==len(bl):
        if min(len(a),len(b))/max(len(a),len(b))<.75:return False
        similarity=SequenceMatcher(None,a,b).ratio()
        if similarity<.87:return False
        if _same_caption_geometry(left['rows'],right['rows']):return True
        # A single distorted detector box must not split an otherwise
        # recurring, almost identical reading. The volatility requirement
        # below still prevents a simple A/B/A word substitution from merging.
        duration=min(item['rows'][-1]['end']-item['rows'][0]['start']
                     for item in (left,right))
        return duration<=.08 and similarity>=.92
    shorter,longer=(al,bl) if len(al)<len(bl) else (bl,al)
    if len(shorter)+1!=len(longer):return False
    if not all(any(SequenceMatcher(None,line,full).ratio()>=.92 for full in longer)
               for line in shorter):return False
    # The visible surviving line must occupy the same part of the frame.
    signatures=[_line_geometry(row) for row in left['rows']+right['rows']]
    signatures=[value for value in signatures if value]
    if len(signatures)<2:return False
    return max(value[1] for value in signatures)/max(min(value[1] for value in signatures),1e-9)<1.6


def _compact_volatile_ocr_noise(runs):
    """Turn rapidly alternating OCR readings of one held caption into one cue.

    The exported reading is still one that OCR actually observed. Requiring at
    least three rapid switches prevents a brief A/B/A *real* text change from
    being voted away. Blank intervals, numerals and negations remain barriers.
    """
    compact=[];i=0
    while i<len(runs):
        start=i;group=[runs[i]];i+=1
        while i<len(runs):
            previous,item=group[-1],runs[i]
            if (not previous['key'] or not item['key'] or
                    item['rows'][0]['start']-previous['rows'][-1]['end']>.08 or
                    item['rows'][-1]['end']-group[0]['rows'][0]['start']>3.5 or
                    not _volatile_near(previous,item)):
                break
            duration=item['rows'][-1]['end']-item['rows'][0]['start']
            # A sustained different full line may be a genuine new subtitle.
            item_lines=item['rows'][0]['text'].splitlines()
            first_lines=group[0]['rows'][0]['text'].splitlines()
            if (duration>.24 and len(item_lines)==len(first_lines)
                    and item['key']!=group[0]['key']):break
            group.append(item);i+=1
        keys=Counter(run['key'] for run in group)
        switches=sum(group[j]['rows'][-1]['end']-group[j]['rows'][0]['start']<=.18
                     for j in range(1,len(group)))
        span=group[-1]['rows'][-1]['end']-group[0]['rows'][0]['start']
        if len(group)>=4 and switches>=3 and span>=.22 and len(keys)>=3:
            observed=Counter(row['text'] for run in group for row in run['rows'])
            # A recognizer may drop the upper line for most frames of a held
            # two-line caption. Repeated complete observations take precedence
            # over more frequent partial readings; still export observed text.
            eligible=[value for value,count in observed.items() if count>=3]
            canonical=max(eligible or observed,
                          key=lambda value:(len(value.splitlines()),observed[value],len(value)))
            canonical_key=key(canonical)
            if observed[canonical]>=3:
                compact.append({'key':canonical_key,
                                'rows':[row for run in group for row in run['rows']],
                                'flags':sorted(set().union(*(run['flags'] for run in group))|
                                               {'volatile_ocr_compacted'})})
                continue
        compact.extend(group)
    return compact


def _extend_volatile_to_observed_anchor(runs):
    """Join a noisy opening to its later stable reading when both observed it.

    The eventual reading must have appeared repeatedly inside the noisy span
    and then persisted later in the same visual band. This avoids treating a
    new, merely similar sentence as a repair of the previous subtitle.
    """
    compact=list(runs);i=0
    while i<len(compact):
        first=compact[i]
        if 'volatile_ocr_compacted' not in first['flags']:
            i+=1;continue
        original=Counter(key(row['text']) for row in first['rows'])
        if not any(n>=2 and k!=first['key'] for k,n in original.items()):
            i+=1;continue
        group=[first];best=None
        for j in range(i+1,len(compact)):
            item=compact[j];previous=group[-1]
            if (not item['key'] or
                    item['rows'][0]['start']-previous['rows'][-1]['end']>.08 or
                    item['rows'][-1]['end']-first['rows'][0]['start']>2.5 or
                    not _volatile_near(previous,item)):
                break
            group.append(item)
            duration=item['rows'][-1]['end']-item['rows'][0]['start']
            if duration<.24 or original[item['key']]<2:continue
            counts=Counter(key(row['text']) for run in group for row in run['rows'])
            if counts[item['key']]>=max(counts.values()):best=(j,item['key'])
        if best is None:
            i+=1;continue
        last,canonical=best;joined=compact[i:last+1]
        compact[i:last+1]=[{'key':canonical,
                            'rows':[row for run in joined for row in run['rows']],
                            'flags':sorted(set().union(*(run['flags'] for run in joined))|
                                           {'volatile_anchor_compacted'})}]
        i+=1
    return compact


def roi_arg(value):
    try:
        roi = tuple(float(x) for x in value.split(','))
        if len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
            raise ValueError()
        return roi
    except ValueError:
        raise argparse.ArgumentTypeError('ROI 必须是归一化 x1,y1,x2,y2，范围 0–1')


def probe(path):
    import av
    with av.open(str(path)) as c:
        streams = [s for s in c.streams.video if not (s.disposition & s.disposition.attached_pic)]
        if not streams:
            raise ValueError('没有可解码的视频流')
        s = streams[0]
        first_frame=next(c.decode(s),None)
        rotation=int(first_frame.rotation) if first_frame is not None else 0
        width,height=(s.height,s.width) if rotation%180 else (s.width,s.height)
        origin = float(c.start_time / av.time_base) if c.start_time is not None else float((s.start_time or 0) * s.time_base)
        duration = float(c.duration / av.time_base) if c.duration is not None else float((s.duration or 0) * s.time_base)
        if duration <= 0:
            raise ValueError('无法取得有效视频时长')
        return {'width': width, 'height': height, 'duration': duration,'rotation':rotation,
                'origin': origin, 'stream_index': s.index, 'fps_hint': float(s.average_rate or 25),
                'time_base': str(s.time_base), 'subtitle_streams': len(c.streams.subtitles)}


def frame_at(path, meta, seconds):
    import av
    with av.open(str(path)) as c:
        s = c.streams[meta['stream_index']]
        target = seconds + meta['origin']
        c.seek(int(target / float(s.time_base)), stream=s, backward=True)
        for f in c.decode(s):
            if f.pts is not None and float(f.pts * f.time_base) + 1e-6 >= target:
                return oriented_image(f)
    raise ValueError(f'无法定位视频帧 {seconds:.3f}s')


def oriented_image(frame):
    image=frame.to_image()
    rotation=int(frame.rotation)
    return image.rotate(rotation,expand=True) if rotation else image


class VisionPool:
    def __init__(self, languages, words):
        self.languages = languages
        self.words = words
        self.name = 'AppleVision-accurate-no-correction'
        self.idle=queue.Queue()
        self.processes = []
        self.lock = threading.Lock()
        self.binary = ROOT / '.runtime' / 'vision-ocr'
        source = SRC / 'vision_ocr.swift'
        if getattr(sys,'frozen',False):
            if not self.binary.exists():raise RuntimeError('安装包缺少识别组件，请重新安装完整应用。')
            return
        self.binary.parent.mkdir(exist_ok=True)
        if not self.binary.exists() or self.binary.stat().st_mtime < source.stat().st_mtime:
            print('编译本地 Apple Vision OCR…', flush=True)
            subprocess.run(['swiftc', '-O', str(source), '-o', str(self.binary)], check=True)

    def command(self):
        return [str(self.binary)]

    def recognize(self, image, correction=False):
        result=self._recognize_once(image,correction)
        if (getattr(self,'name','').startswith('AppleVision') and self.languages==['ko-KR']
                and image.info.get('ellapuede_dialogue_crop') and not read_lines(result)[0]):
            from korean_raster import prepare
            if prepare(image,(0,0,1,1)) is None:return result
            scale=image.info.get('ellapuede_pixel_scale',1)
            if scale>1:
                retry=self._recognize_once(image_crop(image,(0,0,1,1),1/scale),False)
                if read_lines(retry)[0]:return dict(retry,image_verified_fallback=True)
            with self.lock:
                if not hasattr(self,'korean_fallback'):
                    from optional_ocr import OptionalOCR
                    self.korean_fallback=OptionalOCR(self,'韩语短行补识别',lambda:RapidPool(['ko-KR'],[],1))
                    self.korean_fallback_slots=threading.BoundedSemaphore(1)
                secondary=self.korean_fallback
            with self.korean_fallback_slots:
                retry=secondary.recognize(image,dialogue_min_height=getattr(self,'dialogue_min_height',0)*.6,
                                          dialogue_max_height=getattr(self,'dialogue_max_height',0)*1.8)
            if retry is None:return result
            text,confidence=read_lines(retry)
            if confidence>=.9 and any('가'<=c<='힣' for c in text):
                self.last_backend='Apple Vision + 离线韩语短行补识别'
                return dict(retry,image_verified_fallback=True)
        return result

    def _recognize_once(self, image, correction=False):
        p=None
        while True:
            try:p,responses=self.idle.get_nowait()
            except queue.Empty:p=None;break
            if getattr(p,'generation',0)==getattr(self,'generation',0):break
            if p.poll() is None:p.kill();p.wait()
        if p is None or p.poll() is not None:
            generation=getattr(self,'generation',0)
            with self.lock:
                p=subprocess.Popen((self.spawn_command() if hasattr(self,'spawn_command') else self.command()),stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self.processes.append(p)
            p.generation=generation
            responses=queue.Queue()
            def read_responses():
                for line in p.stdout:responses.put(line)
                responses.put(None)
            reader=threading.Thread(target=read_responses,daemon=True);reader.start();p.reader=reader
        try:
            from image_transport import encode_image
            data=encode_image(image)
            request={'image':base64.b64encode(data).decode(),'languages':self.languages,'words':self.words,'correction':correction,'dialogue_crop':bool(image.info.get('ellapuede_dialogue_crop'))}
            try:p.stdin.write(json.dumps(request)+'\n');p.stdin.flush()
            except (BrokenPipeError,OSError) as error:
                raise RuntimeError('OCR 子进程已退出，无法发送图像；请检查离线识别组件和模型是否完整。') from error
            try:line=responses.get(timeout=90)
            except queue.Empty:
                p.kill();p.wait()
                if isinstance(self,RapidPool) and not getattr(self,'force_cpu',False):
                    self.reset_backend(cpu=True);control.emit('phase',phase='加速组件响应超时，正在切换 CPU 重试')
                    return self.recognize(image,correction)
                raise RuntimeError('单帧 OCR 超过 90 秒；已停止识别进程，保留缓存供重试。')
            if not line:raise RuntimeError(f'OCR 子进程已退出（返回码 {p.poll()}）；请检查离线识别组件和模型是否完整。')
            result=json.loads(line)
            if 'error' in result:raise RuntimeError(result['error'])
            if result.get('detected_language')=='ko-KR' and hasattr(self,'korean'):
                self.korean=True;self.route='ko_v5';self.name=self.model_name();self.languages=['ko-KR']
                self.last_detected_language='ko-KR'
            backend=result.get('backend')
            if backend:
                if isinstance(self,RapidPool):
                    if backend.startswith('DirectML'):self.dml_backend=backend
                    elif backend.startswith('CPU'):self.cpu_seen=True
                    if '显卡异常后回退' in backend:self.dml_backend=None
                    backend=('CPU + '+self.dml_backend) if getattr(self,'cpu_seen',False) and getattr(self,'dml_backend',None) else backend
                if backend!=getattr(self,'last_backend',None):self.last_backend=backend;control.emit('backend',backend=backend)
            from dialogue_filter import filter_lines
            filtered=filter_lines(result,image,getattr(self,'dialogue_min_height',0),
                                  getattr(self,'dialogue_max_height',0),getattr(self,'dialogue_min_mask_density',0))
            if 'auto' in self.languages:
                from language_detection import guess_language
                hint=guess_language(read_lines(filtered)[0])
                if hint:self.last_detected_language=hint
            return filtered
        finally:
            if p.poll() is None:
                if p.generation==getattr(self,'generation',0):self.idle.put((p,responses))
                else:p.kill();p.wait()

    def reset_backend(self, cpu=False, languages=None):
        """Retire idle workers immediately; in-flight workers retire on return."""
        with self.lock:
            if cpu:
                self.force_cpu=True
                if isinstance(self,RapidPool):self.dml_backend=None;self.last_backend=None
            if languages is not None:
                self.languages=list(languages)
                if isinstance(self,RapidPool):
                    from ocr_routes import select_route
                    self.route=select_route(languages)
                    self.korean=self.route=='ko_v5';self.english=self.route=='en_v5'
                    self.name=self.model_name()
                    self._device_probe_claimed=False;self.cpu_seen=False;self.dml_backend=None;self.last_backend=None
            self.generation=getattr(self,'generation',0)+1
            while True:
                try:p,_=self.idle.get_nowait()
                except queue.Empty:break
                if p.poll() is None:p.kill();p.wait()

    def close(self):
        if hasattr(self,'korean_fallback'):self.korean_fallback.close()
        for p in self.processes:
            if p.poll() is None:
                p.stdin.close()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            if hasattr(p,'reader'):p.reader.join(timeout=1)
            if p.stdout and (not hasattr(p,'reader') or not p.reader.is_alive()):p.stdout.close()


class RapidPool(VisionPool):
    def __init__(self,languages,words,threads=2,device='auto'):
        import importlib.util
        if importlib.util.find_spec('rapidocr') is None:
            raise RuntimeError('离线识别组件 rapidocr 不可用；源码环境请安装 requirements-desktop.txt 中的依赖，安装版请重新安装完整应用。')
        from ocr_routes import select_route
        self.languages=languages;self.words=words;self.threads=threads;self.device=device;self._device_probe_claimed=False
        self.route=select_route(languages)
        self.korean=self.route=='ko_v5';self.english=self.route=='en_v5'
        self.name=self.model_name()
        self.idle=queue.Queue();self.processes=[];self.lock=threading.Lock()
        self.model_dir=ROOT/'models'
        from ocr_routes import ROUTES
        if not all((self.model_dir/name).exists() for name in (ROUTES[self.route]['det'],ROUTES[self.route]['rec'])):
            raise RuntimeError('安装包缺少离线识别模型，请重新安装完整应用。')

    def model_name(self):
        return 'RapidOCR-ONNX-'+self.route+'-3.9.2'

    def spawn_command(self):
        # The first automatic worker tests DirectML; the others remain CPU
        # lanes. This avoids N copies of a GPU model on integrated graphics.
        if self.device=='auto' and not getattr(self,'force_cpu',False):
            if self._device_probe_claimed:return self.command('cpu')
            self._device_probe_claimed=True
        return self.command()

    def command(self,device_override=None):
        if getattr(sys,'frozen',False):
            worker=Path(sys.executable).with_name('EllaPuedeWorker.exe' if os.name=='nt' else 'EllaPuedeWorker')
            cmd=[str(worker if worker.exists() else sys.executable),'--ocr-worker']
        else:cmd=[sys.executable,str(SRC/'portable_ocr_worker.py')]
        return cmd+['--model-dir',str(self.model_dir),'--threads',str(self.threads),'--route',self.route,'--device',device_override or self.device]+(['--auto-language'] if 'auto' in self.languages and not getattr(self,'auto_probe',False) else [])+(['--cpu'] if getattr(self,'force_cpu',False) else [])


def image_crop(image, roi, scale=2):
    from PIL import Image
    w, h = image.size
    crop = image.crop((round(roi[0] * w), round(roi[1] * h), round(roi[2] * w), round(roi[3] * h)))
    source_scale=image.info.get('ellapuede_pixel_scale',1)
    if scale != 1:
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)
    crop.info['ellapuede_pixel_scale']=source_scale*scale
    crop.info['ellapuede_dialogue_crop']=True
    if roi==(0,0,1,1) and 'ellapuede_text_mask' in image.info:
        crop.info['ellapuede_text_mask']=image.info['ellapuede_text_mask']
    return crop


def read_lines(result):
    items = [x for x in result['lines'] if x.get('candidates') and normalize(x['candidates'][0]['text'])
             and x['candidates'][0].get('confidence',0)>=.5
             and any(c.isalnum() for c in x['candidates'][0]['text'])]
    # Group by vertical center, then order left to right (two speakers may share a row).
    items.sort(key=lambda x: x['box'][1] + x['box'][3] / 2)
    rows = []
    for item in items:
        cy = item['box'][1] + item['box'][3] / 2
        if rows and abs(cy - rows[-1][0]) < min(item['box'][3], rows[-1][1][0]['box'][3]) * .45:
            rows[-1][1].append(item)
        else:
            rows.append((cy, [item]))
    text = '\n'.join(' '.join(x['candidates'][0]['text'] for x in sorted(row, key=lambda x: x['box'][0]))
                     for _, row in rows)
    confidence = min((x['candidates'][0]['confidence'] for x in items), default=0)
    return normalize(text), confidence


def calibrate(path, meta, pool, cache, forced_roi=None):
    from PIL import Image, ImageDraw
    samples = []
    observations = []
    # Avoid depending on the opening titles alone.
    sample_count=12
    for i in range(sample_count):
        control.check()
        control.emit('phase',phase=f'校准手动区域字号：第 {i+1} / {sample_count} 个取样画面' if forced_roi is not None else f'定位字幕区域：第 {i+1} / {sample_count} 个取样画面')
        t = meta['duration'] * (i + .5) / sample_count
        im = frame_at(path, meta, t)
        ocr_image=image_crop(im,forced_roi,1) if forced_roi is not None else im
        result = pool.recognize(ocr_image)
        samples.append((t, im))
        mask=None
        if forced_roi is not None and result['lines']:
            from frame_features import text_mask
            mask=text_mask(ocr_image)
        for line in result['lines']:
            x, y, w, h = line['box']
            density=None
            if mask is not None:
                from dialogue_filter import line_mask_density
                density=line_mask_density(mask,line['box'])
            if forced_roi is not None:
                a,b,c,d=forced_roi;x=a+x*(c-a);y=b+y*(d-b);w*=c-a;h*=d-b
            text = line['candidates'][0]['text'] if line['candidates'] else ''
            if .009 <= h <= .09 and w >= .07 and (forced_roi is not None or y+h/2 >= .45) and len(text.strip()) >= 2:
                observations.append({'t': t, 'text': text, 'box': [x, y, w, h],
                                     'mask_density':density})
    clusters = []
    for o in sorted(observations, key=lambda o: o['box'][1]):
        cy = o['box'][1] + o['box'][3] / 2
        match = next((g for g in clusters if abs(cy - sum(x['box'][1]+x['box'][3]/2 for x in g)/len(g)) < .055
                      and .65 <= o['box'][3]/__import__('statistics').median(x['box'][3] for x in g) <= 1.55), None)
        if match is None:
            clusters.append([o])
        else:
            match.append(o)
    candidates = []
    for group in clusters:
        from dialogue_filter import typical_height
        font_height=typical_height(group)
        if font_height:
            group=[o for o in group if o['box'][3]>=font_height*.75]
        unique = len({key(o['text']) for o in group})
        coverage = len({o['t'] for o in group})
        cy = sum(o['box'][1] + o['box'][3] / 2 for o in group) / len(group)
        score = unique * coverage * __import__('statistics').median(o['box'][3] for o in group)**.5
        roi = (0.02, max(0, min(o['box'][1] for o in group) - .025),
               .98, min(1, max(o['box'][1] + o['box'][3] for o in group) + .025))
        densities=[o['mask_density'] for o in group if o.get('mask_density') is not None]
        mask_density=__import__('statistics').median(densities) if len(densities)>=4 else None
        candidates.append({'roi': roi, 'score': score, 'unique': unique, 'coverage': coverage,
                           'font_height':font_height,'mask_density':mask_density})
    candidates.sort(key=lambda x: x['score'], reverse=True)
    if forced_roi is None and (not candidates or candidates[0]['unique'] < 3 or candidates[0]['coverage'] < 3):
        raise ValueError('未能可靠定位下方对白区域，请手动框选本剧字幕区域；不会改为全画面识别。')
    roi = tuple(forced_roi or candidates[0]['roi'])
    result = {'roi': roi, 'automatic': forced_roi is None, 'candidates': candidates,
              'font_height':candidates[0].get('font_height') if candidates else None,
              'mask_density':candidates[0].get('mask_density') if candidates else None,
              'warning': '本剧共用此区域；可在开始前查看并调整。'}
    save_json(cache / 'calibration.json', result)
    return result


def source_fingerprint(path):
    # Full streaming hash prevents stale caches after same-size source replacement.
    digest = hashlib.sha256();size=max(1,path.stat().st_size);read=0;last_notice=time.monotonic()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            control.check()
            digest.update(block);read+=len(block)
            if time.monotonic()-last_notice>=1:
                control.emit('phase',phase=f'检查视频文件：{read/size:.0%}');last_notice=time.monotonic()
    return digest.hexdigest()


def refine_missing_lines(rows,path,meta,roi,pool,scale,workers=2):
    from line_refine import refine
    return refine(rows,path,meta,roi,pool,scale,workers)


def make_segments(rows):
    runs = []
    for row in rows:
        k = key(row['text'])
        if runs and runs[-1]['key'] == k:
            runs[-1]['rows'].append(row)
        else:
            runs.append({'key': k, 'rows': [row], 'flags': []})
    runs = _extend_volatile_to_observed_anchor(_compact_volatile_ocr_noise(
        _compact_recurrent_ocr_noise(_compact_bracketed_ocr_noise(
            _coalesce_equal_runs(_compact_ocr_flicker(_compact_identical_fragments(runs)))))))
    # Only identical observed text shares a cue. All OCR repairs must already
    # have been verified against that frame's image in the refinement stage.
    events = []
    for run in runs:
        if not run['key']:
            continue
        frames = run['rows']
        votes = Counter(row['text'] for row in frames)
        # Vote actual observed strings, never manufacture new words.
        eligible = Counter({text: n for text, n in votes.items() if key(text) == run['key']})
        text = eligible.most_common(1)[0][0]
        matching = [r for r in frames if r['text'] == text]
        start, end = frames[0]['start'], frames[-1]['end']
        best = min(matching, key=lambda r: (-r['confidence'], abs((start + end) / 2 - r['start'])))
        flags = set(run['flags'])
        if any(r.get('image_verified') for r in frames):
            flags.add('image_verified_repair')
        if any(r.get('fade_restored') for r in frames):
            flags.add('fading_frame_preserved')
        if any(r.get('line_recovered') for r in frames):
            flags.add('missing_line_recovered_check')
        confidence = sum(r['confidence'] for r in matching) / len(matching)
        if confidence < .8:
            flags.add('low_confidence')
        if end - start < .18:
            flags.add('very_short')
        if end - start > 12:
            flags.add('very_long')
        if len(key(text)) / max(.001, end - start) > 35:
            flags.add('high_reading_speed')
        if len(frames) < 3:
            flags.add('few_frames')
        if len(text.splitlines()) > 3:
            flags.add('many_lines')
        events.append({'id': len(events) + 1, 'start': start, 'end': end, 'text': text,
                       'confidence': round(confidence, 4), 'frames': len(frames),
                       'agreement': round(len(matching) / len(frames), 4),
                       'evidence_time': best['start'], 'first_frame': frames[0]['frame'],
                       'last_frame': frames[-1]['frame'], 'flags': sorted(flags),
                       'variants': dict(votes), 'reviewed': False})
        from subtitle_layout import observed_layout
        layout=observed_layout(matching)
        if layout:events[-1]['observed_layout']=layout
    for a, b in zip(events, events[1:]):
        similarity = SequenceMatcher(None, key(a['text']), key(b['text'])).ratio()
        if b['start'] - a['end'] < .3 and similarity > .8:
            for event in [a, b]:
                event['flags'] = sorted(set(event['flags'] + ['similar_neighbor_check']))
    return events


def exclude_off_band_graphics(events, calibration):
    """Reject large, displaced title graphics inside an otherwise stable ROI.

    A manual rectangle can contain both the dialogue line and later end-card
    lettering. The learned dialogue font and band are image observations, not
    language-specific words. Without a stable calibration, preserve every cue.
    """
    candidates=calibration.get('candidates') or []
    baseline=candidates[0] if candidates else {}
    font=calibration.get('font_height') or 0
    band=baseline.get('roi') or []
    roi=calibration.get('roi') or []
    if (font<=0 or len(roi)!=4 or len(band)!=4 or
            baseline.get('coverage',0)<4 or baseline.get('unique',0)<3):
        return events,[]
    center=(band[1]+band[3])/2
    kept=[];excluded=[]
    for event in events:
        layout=event.get('observed_layout') or {}
        glyph=layout.get('glyph_height')
        bottom=layout.get('bottom_y')
        if not glyph or bottom is None:
            kept.append(event);continue
        height=glyph*(roi[3]-roi[1])
        cy=roi[1]+(bottom-glyph/2)*(roi[3]-roi[1])
        oversized=height>font*1.55
        shifted=(height>font*1.25 and abs(cy-center)>max(.035,font*.75))
        (excluded if oversized or shifted else kept).append(event)
    for index,event in enumerate(kept,1):event['id']=index
    return kept,excluded


def stamp(value, ass=False):
    scale = 100 if ass else 1000
    n = max(0, int(value * scale + .5))
    seconds, fraction = divmod(n, scale)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return (f'{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}' if ass
            else f'{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}')


def ass_text(text):
    # Full-width substitutions safely prevent untrusted OCR from becoming ASS tags.
    return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', '\\N')


def validate(events, duration):
    previous_end = 0
    for e in events:
        if not isinstance(e['text'], str) or not normalize(e['text']):
            raise ValueError(f'空字幕：{e["id"]}')
        if not (0 <= e['start'] < e['end'] <= duration + .001):
            raise ValueError(f'字幕时间越界：{e["id"]}')
        if e['start'] < previous_end - .0001:
            raise ValueError(f'字幕重叠：{e["id"]}')
        for scale in [100, 1000]:
            if int(e['end'] * scale + .5) <= int(e['start'] * scale + .5):
                raise ValueError(f'字幕过短，量化后零时长：{e["id"]}')
        previous_end = e['end']


def selected_formats(value='both'):
    if value not in ('srt','ass','both'):
        raise ValueError('字幕格式必须为 srt、ass 或 both')
    return ('srt','ass') if value=='both' else (value,)


def select_scale(requested, video_width, engine, languages):
    """Choose the OCR input size once per episode, independent of speed mode."""
    if requested:return requested
    if engine=='vision' and languages==['th-TH']:
        # On a real 544 px Thai drama, 2x repeatedly omitted a visible upper
        # line while native-size Vision read it, and scanned 34% slower.
        return 1
    return 1 if video_width>=960 else 2


def export_files(document, stem, backup=False, format='both'):
    formats=selected_formats(format)
    events, meta = document['events'], document['video']
    validate(events, meta['duration'])
    srt = '\n\n'.join(f'{i}\n{stamp(e["start"])} --> {stamp(e["end"])}\n{normalize(e["text"])}'
                      for i, e in enumerate(events, 1)) + '\n'
    w, h = meta['width'], meta['height']
    font = max(18, round(h * (document.get('calibration',{}).get('font_height') or .034)))
    ass = f'''[Script Info]
Title: Extracted subtitles
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,{round(h*.06)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    from subtitle_layout import ass_placement
    ass += '\n'.join(f'Dialogue: 0,{stamp(e["start"],True)},{stamp(e["end"],True)},Default,,0,0,0,,{ass_placement(e,document)}{ass_text(normalize(e["text"]))}' for e in events) + '\n'
    from safe_export import write_pair
    contents={'srt':srt,'ass':ass}
    write_pair({Path(str(stem)+'.'+ext):contents[ext] for ext in formats},backup=backup)


def evidence_and_report(document, source, stem, roi, pool, scale):
    from PIL import Image, ImageDraw
    assets = Path(str(stem) + '.review')
    assets.mkdir(exist_ok=True)
    cards = []
    contact = []
    for e in document['events']:
        control.check()
        image = image_crop(frame_at(source, document['video'], e['evidence_time']), roi, scale)
        name = f'{e["id"]:04d}.jpg'
        image.save(assets / name, quality=95)
        # Second pass changes preprocessing and enables the language model ONLY
        # as a cross-check. It cannot silently replace the primary transcription.
        alternate, conf = read_lines(pool.recognize(image, correction=True))
        e['language_check'] = alternate
        if key(alternate) != key(e['text']):
            e['flags'] = sorted(set(e['flags'] + ['language_check_disagreement']))
        # A different rasterization exposes OCR sensitivity. Agreement of two
        # settings of the same engine is NOT independent-engine verification.
        jpeg_image = Image.open(assets / name)
        raster_check, _ = read_lines(pool.recognize(jpeg_image))
        e['raster_check'] = raster_check
        if key(raster_check) != key(e['text']):
            e['flags'] = sorted(set(e['flags'] + ['raster_check_disagreement']))
        if len(key(e['text'])) >= 15 and e['text'].isupper():
            e['flags'] = sorted(set(e['flags'] + ['all_caps_check']))
        e['evidence'] = f'{assets.name}/{name}'
        tile = Image.new('RGB', (600, 150), 'white')
        thumb = image.copy()
        thumb.thumbnail((580, 105))
        tile.paste(thumb, ((600-thumb.width)//2, 25))
        ImageDraw.Draw(tile).text((8, 6), f'{e["id"]:03d} | {e["start"]:.3f} - {e["end"]:.3f}', fill='black')
        contact.append(tile)
        flags = ', '.join(e['flags']) or '自动检查未发现异常；不等于人工确认'
        cards.append(f'<article><b>#{e["id"]}　{stamp(e["start"])} → {stamp(e["end"])}</b>'
                     f'<p>{html.escape(flags)}</p><img loading="lazy" src="{html.escape(e["evidence"],quote=True)}">'
                     f'<pre>{html.escape(e["text"])}</pre><small>跨帧一致比例 {e["agreement"]:.1%}；'
                     f'OCR 分数 {e["confidence"]:.3f}（不是准确率）</small></article>')
    for page_start in range(0, len(contact), 20):
        group = contact[page_start:page_start+20]
        sheet = Image.new('RGB', (1200, ((len(group)+1)//2)*150), '#ddd')
        for i, tile in enumerate(group):
            sheet.paste(tile, ((i % 2)*600, (i//2)*150))
        sheet.save(assets / f'contact-{page_start//20+1:02d}.jpg', quality=92)
    flagged = sum(bool(e['flags']) for e in document['events'])
    report = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>EllaPuede · 字幕复核报告</title><style>body{{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;background:#f5f5f5;color:#222}}article{{background:white;padding:20px;margin:18px 0;border:1px solid #ddd;border-radius:8px}}img{{max-width:100%;height:auto}}pre{{white-space:pre-wrap;font:20px system-ui}}small{{color:#555}}</style>
<h1>EllaPuede · 字幕复核报告</h1><p>{html.escape(source.name)} · {len(document['events'])} 条字幕 · {flagged} 条需重点复核</p>
<p>逐帧 OCR，按原始显示时间戳定位。只识别配置区域内的可见文字。高分不保证无错漏。起止时间和字幕移动仍需抽查原视频。</p>
<p>修改同名 .subtitles.json 的 events 内容后，用 export 子命令重新导出。此页面是识别时的证据快照。</p>
{''.join(cards)}</html>'''
    atomic_text(str(stem) + '.review.html', report)


def write_diagnostics(document,stem):
    items=[]
    for event in document['events']:
        if event.get('flags'):
            items.append('<tr><td>'+str(event['id'])+'</td><td>'+stamp(event['start'])+' → '+stamp(event['end'])+
                         '</td><td>'+html.escape(event['text']).replace('\n','<br>')+'</td><td>'+html.escape(', '.join(event['flags']))+'</td></tr>')
    report='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>EllaPuede 识别报告</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;color:#24312e}td,th{padding:12px;text-align:left;border-bottom:1px solid #ddd}table{border-collapse:collapse;width:100%}</style>'
    report+='<h1>EllaPuede · 识别报告</h1><p>'+html.escape(Path(document['source']).name)+'</p>'
    report+=f'<p>{len(document["events"])} 条字幕已自动导出。此报告仅记录识别疑点，不影响 SRT / ASS 使用；如需修改，可使用外部字幕编辑器。</p>'
    report+='<table><tr><th>序号</th><th>时间</th><th>字幕</th><th>诊断标记</th></tr>'+''.join(items)+'</table></html>'
    atomic_text(str(stem)+'.report.html',report)


def resolve_series_region(path,meta,pool,cache,args):
    series_file=getattr(args,'series_file',None)
    aspect=meta['width']/max(1,meta['height'])
    previous={}
    if series_file and series_file.exists():
        previous=json.loads(series_file.read_text(encoding='utf-8'))
    if args.roi:
        same=(previous.get('roi')==list(args.roi) and abs(aspect/previous.get('aspect',aspect)-1)<=.05)
        result=dict(previous,roi=list(args.roi),automatic=False,aspect=aspect) if same else {'roi':list(args.roi),'automatic':False,'aspect':aspect}
    elif previous and (not previous.get('automatic',False) or previous.get('region_revision')==2):
        result=json.loads(series_file.read_text(encoding='utf-8'))
        roi_arg(','.join(map(str,result['roi'])))
        if abs(aspect/result['aspect']-1)>.05:
            raise ValueError('本集画幅与共用区域的首集不同，请单独设置区域；没有扩大识别范围。')
        control.emit('phase',phase='复用本剧对白区域')
        return result
    else:
        result=calibrate(path,meta,pool,cache,None);result['aspect']=aspect;result['region_revision']=2
    if series_file:
        series_file.parent.mkdir(parents=True,exist_ok=True);save_json(series_file,dict(result,source=str(path)))
    return result


def prepare_manual_region(path,meta,pool,cache,args,calibration):
    """Learn sizes once inside a manual rectangle without moving its borders."""
    if calibration.get('automatic') or calibration.get('font_calibrated'):return calibration
    learned=calibrate(path,meta,pool,cache,tuple(calibration['roi']))
    result=dict(calibration,font_height=learned.get('font_height'),
                mask_density=learned.get('mask_density'),candidates=learned.get('candidates',[]),font_calibrated=True)
    if not result['font_height']:control.emit('warning',message='手动区域内未找到稳定字号；已保留完整框选范围，请用“识别当前框内文字”检查小字是否混入。')
    if getattr(args,'series_file',None):save_json(args.series_file,result)
    return result


def private_result_stem(path,export_stem,args):
    root=getattr(args,'cache_root',None) or args.output/'.ellapuede-cache'
    key=hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
    return root/'results'/key/Path(export_stem).name


def matching_calibration(cached,current):
    return all(cached.get(k)==current.get(k) for k in ('roi','font_height','mask_density','aspect','region_revision','font_calibrated'))


def run_one(path, stem, args, pool):
    pipeline_started=time.monotonic()
    control.emit('phase',phase='检查视频与缓存',source=str(path))
    meta = getattr(args,'video_meta',None) or probe(path)
    stat = path.stat()
    fingerprint = source_fingerprint(path)
    region_cache=(getattr(args,'cache_root',None) or args.output/'.ellapuede-cache')/'region-work'/fingerprint[:24]
    region_cache.mkdir(parents=True,exist_ok=True)
    control.emit('phase',phase='准备本剧对白区域')
    if 'auto' in getattr(pool,'languages',[]):
        from language_detection import resolve_language
        resolve_language(path,meta,args.roi,pool,getattr(args,'series_file',None))
    effective_languages=list(getattr(pool, 'languages', args.language))
    if effective_languages == ['auto'] and getattr(pool, 'last_detected_language', None):
        effective_languages=[pool.last_detected_language]
    if 'auto' not in args.language and effective_languages!=list(args.language):
        raise RuntimeError('识别引擎的实际语言与手动指定语言不一致，已停止以避免导出错误字幕。')
    control.emit('language', requested=list(args.language),
                 resolved=effective_languages,
                 detected=getattr(pool, 'last_detected_language', None))
    pool.dialogue_min_height=0;pool.dialogue_max_height=0;pool.dialogue_min_mask_density=0
    calibration=resolve_series_region(path,meta,pool,region_cache,args)
    calibration=prepare_manual_region(path,meta,pool,region_cache,args,calibration)
    font_height=(calibration.get('font_height') or 0)*meta['height']
    korean='ko-KR' in getattr(pool,'languages',[])
    pool.dialogue_min_height=font_height*(.65 if korean else .45)
    pool.dialogue_max_height=font_height*1.8 if korean else 0
    # Enable this only for a learned, strongly outlined dialogue style. Plain
    # subtitles have no reliable light-on-dark mask and retain height-only OCR.
    baseline=calibration.get('mask_density') or 0
    pool.dialogue_min_mask_density=max(.02,baseline*.2) if baseline>=.08 else 0
    effective_languages=list(getattr(pool,'languages',args.language))
    if effective_languages == ['auto'] and getattr(pool,'last_detected_language',None):
        effective_languages=[pool.last_detected_language]
    if 'auto' not in args.language and effective_languages!=list(args.language):
        raise RuntimeError('识别引擎在处理时切换了手动指定的语言，已停止以避免导出错误字幕。')
    config = {'dialogue_max_height':pool.dialogue_max_height,'dialogue_min_height':pool.dialogue_min_height,
              'dialogue_min_mask_density':pool.dialogue_min_mask_density,'effective_roi':calibration['roi'],'version': OCR_CACHE_REVISION, 'roi': args.roi, 'languages': args.language,'effective_languages':effective_languages,
              'strategy':getattr(args,'strategy','accurate'),'scale': args.scale, 'words': pool.words, 'engine': pool.name,'engine_route':getattr(args,'engine',None),
              'engine_source': hashlib.sha256((OCR_CACHE_REVISION+pool.name).encode()).hexdigest(),
              'macos': __import__('platform').mac_ver()[0]}
    job_id = hashlib.sha256(json.dumps([fingerprint, config], sort_keys=True).encode()).hexdigest()[:24]
    cache = (getattr(args,'cache_root',None) or args.output/'.ellapuede-cache') / 'frames' / job_id
    cache.mkdir(parents=True, exist_ok=True)
    save_json(cache / 'job.json', {'source': str(path), 'sha256': fingerprint, 'config': config})
    calibration_file = cache / 'calibration.json'
    save_json(calibration_file,calibration)
    roi = tuple(calibration['roi'])
    print(f'  字幕区域 {",".join(f"{x:.4f}" for x in roi)}；{getattr(args,'strategy','accurate')}；并发 {args.workers}', flush=True)
    stem.parent.mkdir(parents=True, exist_ok=True)
    control.emit('region',roi=list(roi),automatic=calibration.get('automatic',args.roi is None))
    control.emit('phase',phase='逐帧识别')
    from temporal_scan import scan_frames as verified_scan
    rows, perf = verified_scan(path, meta, roi, pool, cache, args.workers, args.scale)
    from dialogue_filter import restore_connected_fades
    perf['fading_frames_restored']=restore_connected_fades(rows)
    print('  整理字幕并自动导出…', flush=True)
    control.emit('phase',phase='整理字幕并自动导出')
    refine_started=time.monotonic()
    recovered = refine_missing_lines(rows,path,meta,roi,pool,args.scale,args.workers)
    perf['line_check_seconds']=round(time.monotonic()-refine_started,2)
    refine_started=time.monotonic()
    from quality_refine import refine
    perf['image_verified_repairs']=refine(rows,path,meta,roi,pool,args.scale,args.workers)
    perf['quality_check_seconds']=round(time.monotonic()-refine_started,2)
    refine_started=time.monotonic()
    from visual_consensus import refine as refine_visual_consensus, refine_recurrent_variant
    perf['visual_consensus_repairs']=refine_visual_consensus(rows,path,meta,roi,pool)
    perf['recurrent_glyph_repairs']=refine_recurrent_variant(rows,path,meta,roi,pool)
    perf['visual_consensus_seconds']=round(time.monotonic()-refine_started,2)
    events,excluded_layout_events=exclude_off_band_graphics(make_segments(rows),calibration)
    if not events:
        raise ValueError('没有识别出字幕，缓存已保留；请检查区域和语言')
    document = {'tool_version': VERSION, 'source': str(path), 'source_sha256': fingerprint,
                'source_bytes': stat.st_size, 'video': meta, 'episode': episode_info(path.stem),
                'config': config, 'calibration': calibration, 'performance': perf,
                'resolved_languages':effective_languages,'backend':getattr(pool,'last_backend',pool.name),
                'status': 'automatic_exported', 'recovered_line_frames': recovered,
                'events': events,
                'excluded_layout_events': [{'start':e['start'],'end':e['end'],'text':e['text']}
                                           for e in excluded_layout_events]}
    validate(events, meta['duration'])
    export_stem=getattr(args,'subtitle_stem',None) or stem
    document['export_stem']=str(export_stem)
    # Deliver subtitle files first. Diagnostics are never an approval gate.
    document['export_formats']=list(selected_formats(getattr(args,'format','both')))
    export_files(document, export_stem,backup=args.overwrite,format=getattr(args,'format','both'))
    document['warnings']=list(getattr(pool,'optional_warnings',{}).values())
    # The counterfactual cluster comparison is a developer diagnostic, not a
    # second processing pass or a reason to ask users to review every cue.
    # Generate it only with an explicitly requested evidence report.
    if getattr(args,'evidence_report',False):
        try:
            from segmentation_diagnostics import analyze
            diagnostic_started=time.monotonic()
            document['segmentation_diagnostics']=analyze(rows,events,perf)
            perf['segmentation_diagnostic_seconds']=round(time.monotonic()-diagnostic_started,3)
        except Exception as error:
            control.emit('warning',message=f'字幕已导出，分段对照记录未生成：{error}')
    for warning in document['warnings']:control.emit('warning',message=warning)
    if getattr(args,'evidence_report',False):
        try:evidence_and_report(document,path,stem,roi,pool,args.scale)
        except Exception as error:
            control.emit('warning',message=f'字幕已导出，附加图像报告未生成：{error}')
    document['performance']['pipeline_seconds']=round(time.monotonic()-pipeline_started,2)
    if control.CONTROL:document['performance']['peak_process_tree_mb']=round(control.CONTROL.peak_mb)
    try:
        save_json(str(stem)+'.subtitles.json',document)
        if getattr(args,'evidence_report',False):write_diagnostics(document,stem)
    except Exception as error:
        control.emit('warning',message=f'字幕已导出，识别记录未完整保存：{error}')
    flagged = sum(bool(e['flags']) for e in events)
    flag_counts=dict(Counter(flag for event in events for flag in event['flags']))
    print(f'  完成：{len(events)} 条，{" / ".join(document["export_formats"]).upper()} 已自动导出。', flush=True)
    control.emit('result',stem=str(stem),export_stem=str(export_stem),events=len(events),flagged=flagged,
                 performance=document['performance'],backend=document['backend'],flag_counts=flag_counts,
                 resolved_languages=list(document['resolved_languages']))
    return {'source': str(path), 'output_stem': str(stem), 'source_sha256': fingerprint,
            'episode': document['episode'], 'status': 'completed_exported',
            'events': len(events), 'flagged': flagged, 'performance': perf}


def main(argv=None,pool_cache=None):
    parser = argparse.ArgumentParser(description='视频画面字幕 OCR：本地逐帧识别，批量导出 SRT / ASS')
    parser.add_argument('--version',action='version',version=f'EllaPuede {RELEASE_VERSION}')
    subs = parser.add_subparsers(dest='command', required=True)
    extract = subs.add_parser('extract', help='处理一个视频或整个文件夹（递归）')
    extract.add_argument('input', type=Path)
    extract.add_argument('-o', '--output', type=Path, required=True)
    extract.add_argument('--roi', type=roi_arg, help='字幕区域 x1,y1,x2,y2，左上原点，0–1；默认自动校准')
    extract.add_argument('--language', default='auto', help='识别语言代码，逗号分隔；不执行翻译')
    extract.add_argument('--strategy',choices=['accurate'],default='accurate',help=argparse.SUPPRESS)
    extract.add_argument('--workers', type=int, choices=range(1,9), default=2)
    extract.add_argument('--scale', type=float, default=0, help='OCR 放大倍数：0 自动（按语言和平台选取），或 1–4')
    extract.add_argument('--words', type=Path, help='UTF-8 词表，每行一个专名，仅作为 OCR 提示')
    extract.add_argument('--overwrite', action='store_true', help='允许覆盖当前输出（OCR 帧缓存仍复用）')
    extract.add_argument('--engine',choices=['auto','vision','rapid'],default='auto')
    extract.add_argument('--device',choices=['auto','cpu','gpu'],default='auto',help='ONNX 计算设备；不改变 OCR 语言模型。GPU 仅在支持 DirectML 的 Windows 上启用')
    extract.add_argument('--threads',type=int,choices=range(1,9),default=2,help='每个 ONNX 进程的计算线程数')
    extract.add_argument('--memory-gb',type=float,default=4,help='进程树内存软阈值（GB），超出后保留进度并停止')
    extract.add_argument('--evidence-report',action='store_true',help='附加图像诊断报告（可选，不影响字幕导出）')
    extract.add_argument('--format',choices=['srt','ass','both'],default='both',help='导出格式，默认两种都导出')
    extract.add_argument('--organize-output',action='store_true',help=argparse.SUPPRESS)
    extract.add_argument('--cache-root',type=Path,help=argparse.SUPPRESS)
    extract.add_argument('--series-file',type=Path,help=argparse.SUPPRESS)
    extract.add_argument('--control-dir',type=Path,help=argparse.SUPPRESS)
    export = subs.add_parser('export', help='从已复核的 subtitles.json 重新生成字幕')
    export.add_argument('json_file', type=Path)
    export.add_argument('--stem', type=Path, help='自定义输出路径主体；默认与视频文件名一致')
    export.add_argument('--format',choices=['srt','ass','both'],default='both')
    export.add_argument('--overwrite',action='store_true',help='备份并替换已有同名字幕')
    args = parser.parse_args(argv)
    if args.command == 'export':
        doc = json.loads(args.json_file.read_text(encoding='utf-8'))
        stem = args.stem or (Path(doc['export_stem']) if doc.get('export_stem') else aligned_stem(args.json_file.parent,doc['source']))
        stem.parent.mkdir(parents=True,exist_ok=True)
        if not args.overwrite and any(Path(str(stem)+x).exists() for x in ('.'+ext for ext in selected_formats(args.format))):
            parser.error('同名字幕已存在；使用 --overwrite 备份并替换，或用 --stem 选择其他目录')
        export_files(doc, stem,backup=True,format=args.format)
        print(f'已导出 {stem}：{args.format}')
        return 0
    if args.scale!=0 and not 1 <= args.scale <= 4:
        parser.error('--scale 必须在 1–4 之间')
    args.input = args.input.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.cache_root:args.cache_root=args.cache_root.expanduser().resolve();args.cache_root.mkdir(parents=True,exist_ok=True)
    if not args.series_file and args.input.is_dir():
        root=args.cache_root or args.output/'.ellapuede-cache'
        args.series_file=root/'series'/(hashlib.sha256(str(args.input).encode()).hexdigest()+'.json')
    output_lock=control.OutputLock(args.output)
    control.CONTROL=control.Controller(args.control_dir,args.memory_gb,args.output,cache=args.cache_root)
    if args.engine=='vision' and sys.platform!='darwin':parser.error('Apple Vision 仅适用于 macOS')
    from hardware_policy import resolve_engine
    args.engine=resolve_engine(args.engine,args.language)
    args.language = [x.strip() for x in args.language.split(',') if x.strip()]
    from hardware_policy import validate_languages
    try: validate_languages(args.language)
    except ValueError as error: parser.error(str(error))
    files = ([args.input] if args.input.is_file() else
             sorted((p for p in args.input.rglob('*') if p.is_file() and p.suffix.lower() in VIDEO_EXTS), key=natural_key))
    if not files:
        parser.error('没有找到视频文件')
    if args.input.is_file() and args.input.suffix.lower() not in VIDEO_EXTS:
        parser.error('输入扩展名不受支持')
    words = args.words.read_text(encoding='utf-8').splitlines() if args.words else []
    manifest = {'version': VERSION, 'input': str(args.input), 'jobs': [], 'warnings': []}
    episodes = Counter((episode_info(p.stem)['season'], episode_info(p.stem)['episode']) for p in files)
    manifest['warnings'] = [f'重复集数标记（可能为不同版本或不同子目录）：{e}' for e,n in episodes.items() if n > 1 and e[1] is not None]
    identified = sorted({e[1] for e in episodes if e[1] is not None})
    if identified:
        missing = sorted(set(range(min(identified), max(identified)+1)) - set(identified))
        if missing:
            manifest['warnings'].append(f'集数序列存在空缺（跨季时需人工核对）：{missing}')
    for warning in manifest['warnings']:control.emit('warning',message=warning)
    control.emit('phase',phase='准备离线识别组件；首次启动可能需要较长时间')
    pool_key=(args.engine,tuple(args.language),tuple(words),args.threads,args.device,str(args.series_file) if 'auto' in args.language else None)
    if pool_cache is not None and pool_cache.get('key')!=pool_key:
        if pool_cache.get('pool'):pool_cache['pool'].close()
        pool_cache.clear()
    pool=pool_cache.get('pool') if pool_cache else None
    if pool is None:pool=VisionPool(args.language, words) if args.engine=='vision' else RapidPool(args.language,words,args.threads,args.device)
    if pool_cache is not None:pool_cache.update(key=pool_key,pool=pool)
    relative=[Path(p.name) if args.input.is_file() else p.relative_to(args.input) for p in files]
    planned=output_stems(zip(files,relative),args.output)
    requested_scale=args.scale
    try:
        for i, path in enumerate(files, 1):
            rel = Path(path.name) if args.input.is_file() else path.relative_to(args.input)
            export_stem = planned[i-1]
            args.subtitle_stem=export_stem
            stem = private_result_stem(path,export_stem,args)
            print(f'[{i}/{len(files)}] {rel}', flush=True)
            control.emit('file',index=i,total=len(files),source=str(path))
            try:
                args.video_meta=probe(path)
                args.scale=select_scale(requested_scale,args.video_meta['width'],args.engine,args.language)
                json_file = Path(str(stem)+'.subtitles.json')
                existing = any(Path(str(export_stem)+s).exists() for s in ('.'+ext for ext in selected_formats(args.format)))
                if (existing or json_file.exists()) and not args.overwrite:
                    if not json_file.exists():
                        raise ValueError('输出已存在，未覆盖；请换输出目录或显式 --overwrite')
                    doc = json.loads(json_file.read_text(encoding='utf-8'))
                    if (doc.get('source_sha256') == source_fingerprint(path)
                            and doc.get('config',{}).get('roi') == (list(args.roi) if args.roi else None)
                            and (not args.series_file or not args.series_file.exists() or matching_calibration(doc.get('calibration',{}),json.loads(args.series_file.read_text(encoding='utf-8'))))
                            and doc.get('config',{}).get('languages') == args.language
                            and doc.get('config',{}).get('scale') == args.scale
                            and doc.get('config',{}).get('strategy','accurate') == args.strategy
                            and doc.get('config',{}).get('words') == words
                            and doc.get('config',{}).get('engine_route') == args.engine
                            and doc.get('tool_version') == VERSION):
                        for ext in selected_formats(args.format):
                            if not Path(str(export_stem)+'.'+ext).exists():
                                export_files(doc,export_stem,format=ext)
                        manifest['jobs'].append({'source':str(path),'output_stem':str(stem),'status':'skipped_existing'})
                        print('  输入和识别配置一致，已准备所选格式，无需重复 OCR。',flush=True)
                        for warning in doc.get('warnings',[]):control.emit('warning',message=warning)
                        control.emit('result',stem=str(stem),export_stem=str(export_stem),events=len(doc['events']),flagged=sum(bool(e['flags']) for e in doc['events']),cached=True,resolved_languages=doc.get('resolved_languages',[]),backend=doc.get('backend',''),flag_counts=dict(Counter(flag for event in doc['events'] for flag in event['flags'])))
                        continue
                    raise ValueError('输出对应的输入或配置已变化；请换目录或显式 --overwrite')
                manifest['jobs'].append(run_one(path, stem, args, pool))
            except control.Cancelled:
                manifest['jobs'].append({'source':str(path),'status':'interrupted'})
                raise
            except Exception as error:
                print(f'  失败：{error}', file=sys.stderr, flush=True)
                manifest['jobs'].append({'source': str(path), 'status': 'failed', 'error': str(error)})
                from friendly_errors import describe
                from language_detection import LanguageUndetermined
                control.emit('error',message=describe(error),action='choose_language' if isinstance(error,LanguageUndetermined) else None)
            finally:
                save_json((args.cache_root or args.output/'.ellapuede-cache')/'manifest.json', manifest)
    except (KeyboardInterrupt,control.Cancelled):
        print('\n已中断；帧缓存已保留，再次运行同一命令即可继续。', file=sys.stderr)
        return 130
    finally:
        if pool_cache is None:pool.close()
        output_lock.close()
    return 1 if any(x['status']=='failed' for x in manifest['jobs']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
