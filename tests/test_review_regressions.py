import json,tempfile,unittest,queue,threading,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PIL import Image
import subtitle_ocr as core

def reading(text,score=.99):
    return {'lines':[{'box':[.2,.25,.6,.2],'candidates':[{'text':text,'confidence':score}]}]}

class ReviewRegressions(unittest.TestCase):
    def test_manual_override_survives_previous_series_aspect_and_reuses_font(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);f=root/'series.json';f.write_text(json.dumps({'roi':[0,.8,1,.9],'aspect':16/9,'font_height':.02}))
            args=SimpleNamespace(roi=[0,.6,1,.8],series_file=f)
            result=core.resolve_series_region('portrait',{'width':1080,'height':1920},None,root,args)
            self.assertEqual(result['roi'],args.roi);self.assertNotIn('font_height',result)
            with patch.object(core,'calibrate',return_value={'font_height':.025}) as calibrate:
                result=core.prepare_manual_region('portrait',{'width':1080,'height':1920},None,root,args,result)
                again=core.resolve_series_region('next',{'width':1080,'height':1920},None,root,args)
                core.prepare_manual_region('next',{},None,root,args,again)
                calibrate.assert_called_once();self.assertEqual(again['font_height'],.025)

    def test_manual_calibration_only_recognizes_selected_pixels(self):
        im=Image.new('RGB',(100,200),'red');im.paste('blue',(10,120,90,160))
        class Pool:
            def recognize(self,crop):
                self_test.assertEqual(crop.size,(80,40));self_test.assertEqual(crop.getpixel((0,0)),(0,0,255))
                return reading('字幕内容')
        self_test=self
        with tempfile.TemporaryDirectory() as tmp,patch.object(core,'frame_at',return_value=im),patch.object(core.control,'emit'):
            result=core.calibrate('test',{'duration':120},Pool(),Path(tmp),(.1,.6,.9,.8))
        self.assertEqual(result['roi'],(.1,.6,.9,.8));self.assertAlmostEqual(result['font_height'],.04)

    def test_han_spacing_does_not_fragment_but_words_digits_punctuation_do(self):
        self.assertEqual(core.key('来了 来了'),core.key('来了来了'))
        for a,b in [('I can','I cannot'),('한국 말','한국말'),('来了!','来了?'),('来了1','来了2')]:self.assertNotEqual(core.key(a),core.key(b))
        texts=['来了来了','来了 来了']*10
        rows=[{'frame':i,'start':i*.04,'end':(i+1)*.04,'text':t,'confidence':.99,'ocr':reading(t)} for i,t in enumerate(texts)]
        events=core.make_segments(rows);self.assertEqual(len(events),1);self.assertEqual(events[0]['end'],.8)
        self.assertIn(events[0]['text'],texts)

    def test_cli_reexport_defaults_to_recorded_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stem=root/'exports'/'video';record=root/'private.json'
            record.write_text(json.dumps({'source':'/missing/video.mp4','export_stem':str(stem),'video':{'width':100,'height':100,'duration':1},'events':[{'id':1,'start':0,'end':1,'text':'Hello'}]}))
            self.assertEqual(core.main(['export',str(record),'--format','srt']),0)
            self.assertTrue(stem.with_suffix('.srt').exists());self.assertFalse((root/'video.srt').exists())

    def test_heartbeat_does_not_depend_on_psutil(self):
        from resource_control import Controller
        c=Controller();c.psutil=None
        with patch('resource_control.emit') as emit:c.check()
        self.assertEqual(emit.call_args.args[0],'heartbeat')

    def test_cpu_fallback_retires_existing_idle_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'echo.py';script.write_text('import sys,json,os\nfor line in sys.stdin: print(json.dumps({"lines":[],"pid":os.getpid(),"cpu":"--cpu" in sys.argv}),flush=True)\n')
            class Pool(core.VisionPool):
                def __init__(self):self.idle=queue.Queue();self.processes=[];self.lock=threading.Lock();self.languages=[];self.words=[]
                def command(self):return [sys.executable,str(script)]+(['--cpu'] if getattr(self,'force_cpu',False) else [])
            pool=Pool()
            try:
                first=pool.recognize(Image.new('RGB',(8,8)));pool.reset_backend(cpu=True)
                second=pool.recognize(Image.new('RGB',(8,8)))
                self.assertNotEqual(first['pid'],second['pid']);self.assertTrue(second['cpu']);self.assertIsNotNone(pool.processes[0].poll())
            finally:pool.close()

    def test_orphan_cleanup_is_explicit_and_protects_pending_same_content(self):
        from workspace_dialogs import clear_completed_cache
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for key,source,sha in [('orphan','removed','a'),('shared','removed2','b')]:
                d=root/'frames'/key;d.mkdir(parents=True);(d/'job.json').write_text(json.dumps({'source':source,'sha256':sha}))
            result=root/'results'/'pending';result.mkdir(parents=True);(result/'a.subtitles.json').write_text(json.dumps({'source':'pending','source_sha256':'b'}))
            jobs=[{'source':'pending','status':'pending'}]
            clear_completed_cache(root,jobs);self.assertTrue((root/'frames/orphan').exists())
            clear_completed_cache(root,jobs,True);self.assertFalse((root/'frames/orphan').exists());self.assertTrue((root/'frames/shared').exists())

    def test_one_language_vote_is_not_a_lock_and_confirmed_choice_restarts_workers(self):
        from language_detection import resolve_language
        pool=SimpleNamespace(languages=['auto'],name='AppleVision',auto_probe=False)
        pool.recognize=Mock(side_effect=[reading(t) for t in ['你好世界','大家来了','字幕内容','明天出发']])
        def reset(**kw):pool.languages=kw['languages']
        pool.reset_backend=Mock(side_effect=reset)
        korean=Mock();korean.recognize.return_value={'lines':[]}
        with patch.object(core,'RapidPool',return_value=korean),patch.object(core,'frame_at',return_value=Image.new('RGB',(80,100))):
            self.assertEqual(resolve_language('x',{'duration':20},None,pool),['zh-Hans'])
        self.assertEqual(pool.recognize.call_count,4);pool.reset_backend.assert_called_once_with(languages=['zh-Hans']);self.assertFalse(pool.auto_probe)

    def test_unresolved_language_does_not_silently_scan_multilingual(self):
        from language_detection import resolve_language
        pool=SimpleNamespace(languages=['auto'],name='AppleVision',recognize=Mock(return_value=reading('1234')),reset_backend=Mock())
        korean=Mock();korean.recognize.return_value={'lines':[]}
        with patch.object(core,'RapidPool',return_value=korean),patch.object(core,'frame_at',return_value=Image.new('RGB',(80,100))):
            with self.assertRaisesRegex(ValueError,'选择原语言'):resolve_language('x',{'duration':20},None,pool)
        pool.reset_backend.assert_not_called()
        with patch.object(core,'frame_at',side_effect=AssertionError('Do not repeat failed series probe')):
            with self.assertRaisesRegex(ValueError,'选择原语言'):resolve_language('next',{'duration':20},None,pool)

    def test_korean_votes_do_not_compare_scores_from_different_models(self):
        from language_detection import resolve_language
        pool=SimpleNamespace(languages=['auto'],name='AppleVision',recognize=Mock(return_value=reading('wrong latin',1)))
        def reset(**kw):pool.languages=kw['languages']
        pool.reset_backend=Mock(side_effect=reset)
        korean=Mock();korean.recognize.side_effect=[reading(t,.91) for t in ['좋은 날','친구야','안녕하세요!']]
        native=Mock();native._recognize_once.side_effect=[reading(t) for t in ['좋은 날','친구야','안녕하세요!']]
        with patch.object(core,'RapidPool',return_value=korean),patch.object(core,'VisionPool',return_value=native),patch.object(core,'frame_at',return_value=Image.new('RGB',(80,100))):
            self.assertEqual(resolve_language('x',{'duration':120},None,pool),['ko-KR'])

    def test_changed_font_invalidates_completed_result_even_with_same_rectangle(self):
        cached={'roi':[0,.6,1,.8],'font_height':.02,'aspect':.56}
        self.assertTrue(core.matching_calibration(cached,dict(cached)))
        self.assertFalse(core.matching_calibration(cached,dict(cached,font_height=.03)))

    def test_language_change_clears_stale_auto_label(self):
        from workspace_policy import apply_settings
        job={'id':'a','series':'A','source':'/A/e.mp4','status':'failed','settings':{'language':'auto'},'resolved_languages':['ko-KR'],'detected_language':'ko-KR'}
        apply_settings([job],{'language':'en-US'},'A')
        self.assertNotIn('resolved_languages',job);self.assertNotIn('detected_language',job);self.assertEqual(job['status'],'pending')

    def test_translated_reference_does_not_generate_bogus_cer(self):
        from benchmark_quality import evaluate
        report=evaluate({'events':[{'start':0,'end':1,'text':'你好'}]}, {'events':[{'start':0,'end':.5,'text':'Hello'},{'start':.5,'end':1,'text':'Hello'}]},timing_only=True)
        self.assertIsNone(report['character_error_rate']);self.assertEqual(report['overlap_fragments_per_reference_mean'],2)

    def test_failed_backup_leaves_original_files_and_no_partial_history(self):
        from safe_export import write_pair
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a.srt';a.write_text('original')
            with patch('safe_export.shutil.copy2',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):write_pair({a:'new'},backup=True)
            self.assertEqual(a.read_text(),'original');self.assertEqual(list((root/'.ellapuede-history').iterdir()),[])

    def test_bad_video_probe_does_not_abort_later_episodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'input';source.mkdir()
            (source/'E01.mp4').write_bytes(b'bad');(source/'E02.mp4').write_bytes(b'good')
            pool=SimpleNamespace(name='test',languages=['en-US'],words=[],close=Mock())
            with patch.object(core,'RapidPool',return_value=pool),patch.object(core,'probe',side_effect=[ValueError('bad video'),{'width':1000}]),patch.object(core,'run_one',return_value={'status':'completed_exported'}) as run,patch.object(core.control,'CONTROL',None),patch.object(core.control,'emit'):
                code=core.main(['extract',str(source),'-o',str(root/'out'),'--engine','rapid','--language','en-US'])
            self.assertEqual(code,1);self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0].name,'E02.mp4')
