"""Read an existing frame cache without OCR or changes to subtitle exports."""
import _bootstrap  # noqa: F401
import argparse
import json
from pathlib import Path
import sqlite3
from subtitle_ocr import read_lines, make_segments, save_json
from segmentation_diagnostics import analyze, cue_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', required=True, type=Path)
    parser.add_argument('--result', type=Path, help='Optional final .subtitles.json for a separate comparison')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() in {args.frames.resolve(), args.result.resolve() if args.result else None}:
        parser.error('Output must not replace an input')
    with sqlite3.connect(args.frames.resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = []
        for frame, start, end, data in db.execute('SELECT idx,t,end,data FROM frames ORDER BY idx'):
            ocr = json.loads(data)
            text, confidence = read_lines(ocr)
            rows.append(dict(frame=frame, start=start, end=end, text=text, confidence=confidence, ocr=ocr))
    document = json.loads(args.result.read_text(encoding='utf-8')) if args.result else {}
    result = analyze(rows, make_segments(rows), {}, stage='raw_scan_cache_before_image_refinement')
    result['source_cache'] = str(args.frames.resolve())
    result['limitation'] += ' 此缓存不含后续图像修复，不能把候选条数与最终导出直接视为算法净改善。'
    if document:
        result['final_export_separate_stage'] = cue_metrics(document['events'])
    save_json(args.output, result)
    print(json.dumps({k:v for k,v in result.items() if k != 'candidate_events'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
