import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from workspace_policy import apply_settings,removal_snapshot,restore_removed,import_entries
from workspace_dialogs import export_results,cache_inventory,clear_completed_cache,migrate_cache
from project_progress import progress

class WorkspaceTests(unittest.TestCase):
    def test_language_change_requeues_completed_series_but_not_other_series(self):
        jobs=[{'id':'1','source':'/A/1.mp4','series':'A','status':'done','settings':{'language':'en-US'}},{'id':'2','source':'/B/2.mp4','series':'B','status':'pending','settings':{'language':'en-US'}}]
        apply_settings(jobs,{'language':'ko-KR'},'A');self.assertEqual(jobs[0]['status'],'pending');self.assertTrue(jobs[0]['replace_output']);self.assertEqual(jobs[1]['settings']['language'],'en-US')
    def test_format_only_change_marks_reexport_without_reprocessing(self):
        job={'id':'1','source':'/A/1.mp4','series':'A','status':'done','settings':{'language':'en-US','format':'srt'}}
        apply_settings([job],{'format':'ass'},'A')
        self.assertEqual(job['status'],'pending');self.assertTrue(job['export_only'])
        apply_settings([job],{'language':'ko-KR'},'A')
        self.assertNotIn('export_only',job)
        self.assertEqual(job['pending_reason'],'语言或引擎已更改 · 待重新识别')
        self.assertEqual(job['processed_seconds'],0)
    def test_default_change_does_not_touch_existing(self):
        jobs=[{'id':'1','series':'A','source':'/a','status':'done','settings':{'language':'en-US'}}]
        apply_settings(jobs,{'language':'ko-KR'},None);self.assertEqual(jobs[0]['settings']['language'],'en-US')
    def test_remove_restore_excludes_active_and_avoids_duplicates(self):
        a={'id':'a','source':'a','status':'running'};b={'id':'b','source':'b','status':'pending'};jobs=[a,b]
        snap=removal_snapshot(jobs,{'a','b'},a);self.assertEqual(len(snap),1);jobs.remove(b);restore_removed(jobs,snap);restore_removed(jobs,snap);self.assertEqual(len(jobs),2)
    def test_project_progress_is_duration_weighted_and_does_not_reset(self):
        jobs=[{'status':'done','duration':10},{'status':'pending','duration':90}];self.assertEqual(progress(jobs),100)
        jobs[1].update(status='running',processed_seconds=45);self.assertEqual(progress(jobs),550)
        jobs[1].update(status='interrupted');self.assertEqual(progress(jobs),550)
        jobs[1].update(processed_seconds=90);self.assertLess(progress(jobs),1000)
        jobs[1]['status']='done';self.assertEqual(progress(jobs),1000)
    def test_unknown_duration_never_divides_by_zero(self):
        self.assertEqual(progress([]),0);self.assertEqual(progress([{'status':'pending'}]),0)
    def test_parent_folder_separates_drama_subfolders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('DramaA','DramaB'):(root/name).mkdir();(root/name/'E01.mp4').write_bytes(b'fake')
            entries=import_entries([root]);self.assertEqual(len({x[2] for x in entries}),2)
    def test_reexport_preserves_basename_without_ocr_or_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stem=root/'cache';doc={'video':{'width':640,'height':360,'duration':2},'events':[{'id':1,'start':.1,'end':1.5,'text':'안녕하세요'}]};Path(str(stem)+'.subtitles.json').write_text(json.dumps(doc))
            jobs=[{'id':'1','source':'/not-present/片名.E01.mp4','relative':'片名.E01.mp4','result_stem':str(stem)}]
            with patch('subtitle_ocr.VisionPool',side_effect=AssertionError('No OCR')):export_results(jobs,root/'out','ass')
            self.assertIn('안녕하세요',(root/'out/片名.E01.ass').read_text());self.assertFalse((root/'out/片名.E01.srt').exists())
    def test_cache_cleanup_preserves_pending_and_export_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n,status in [('a','done'),('b','pending')]:
                d=root/'frames'/n;d.mkdir(parents=True);(d/'job.json').write_text(json.dumps({'source':n,'sha256':n}));(d/'frames.sqlite').write_bytes(b'cache')
            (root/'results').mkdir();(root/'results'/'keep.json').write_text('{}')
            clear_completed_cache(root,[{'source':'a','status':'done'},{'source':'b','status':'pending'}]);self.assertFalse((root/'frames/a').exists());self.assertTrue((root/'frames/b/frames.sqlite').exists());self.assertTrue((root/'results/keep.json').exists())
    def test_migration_verifies_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';old.mkdir();(old/'a').write_bytes(b'keep');migrate_cache(old,root/'new');self.assertEqual((root/'new/a').read_bytes(),b'keep');self.assertTrue((old/'a').exists())
            with self.assertRaises(ValueError):migrate_cache(old,old/'child')
