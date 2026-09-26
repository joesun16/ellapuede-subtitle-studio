"""Experimental text clustering, NEVER used to choose exported cues.

This is a counterfactual, not an accuracy score. Similar captions (numbers,
negations, short interruptions) can be genuine changes; retain their evidence.
"""
from collections import Counter
from difflib import SequenceMatcher
from statistics import median


def cue_metrics(events):
    durations = [e['end'] - e['start'] for e in events]
    short = sum(d < .2 - 1e-9 for d in durations)
    return {'cues': len(events), 'under_200ms': short,
            'under_200ms_ratio': short / len(events) if events else 0,
            'median_seconds': median(durations) if durations else 0}


def shadow_segments(rows, threshold=.85, blank_gap=.12):
    from subtitle_ocr import key
    if not 0 < threshold <= 1 or blank_gap < 0:
        raise ValueError('Invalid clustering parameters')
    events = []
    cluster = None

    def finish():
        if cluster is None:
            return
        variants = cluster['variants']
        text, count = variants.most_common(1)[0]
        events.append({'start': cluster['start'], 'end': cluster['end'],
                       'text': text, 'first_frame': cluster['first_frame'],
                       'last_frame': cluster['last_frame'],
                       'frames': sum(variants.values()), 'variants': dict(variants),
                       'agreement': count / sum(variants.values()),
                       'merged_different_readings': len(cluster['keys']) > 1})

    for row in rows:
        text = row['text']
        k = key(text)
        if not k:
            continue
        if (cluster is not None and
                (row['start'] - cluster['end'] > blank_gap + 1e-9 or
                 (k != cluster['dominant'] and
                  SequenceMatcher(None, cluster['dominant'], k, autojunk=False).ratio() < threshold))):
            finish()
            cluster = None
        if cluster is None:
            cluster = {'start': row['start'], 'first_frame': row['frame'],
                       'dominant': k, 'keys': Counter(), 'variants': Counter()}
        cluster['end'] = row['end']
        cluster['last_frame'] = row['frame']
        cluster['keys'][k] += 1
        cluster['variants'][text] += 1
        if cluster['keys'][k] > cluster['keys'][cluster['dominant']]:
            cluster['dominant'] = k
    finish()
    return events


def analyze(rows, exported, performance, stage='after_image_refinement'):
    candidates = shadow_segments(rows)
    current = cue_metrics(exported)
    candidate = cue_metrics(candidates)
    warnings = []
    # Compare only newly processed rows on resumed jobs, not all decoded frames.
    denominator = performance.get('new_frame_rows',
                                  performance.get('decoded_frames', 0) - performance.get('cache_frames', 0))
    ratio = performance.get('new_ocr_frames', 0) / denominator if denominator > 0 else None
    if ratio is not None and ratio > .95:
        warnings.append('本集主扫描接近逐帧调用 OCR，可复用画面较少；处理速度可能偏慢。')
    if current['under_200ms_ratio'] > .2:
        warnings.append('本集较多字幕短于 0.2 秒，存在碎片化风险；此提示不阻断自动导出。')
    return {'schema': 1, 'stage': stage, 'affects_export': False,
            'threshold': .85, 'blank_gap_seconds': .12,
            'current': current, 'candidate': candidate,
            'new_ocr_per_new_frame': ratio, 'warnings': warnings,
            'limitation': '旁路条数不代表准确率；可能合并真实换字、数字或否定词，未用于导出。',
            'candidate_events': candidates}
