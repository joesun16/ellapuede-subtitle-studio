"""Observed glyph placement for ASS, without claiming to recover a font face."""
import math
from statistics import median


def observed_layout(rows):
    observations = []
    for row in rows:
        lines = [line for line in row.get('ocr', {}).get('lines', [])
                 if line.get('candidates') and line['candidates'][0].get('confidence', 0) >= .5
                 and any(c.isalnum() for c in line['candidates'][0].get('text', ''))]
        boxes = [line.get('box', []) for line in lines]
        if not boxes or any(len(b) != 4 or not all(math.isfinite(v) for v in b) or b[2] <= 0 or b[3] <= 0 for b in boxes):
            continue
        left = min(b[0] for b in boxes)
        right = max(b[0] + b[2] for b in boxes)
        bottom = max(b[1] + b[3] for b in boxes)
        observations.append(((left + right) / 2, bottom, median(b[3] for b in boxes)))
    if not observations:
        return None
    return dict(zip(('center_x', 'bottom_y', 'glyph_height'),
                    (median(values) for values in zip(*observations))))


def ass_placement(event, document):
    layout = event.get('observed_layout')
    calibration = document.get('calibration', {})
    roi = calibration.get('ocr_roi') or calibration.get('roi')
    if not layout or not roi or len(roi) != 4:
        return ''  # Older result files retain the standard bottom style.
    values = [*roi, *(layout.get(k, float('nan')) for k in ('center_x', 'bottom_y', 'glyph_height'))]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return ''
    left, top, right, bottom = roi
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1 and layout['glyph_height'] > 0):
        return ''
    width, height = document['video']['width'], document['video']['height']
    x = round(min(1, max(0, left + layout['center_x'] * (right - left))) * width)
    y = round(min(1, max(0, top + layout['bottom_y'] * (bottom - top))) * height)
    font = max(1, min(height, round(layout['glyph_height'] * (bottom - top) * height)))
    # ASS uses font metrics, while OCR measures visible glyphs: size/position is
    # an approximation. The original typeface cannot be determined from OCR.
    return '{' + rf'\an2\pos({x},{y})\fs{font}' + '}'
