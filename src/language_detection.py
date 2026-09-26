"""Bounded script verification for automatic Korean on macOS.
Apple Vision's automatic language setting alone may not select Korean.
No image leaves this machine. Language selection never replaces subtitle text.
"""
from contextlib import ExitStack
from difflib import SequenceMatcher

class LanguageUndetermined(ValueError):
    pass


def language_cache_file(series_file):
    return series_file.with_suffix('.language.json') if series_file else None


def resolve_language(path,meta,roi,pool,series_file=None):
    """One controller votes before scanning; workers never select models mid-job."""
    import json
    from pathlib import Path
    import subtitle_ocr as core
    if 'auto' not in pool.languages:return list(pool.languages)
    if getattr(pool,'language_error',None):raise LanguageUndetermined(pool.language_error)
    cache=language_cache_file(series_file)
    context={'version':core.VERSION,'roi':list(roi) if roi else None,
             'backend':'vision' if pool.name.startswith('AppleVision') else 'rapid'}
    if cache and cache.exists():
        try:
            doc=json.loads(cache.read_text(encoding='utf-8'));source=Path(doc['source']);stat=source.stat()
            if doc['context']==context and doc['stamp']==[stat.st_size,stat.st_mtime_ns]:
                pool.reset_backend(languages=doc['languages']);pool.last_detected_language=doc['languages'][0]
                core.control.emit('phase',phase='复用本剧已确认的字幕语言')
                return list(pool.languages)
        except (OSError,ValueError,KeyError):pass
    core.control.emit('phase',phase='取样判断本剧字幕语言')
    votes={};korean_texts=set();chosen=None
    # Suppress the portable worker's legacy per-process auto selection.
    pool.auto_probe=True
    try:
        with ExitStack() as stack:
            from optional_ocr import OptionalOCR
            korean=OptionalOCR(pool,'自动语言的韩语交叉确认',lambda:core.RapidPool(['ko-KR'],[],1))
            stack.callback(korean.close)
            native_korean=None
            for i in range(12):
                core.control.check()
                image=core.image_crop(core.frame_at(path,meta,meta['duration']*(i+.5)/12),roi or (.02,.45,.98,.95),1)
                result=pool.recognize(image);text,score=core.read_lines(result);hint=guess_language(text)
                checked=korean.recognize(image)
                if checked is None:
                    # A missing script check can make Korean appear Latin. Do
                    # not silently commit the entire series to the wrong model.
                    pool.language_error='自动语言校验组件不可用，请在上方选择原语言后重试。'
                    raise LanguageUndetermined(pool.language_error)
                candidate,confidence=core.read_lines(checked)
                if agrees(candidate,candidate,confidence):
                    # Scores from different OCR models are not calibrated against
                    # one another. Confirm the script on this image instead.
                    if pool.name.startswith('AppleVision'):
                        if native_korean is None:
                            native_korean=core.VisionPool(['ko-KR'],[]);stack.callback(native_korean.close)
                        second,_=core.read_lines(native_korean._recognize_once(image))
                    else:
                        second,_=core.read_lines(korean.recognize(core.image_crop(image,(0,0,1,1),1.5)) or {'lines':[]})
                    if agrees(candidate,second,confidence):korean_texts.add(core.key(candidate))
                if hint and score>=.85:
                    votes.setdefault(hint,set()).add(core.key(text))
                if len(korean_texts)>=3:chosen=['ko-KR'];break
                ranked=sorted(((len(v),k) for k,v in votes.items()),reverse=True)
                if i>=3 and ranked and ranked[0][0]>=3 and ranked[0][1]!='ko-KR' and len(korean_texts)==0:
                    if len(ranked)==1 or ranked[0][0]>=ranked[1][0]+2:
                        chosen=[ranked[0][1]];break
    finally:pool.auto_probe=False
    if not chosen:
        pool.language_error='无法可靠判断本剧字幕语言，请在上方选择原语言后重试；不会用未确定的语言继续识别。'
        raise LanguageUndetermined(pool.language_error)
    pool.reset_backend(languages=chosen);pool.last_detected_language=chosen[0]
    if cache:
        stat=Path(path).stat();cache.parent.mkdir(parents=True,exist_ok=True)
        core.save_json(cache,{'context':context,'source':str(path),'stamp':[stat.st_size,stat.st_mtime_ns],'languages':chosen})
    return chosen


def guess_language(text):
    """Infer a displayable script language from OCR text without translation.

    This is a UI hint and model-routing aid, not a semantic language detector.
    Latin text is reported as English only as the default Latin OCR route;
    users can still choose Spanish/French/etc. explicitly for best accuracy.
    """
    text=''.join(ch for ch in (text or '') if ch.isalpha())
    if not text:return None
    if sum('가'<=ch<='힣' for ch in text)>=2:return 'ko-KR'
    if any('\u3040'<=ch<='\u30ff' for ch in text):return 'ja-JP'
    cjk=sum('\u3400'<=ch<='\u9fff' for ch in text)
    if cjk>=2:return 'zh-Hans'
    latin=sum(('a'<=ch.lower()<='z') for ch in text)
    if latin>=3 and latin/max(1,len(text))>=.8:return 'en-US'
    return None


def agrees(first, second, confidence):
    a=''.join(first.split());b=''.join(second.split())
    def hangul(text):
        letters=[c for c in text if c.isalpha()]
        count=sum('가'<=c<='힣' for c in letters)
        return count>=2 and count/max(1,len(letters))>=.8
    return confidence>=.85 and hangul(a) and hangul(b) and SequenceMatcher(None,a,b).ratio()>=.75


def detect_korean(path,meta,roi,pool):
    import subtitle_ocr as core
    if getattr(pool,'language_checked',False):return
    core.control.emit('phase',phase='自动判断字幕语言（含韩语）')
    votes=set()
    with ExitStack() as stack:
        from optional_ocr import OptionalOCR
        portable=OptionalOCR(pool,'韩语语言复核',lambda:core.RapidPool(['ko-KR'],[],1))
        stack.callback(portable.close)
        native=core.VisionPool(['ko-KR'],[]);stack.callback(native.close)
        for i in range(12):
            core.control.check()
            crop=core.image_crop(core.frame_at(path,meta,meta['duration']*(i+.5)/12),roi or (.02,.45,.98,.95),1)
            checked=portable.recognize(crop)
            if checked is None:break
            first,confidence=core.read_lines(checked)
            if confidence<.85 or not any('가'<=c<='힣' for c in first):continue
            # Native-only confirmation; no recursive use of the portable fallback.
            second,_=core.read_lines(native._recognize_once(crop))
            if agrees(first,second,confidence):votes.add(core.key(second))
            if len(votes)>=3:
                pool.languages=['ko-KR'];break
    pool.language_checked=True
