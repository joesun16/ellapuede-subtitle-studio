import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import subtitle_ocr as core
from optional_ocr import OptionalOCR
from segmentation_diagnostics import analyze, shadow_segments


def reading(text):
    return {'lines': [{'box': [.1, .25, .8, .5], 'candidates': [{'text': text, 'confidence': .99}]}]}


def rows_for(texts):
    return [dict(frame=i, start=10+i*.04, end=10+(i+1)*.04, text=text,
                 confidence=.99, ocr=reading(text)) for i, text in enumerate(texts)]


class AssessmentFollowupTests(unittest.TestCase):
    def test_shadow_never_changes_original_negations_numbers_or_pts(self):
        for pair in [('I can leave now', "I can't leave now"), ('Take 100 dollars', 'Take 900 dollars'), ('김민수', '김민수2')]:
            rows = rows_for([pair[0]]*8+[pair[1]]+[pair[0]]*8)
            before = copy.deepcopy(rows)
            events = core.make_segments(rows)
            report = analyze(rows, events, {})
            self.assertEqual(rows, before)
            self.assertEqual(events, core.make_segments(rows))
            self.assertEqual([e['text'] for e in events], [pair[0], pair[1], pair[0]])
            self.assertFalse(report['affects_export'])
            for e in report['candidate_events']:
                self.assertIn(e['text'], [pair[0], pair[1]])
                self.assertEqual(e['start'], rows[e['first_frame']]['start'])
                self.assertEqual(e['end'], rows[e['last_frame']]['end'])

    def test_shadow_can_hide_a_real_digit_change_so_it_is_not_an_accuracy_score(self):
        rows = rows_for(['Take 100 dollars']*8+['Take 900 dollars']+['Take 100 dollars']*8)
        candidates = shadow_segments(rows)
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]['merged_different_readings'])
        self.assertIn('Take 900 dollars', candidates[0]['variants'])

    def test_shadow_respects_blank_gap_and_keeps_one_frame_single_glyph(self):
        rows = rows_for(['아!']+['']*4+['아!','피','ㅍ'])
        self.assertEqual([e['text'] for e in shadow_segments(rows)], ['아!','아!','피','ㅍ'])
        self.assertEqual(shadow_segments([]), [])

    def test_resumed_scan_diagnostics_use_only_new_rows(self):
        report = analyze([], [], {'decoded_frames':10000, 'cache_frames':9900,
                                 'new_frame_rows':100, 'new_ocr_frames':99})
        self.assertEqual(report['new_ocr_per_new_frame'], .99)
        self.assertEqual(len(report['warnings']), 1)
        self.assertIsNone(analyze([],[],{'decoded_frames':100,'cache_frames':100})['new_ocr_per_new_frame'])

    def test_exact_gap_limit_is_not_lost_to_float_rounding(self):
        rows = rows_for(['피','','','','피'])
        self.assertEqual(len(core.make_segments(rows)), 1)
        self.assertEqual(len(core.make_segments(rows_for(['피','','','','','피']))), 2)

    def test_optional_failure_warns_once_and_does_not_retry_every_frame(self):
        owner = SimpleNamespace()
        secondary = Mock(); secondary.recognize.side_effect = BrokenPipeError('gone')
        factory = Mock(return_value=secondary)
        check = OptionalOCR(owner, '复核', factory)
        with patch('resource_control.emit') as emit:
            with ThreadPoolExecutor(max_workers=4) as executor:
                self.assertEqual(list(executor.map(check.recognize, [Image.new('RGB',(4,4))]*12)), [None]*12)
            self.assertEqual(emit.call_count, 1)
        self.assertTrue(owner.optional_warnings)
        factory.assert_called_once()
        check.close(); secondary.close.assert_called_once()

    def test_cancellation_and_memory_error_are_never_swallowed(self):
        from resource_control import Cancelled
        for error in (Cancelled('stop'), MemoryError('memory')):
            check = OptionalOCR(SimpleNamespace(), 'test', Mock(side_effect=error))
            with self.assertRaises(type(error)):check.recognize(None)

    def test_korean_optional_failure_retains_primary_result(self):
        import threading
        pool = object.__new__(core.VisionPool)
        pool.languages=['ko-KR']; pool.name='AppleVision'; pool.lock=threading.Lock()
        pool._recognize_once=Mock(return_value={'lines':[]})
        with patch('korean_raster.prepare',return_value={}), patch.object(core,'RapidPool',side_effect=ImportError('missing')):
            result=pool.recognize(core.image_crop(Image.new('RGB',(40,20)),(0,0,1,1),1))
        self.assertEqual(result, {'lines':[]})
        self.assertIn('韩语短行补识别', pool.optional_warnings)

    def test_english_secondary_failure_continues_primary_image_verification(self):
        from quality_refine import refine
        rows=rows_for(['hello']*8+['hello!']+['hello']*8)
        container=MagicMock();container.__enter__.return_value=container
        container.streams=[SimpleNamespace(codec_context=SimpleNamespace())]
        container.decode.return_value=iter(range(len(rows)))
        pool=SimpleNamespace(languages=['en-US'],name='AppleVision')
        with patch('av.open',return_value=container), patch.object(core,'oriented_image',return_value=Image.new('RGB',(80,30))), patch.object(core,'RapidPool',side_effect=ImportError('missing')), patch('quality_refine.retry_image',return_value=('hello',.99)):
            self.assertEqual(refine(rows,'test',{'stream_index':0},(0,0,1,1),pool,1,1),1)
        self.assertTrue(all(row['text']=='hello' for row in rows))

    def test_english_scale_two_does_not_repeat_identical_secondary_crop(self):
        from quality_refine import refine
        rows=rows_for(['hello']*8+['hello!']+['hello']*8)
        container=MagicMock();container.__enter__.return_value=container
        container.streams=[SimpleNamespace(codec_context=SimpleNamespace())]
        container.decode.return_value=iter(range(len(rows)))
        pool=SimpleNamespace(languages=['en-US'],name='AppleVision')
        secondary=Mock();secondary.recognize.return_value={'lines':[]}
        with patch('av.open',return_value=container), patch.object(core,'oriented_image',return_value=Image.new('RGB',(80,30))), patch.object(core,'RapidPool',return_value=secondary), patch('quality_refine.retry_image',return_value=None):
            self.assertEqual(refine(rows,'test',{'stream_index':0},(0,0,1,1),pool,2,1),0)
        self.assertEqual(secondary.recognize.call_count,2)  # full crop + text band, never band twice
        self.assertEqual(rows[8]['text'],'hello!')

    def test_failed_language_check_is_actionable_not_silently_latin(self):
        from language_detection import resolve_language, LanguageUndetermined
        pool=SimpleNamespace(languages=['auto'],name='AppleVision',recognize=Mock(return_value=reading('Latin-looking error')))
        with patch.object(core,'RapidPool',side_effect=ImportError('missing')),patch.object(core,'frame_at',return_value=Image.new('RGB',(40,40))):
            with self.assertRaisesRegex(LanguageUndetermined,'选择原语言'):
                resolve_language('test',{'duration':10},None,pool)
        self.assertEqual(pool.languages,['auto'])
        self.assertFalse(pool.auto_probe)

    def test_missing_primary_engine_still_fails_clearly(self):
        with patch('importlib.util.find_spec',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'rapidocr'):core.RapidPool(['en-US'],[])

    def test_memo_hashes_each_visited_crop_once_and_keeps_scale_distinct(self):
        import temporal_scan
        secondary=Mock(); secondary.recognize.return_value=reading('Hello')
        memo=temporal_scan.ExactFrameMemo(secondary)
        images=[Image.new('RGB',(10,10),'white') for _ in range(5)]
        with patch('temporal_scan.hashlib.sha256',wraps=temporal_scan.hashlib.sha256) as digest:
            temporal_scan.recognize_group(memo,images,2)
            self.assertEqual(digest.call_count,3)  # first, middle, last, no scaled rehash
        self.assertEqual(secondary.recognize.call_count,1)
        temporal_scan.recognize_group(memo,images,1)
        self.assertEqual(secondary.recognize.call_count,2)

    def test_controls_cleanup_preserves_active_unknown_files_and_symlinks(self):
        from control_cleanup import clean_finished_controls
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'controls';root.mkdir()
            for name in ('done','active','unknown','other'):(root/name).mkdir()
            (root/'done/stop').touch();(root/'unknown/pause').touch();(root/'other/note.txt').touch()
            outside=Path(tmp)/'outside';outside.mkdir();(outside/'stop').touch()
            (root/'link').symlink_to(outside,target_is_directory=True)
            self.assertEqual(clean_finished_controls(root,['done','other','link'],['active']),1)
            for p in ('active','unknown/pause','other/note.txt','link'):self.assertTrue((root/p).exists())
            self.assertTrue((outside/'stop').exists())

    def test_ass_uses_observed_roi_position_and_srt_keeps_plain_text(self):
        events=core.make_segments(rows_for(['Hello']*5))
        document={'video':{'width':1080,'height':1920,'duration':20},
                  'calibration':{'roi':[0,.60,1,.70]},'events':events}
        with tempfile.TemporaryDirectory() as tmp:
            stem=Path(tmp)/'E01';core.export_files(document,stem)
            ass=stem.with_suffix('.ass').read_text()
            self.assertIn(r'{\an2\pos(540,1296)\fs96}Hello',ass)
            self.assertNotIn('pos(',stem.with_suffix('.srt').read_text())

    def test_diagnostic_keys_display_chinese_and_read_legacy(self):
        from diagnostic_labels import summary
        self.assertNotIn('fragment_compacted',summary({'fragment_compacted':3}))
        self.assertNotIn('identical_fragment_compacted',summary({'identical_fragment_compacted':3}))

    def test_real_source_worker_can_load_models_without_tools_on_pythonpath(self):
        import base64, json, os, subprocess, sys
        root=Path(__file__).resolve().parent.parent
        from model_manifest import MODELS
        if not all((root/'models'/name).exists() for name in MODELS):
            self.skipTest('Offline models unavailable; packaged smoke checks this after build')
        request=json.dumps({'image':base64.b64encode((root/'assets/smoke-korean.png').read_bytes()).decode()})+'\n'
        env=dict(os.environ);env.pop('PYTHONPATH',None)
        with tempfile.TemporaryDirectory() as cwd:
            result=subprocess.run([sys.executable,str(root/'launch.py'),'--ocr-worker','--model-dir',str(root/'models'),'--korean','--threads','1','--cpu'],
                                  input=request,text=True,capture_output=True,cwd=cwd,env=env,timeout=90)
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(result.stdout.strip().splitlines()[-1])
        self.assertIn('안녕하세요',core.read_lines(output)[0])
