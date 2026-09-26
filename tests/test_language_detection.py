import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from language_detection import agrees,detect_korean,guess_language


class LanguageDetectionTests(unittest.TestCase):
    def test_script_hint_reports_common_subtitle_scripts(self):
        self.assertEqual(guess_language('좋은 날'), 'ko-KR')
        self.assertEqual(guess_language('こんにちは'), 'ja-JP')
        self.assertEqual(guess_language('你好世界'), 'zh-Hans')
        self.assertEqual(guess_language('This is what'), 'en-US')
    def test_independent_hangul_evidence_tolerates_small_ocr_error(self):
        self.assertTrue(agrees('안녀하세요!', '안녕하세요!', .97))
        self.assertTrue(agrees('좋은날', '좋은 날', .96))

    def test_latin_numbers_weak_or_disagreeing_results_do_not_select_korean(self):
        self.assertFalse(agrees('Hello', 'Hello', .99))
        self.assertFalse(agrees('1234', '1234', .99))
        self.assertFalse(agrees('좋은 날', '좋은 날', .7))
        self.assertFalse(agrees('좋은 날', '친구야', .99))

    def test_selection_requires_three_distinct_frames_and_is_reused(self):
        def result(text):return {'lines':[{'box':[0,0,1,1],'candidates':[{'text':text,'confidence':.99}]}]}
        for texts,expected in [(['좋은 날','친구야']*6,['auto']),(['좋은 날','친구야','안녕하세요!'],['ko-KR'])]:
            portable=Mock();portable.recognize.side_effect=[result(t) for t in texts]
            native=Mock();native._recognize_once.side_effect=[result(t) for t in texts]
            pool=SimpleNamespace(languages=['auto'])
            with patch('subtitle_ocr.RapidPool',return_value=portable) as create,patch('subtitle_ocr.VisionPool',return_value=native),patch('subtitle_ocr.frame_at',return_value=Image.new('RGB',(100,100))):
                detect_korean('sample',{'duration':120},None,pool)
                detect_korean('next_episode',{'duration':120},None,pool)
                self.assertEqual(pool.languages,expected)
                create.assert_called_once()
            portable.close.assert_called_once();native.close.assert_called_once()
