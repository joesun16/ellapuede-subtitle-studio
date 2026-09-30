"""Compare SRT/ASS/JSON references without treating fewer cues as better OCR.

Reference media stays external. Whitespace/wrapping and Unicode NFC are the
only text normalizations: accents, punctuation, case and genuine words count.
Temporal matching is monotonic, one-to-one; split cues remain visible errors.
"""
import argparse
import json
import math
import re
import unicodedata
from pathlib import Path


def text_key(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def seconds(value):
    h, m, s = value.strip().replace(',', '.').split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def read_events(path):
    path = Path(path)
    data = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() == '.json':
        return json.loads(data)['events']
    events = []
    if path.suffix.lower() in ('.ass', '.ssa'):
        fields = None
        in_events = False
        for line in data.splitlines():
            if line.startswith('['):
                in_events = line.strip().lower() == '[events]'
            if not in_events:
                continue
            if line.startswith('Format:'):
                fields = [x.strip().lower() for x in line.split(':', 1)[1].split(',')]
            if line.startswith('Dialogue:'):
                if not fields:
                    raise ValueError('ASS events require a Format line')
                row = dict(zip(fields, line.split(':', 1)[1].lstrip().split(',', len(fields)-1)))
                text = re.sub(r'\{[^}]*\}', '', row['text'])
                text = text.replace('\\N', '\n').replace('\\n', '\n').replace('\\h', ' ')
                events.append(dict(start=seconds(row['start']), end=seconds(row['end']), text=text))
    else:
        for block in re.split(r'\n\s*\n', data.replace('\r\n', '\n').strip()):
            lines = block.splitlines()
            index = next((i for i, line in enumerate(lines) if '-->' in line), None)
            if index is None:
                continue
            left, right = lines[index].split('-->', 1)
            events.append(dict(start=seconds(left), end=seconds(right.strip().split()[0]),
                               text='\n'.join(lines[index+1:])))
    if not events:
        raise ValueError(f'No subtitle events: {path.name}')
    for e in events:
        if not all(math.isfinite(e[k]) for k in ('start', 'end')) or e['end'] < e['start']:
            raise ValueError('Invalid reference time')
    return sorted(events, key=lambda e: (e['start'], e['end']))


def distance(a, b):
    previous = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1]+1, previous[j]+1, previous[j-1]+(x != y)))
        previous = row
    return previous[-1]


def align(reference, output):
    """Time-constrained sequence alignment; never match a repeated line far away."""
    n, m = len(reference), len(output)
    costs = [[0.] * (m+1) for _ in range(n+1)]
    back = {}
    for i in range(1, n+1): costs[i][0] = i; back[i, 0] = (i-1, 0)
    for j in range(1, m+1): costs[0][j] = j; back[0, j] = (0, j-1)
    for i, a in enumerate(reference, 1):
        ak = text_key(a['text'])
        for j, b in enumerate(output, 1):
            bk = text_key(b['text'])
            overlap = min(a['end'], b['end']) - max(a['start'], b['start'])
            ratio = distance(ak, bk) / max(1, len(ak), len(bk))
            span = max(.05, a['end']-a['start'], b['end']-b['start'])
            match = ratio + .35 * (1-max(0, overlap)/span)
            if overlap <= 0 and (ratio > .25 or abs(a['start']-b['start']) > .75):
                match = 3.
            options = [(costs[i-1][j-1]+match, (i-1, j-1)),
                       (costs[i-1][j]+1, (i-1, j)), (costs[i][j-1]+1, (i, j-1))]
            costs[i][j], back[i, j] = min(options, key=lambda item: item[0])
    pairs = []; i, j = n, m
    while i or j:
        pi, pj = back[i, j]
        pairs.append((i-1 if pi < i else None, j-1 if pj < j else None))
        i, j = pi, pj
    return pairs[::-1]


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values)*fraction)-1)] if values else None


def evaluate(reference, output):
    details = []; errors = 0; boundaries = []; exact = 0; missing = 0; extra = 0
    for i, j in align(reference, output):
        a = reference[i] if i is not None else None
        b = output[j] if j is not None else None
        ak = text_key(a['text']) if a else ''; bk = text_key(b['text']) if b else ''
        edit = distance(ak, bk); errors += edit
        detail = dict(reference_index=i, output_index=j, reference=a, output=b, edits=edit)
        if a and b:
            detail.update(start_delta=round(b['start']-a['start'], 6), end_delta=round(b['end']-a['end'], 6))
            # Timing distribution on exact text only, explicitly report coverage.
            if ak == bk:
                exact += 1; boundaries.extend([abs(detail['start_delta']), abs(detail['end_delta'])])
        elif a: missing += 1
        else: extra += 1
        details.append(detail)
    repeated = []
    for j in range(1, len(output)):
        a, b = output[j-1:j+1]
        if text_key(a['text']) == text_key(b['text']) and -.01 <= b['start']-a['end'] <= .12:
            repeated.append(j)
    return dict(reference_cues=len(reference), output_cues=len(output), exact_cues=exact,
                unmatched_reference_cues=missing, unmatched_output_cues=extra,
                character_error_rate=round(errors/max(1,sum(len(text_key(a['text'])) for a in reference)),6),
                exact_boundary_count=len(boundaries), exact_boundary_p50=percentile(boundaries,.5),
                exact_boundary_p95=percentile(boundaries,.95), exact_boundary_max=max(boundaries,default=None),
                adjacent_repeat_indices=repeated,
                short_cues=sum(e['end']-e['start'] < .18 for e in output), details=details,
                caveat='Reference comparison, not automatic truth. Check burn-in differences, frame rate conversion and genuine repeated/short captions against video.')


def main():
    p=argparse.ArgumentParser();p.add_argument('reference',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    result=evaluate(read_events(a.reference),read_events(a.output))
    a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='details'},ensure_ascii=False,indent=2))

if __name__ == '__main__':main()
