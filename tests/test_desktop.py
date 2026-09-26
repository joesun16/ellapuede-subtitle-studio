"""Extraction-only desktop state and navigation regression tests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QPushButton,QTabWidget
from ella_app import MainWindow,STYLE
APP=QApplication.instance() or QApplication([]);APP.setStyleSheet(STYLE)
class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.window=MainWindow(self.root/'state');self.window.show();APP.processEvents()
    def tearDown(self):
        self.window.close();self.window.deleteLater();APP.processEvents();self.temp.cleanup()
    def test_extraction_only_and_advanced_hidden(self):
        self.assertFalse(self.window.findChildren(QTabWidget))
        self.assertFalse(any('校对' in w.text() or '复核' in w.text() or '检查字幕' in w.text() for w in self.window.findChildren(QPushButton)))
        self.assertFalse(self.window.advanced.isVisible())
    def test_preparation_preserves_project_progress_and_korean_is_visible(self):
        self.window.handle_event({'type':'phase','phase':'定位字幕区域：第 1 / 12 个取样画面'})
        self.assertEqual(self.window.progress.maximum(),1000)
        self.assertIn('第 1 / 12',self.window.phase_label.text())
        self.assertGreaterEqual(self.window.language.findData('ko-KR'),0)
        self.assertTrue(self.window.language.isVisible())
        self.assertFalse(self.window.advanced.isAncestorOf(self.window.language))
    def test_language_change_requeues_visible_completed_job(self):
        job={'id':'a','source':'/example.mp4','relative':'example.mp4','status':'done','roi':None}
        self.window.jobs.append(job);self.window.language.setCurrentIndex(self.window.language.findData('ko-KR'))
        self.assertEqual(job['status'],'pending');self.assertTrue(job['replace_output'])
    def test_incomplete_queue_restores_as_interrupted(self):
        self.window.jobs.append({'id':'a','source':'/example.mp4','relative':'example.mp4','status':'running','roi':None});self.window.save_state()
        other=MainWindow(self.root/'state');self.assertEqual(other.jobs[0]['status'],'interrupted');other.close()
    def test_shared_region_event_is_saved_for_all_episodes(self):
        a={'id':'a','source':'/A/E01.mp4','relative':'E01.mp4','status':'running','roi':None,'series':'/A'}
        b={'id':'b','source':'/A/E02.mp4','relative':'E02.mp4','status':'done','roi':None,'series':'/A'}
        self.window.jobs.extend([a,b]);self.window.active=a
        roi=[.1,.7,.9,.9];self.window.handle_event({'type':'region','roi':roi,'automatic':True})
        self.assertEqual(self.window.series_regions['/A']['roi'],roi);self.assertEqual(b['detected_roi'],roi)
        self.window.active=None;self.window.refresh_queue();self.window.queue_table.selectRow(0);self.window.clear_roi()
        self.assertEqual(b['status'],'pending');self.assertNotIn('/A',self.window.series_regions)
    def test_speed_mode_change_does_not_requeue_or_change_content_settings(self):
        job={'id':'a','source':'/A/e.mp4','relative':'e.mp4','status':'done','roi':None};self.window.jobs.append(job)
        self.window.profile.setCurrentIndex(2);self.assertEqual(job['status'],'done')
    def test_result_records_actual_subtitle_location(self):
        self.window.active={}
        self.window.handle_event({'type':'result','stem':'/out/识别记录/E01','export_stem':'/out/E01','events':10,'flagged':3})
        self.assertEqual(self.window.active['export_stem'],'/out/E01')
        self.assertEqual(self.window.progress.value(),0)
    def test_finished_queue_never_requires_review(self):
        self.window.jobs.append({'id':'a','source':'/example.mp4','relative':'example.mp4','status':'done','roi':None,'flagged':8})
        self.window.finish_queue()
        self.assertIn('1 个视频已导出',self.window.phase_label.text())
    def test_format_is_persisted_and_locked_during_processing(self):
        self.window.export_format.setCurrentIndex(self.window.export_format.findData('ass'))
        self.window.save_state()
        other=MainWindow(self.root/'state')
        self.assertEqual(other.export_format.currentData(),'ass');other.close()
        self.window.set_running_ui(True)
        self.assertFalse(self.window.export_format.isEnabled())
        self.window.set_running_ui(False)
    def test_new_format_queues_reexport_and_preserves_old_file_until_export(self):
        stem=self.root/'E01';stem.with_suffix('.srt').write_text('keep')
        self.window.export_format.setCurrentIndex(self.window.export_format.findData('srt'))
        self.window.jobs.append({'id':'a','source':'/example.mp4','relative':'example.mp4','status':'done','roi':None,'export_stem':str(stem),
                                 'settings':dict(self.window.defaults,format='srt')})
        self.window.export_format.setCurrentIndex(self.window.export_format.findData('ass'))
        self.assertEqual(self.window.jobs[0]['status'],'pending')
        self.assertTrue(self.window.jobs[0]['export_only'])
        self.assertEqual(stem.with_suffix('.srt').read_text(),'keep')
if __name__=='__main__':unittest.main()
