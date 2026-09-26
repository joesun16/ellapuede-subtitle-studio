import threading
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from subtitle_ocr import VisionPool, image_crop, read_lines


def result(text='', confidence=.99):
    return {'lines': [{'box': [.1, .2, .8, .5], 'candidates': [
        {'text': text, 'confidence': confidence}]}] if text else []}


class KoreanFallbackTests(unittest.TestCase):
    def pool(self):
        pool = object.__new__(VisionPool)
        pool.name = 'AppleVision-test'
        pool.languages = ['ko-KR']
        pool.lock = threading.Lock()
        return pool

    def test_existing_text_is_not_rewritten_by_another_engine(self):
        pool = self.pool()
        pool._recognize_once = Mock(return_value=result('좋은 날'))
        with patch('subtitle_ocr.RapidPool') as secondary:
            self.assertEqual(read_lines(pool.recognize(image_crop(Image.new('RGB', (100, 50)), (0, 0, 1, 1))))[0], '좋은 날')
            secondary.assert_not_called()

    def test_blank_without_glyph_evidence_does_not_trigger_secondary(self):
        pool = self.pool()
        pool._recognize_once = Mock(return_value=result())
        image = image_crop(Image.new('RGB', (100, 50)), (0, 0, 1, 1))
        with patch('subtitle_ocr.RapidPool') as secondary:
            self.assertFalse(read_lines(pool.recognize(image))[0])
            secondary.assert_not_called()

    def test_native_resolution_retry_recovers_current_image_before_secondary(self):
        pool = self.pool()
        pool._recognize_once = Mock(side_effect=[result(), result('오늘 좋아!')])
        image = image_crop(Image.new('RGB', (100, 50)), (0, 0, 1, 1), 2)
        with patch('korean_raster.prepare', return_value={}), patch('subtitle_ocr.RapidPool') as secondary:
            self.assertEqual(read_lines(pool.recognize(image))[0], '오늘 좋아!')
            self.assertEqual(pool._recognize_once.call_args.args[0].size, (100, 50))
            secondary.assert_not_called()

    def test_short_line_fallback_requires_hangul_and_high_confidence(self):
        for text, confidence, expected in [('아!', .96, '아!'), ('아!', .70, ''), ('R', .99, '')]:
            pool = self.pool()
            pool._recognize_once = Mock(return_value=result())
            image = image_crop(Image.new('RGB', (100, 50)), (0, 0, 1, 1), 1)
            with patch('korean_raster.prepare', return_value={}), patch('subtitle_ocr.RapidPool') as factory:
                factory.return_value.recognize.return_value = result(text, confidence)
                self.assertEqual(read_lines(pool.recognize(image))[0], expected)
