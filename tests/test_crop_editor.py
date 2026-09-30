import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from crop_editor import CropCanvas,CropDialog
from ella_app import MainWindow,STYLE
APP=QApplication.instance() or QApplication([]);APP.setStyleSheet(STYLE)
class CropTests(unittest.TestCase):
    def setUp(self):
        self.c=CropCanvas();self.c.resize(600,400);p=QPixmap(400,400);p.fill(Qt.GlobalColor.white);self.c.pixmap=p;self.c.source_size=(400,400);self.c.show();APP.processEvents()
    def tearDown(self):self.c.close();self.c.deleteLater();APP.processEvents()
    def drag(self,a,b):
        QTest.mousePress(self.c,Qt.MouseButton.LeftButton,pos=QPoint(*a));QTest.mouseMove(self.c,QPoint(*b));QTest.mouseRelease(self.c,Qt.MouseButton.LeftButton,pos=QPoint(*b))
    def test_letterbox_is_ignored_and_native_rect_unchanged(self):
        old=self.c.roi;self.drag((10,20),(90,200));self.assertEqual(old,self.c.roi);self.assertEqual(self.c.rect().width(),600)
    def test_draw_reverse_move_and_clamp(self):
        self.c.draw_new=True;self.drag((450,300),(200,200));self.assertEqual(self.c.roi,(.25,.5,.875,.75))
        self.drag((300,250),(600,400));self.assertEqual(self.c.roi,(.375,.75,1.,1.))
    def test_resize_and_keyboard(self):
        self.c.set_roi((.25,.25,.75,.75));self.drag((400,300),(460,340));self.assertEqual(self.c.roi,(.25,.25,.9,.85))
        QTest.keyClick(self.c,Qt.Key.Key_Left);self.assertAlmostEqual(self.c.roi[0],.2475)
        self.assertFalse(self.c.set_roi((.5,.5,.2,.2)))
    def test_initial_preview_cannot_be_applied(self):
        with patch.object(CropDialog,'load'):
            d=CropDialog(Path('/absent.mp4'),None);self.assertFalse(d.apply.isEnabled());d.reject()
    def test_missing_source_offers_relocation_without_starting_worker_or_traceback(self):
        d=CropDialog(Path('/absent-video.mp4'),None)
        self.assertIsNone(d.process)
        self.assertFalse(d.relink.isHidden())
        self.assertIn('找不到原视频',d.info.text())
        self.assertNotIn('Traceback',d.info.text())
        self.assertFalse(d.apply.isEnabled())
        d.reject()
    def test_relocation_uses_selected_video_and_keeps_dialog_open(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(CropDialog,'load'):
            source=Path(tmp)/'moved.mp4';source.touch()
            d=CropDialog(Path('/absent.mp4'),None)
            with patch('crop_editor.QFileDialog.getOpenFileName',return_value=(str(source),'')):
                d.relocate_source()
            self.assertEqual(d.path,source.resolve())
            self.assertEqual(d.relocated_path,source.resolve())
            self.assertIn(source.name,d.caption.text())
            d.reject()
    def test_thin_selection_uses_nearest_bottom_handle(self):
        self.c.set_roi((.2,.5,.8,.53))
        self.assertEqual(self.c.hit(self.c.selection_rect().bottomLeft()),'lb')
    def test_click_candidate_snaps_and_roi_edit_invalidates_old_calibration(self):
        self.c.candidates=[{'roi':(.1,.2,.9,.3),'score':5}]
        QTest.mouseClick(self.c,Qt.MouseButton.LeftButton,pos=QPoint(300,100))
        self.assertEqual(self.c.roi,(.1,.2,.9,.3))
        with patch.object(CropDialog,'load'):
            d=CropDialog(Path('/absent.mp4'),None);d.calibration={'roi':list(d.canvas.roi),'font_height':.02}
            d.canvas.set_roi((.1,.4,.9,.6));self.assertIsNone(d.calibration);d.reject()
    def test_precision_dialog_has_four_separate_rows(self):
        with patch.object(CropDialog,'load'):
            d=CropDialog(Path('/absent.mp4'),None);d.show();d.precision.click();APP.processEvents()
            self.assertTrue(d.precision_dialog.isVisible())
            for a,b in zip(d.coords,d.coords[1:]):
                self.assertGreaterEqual(b.geometry().top()-a.geometry().bottom(),12)
                self.assertEqual(a.height(),40)
            d.precision_dialog.close();d.reject()
    def test_seek_click_and_drag_update_time_without_reflow(self):
        with patch.object(CropDialog,'load'):
            d=CropDialog(Path('/absent.mp4'),None);d.meta={'duration':72.1};d.slider.setEnabled(True)
            d.show();APP.processEvents();canvas=d.canvas.geometry();bar=d.slider.geometry()
            QTest.mousePress(d.slider,Qt.MouseButton.LeftButton,pos=QPoint(round(bar.width()*.25),bar.height()//2))
            APP.processEvents();self.assertAlmostEqual(d.slider.value(),250,delta=25)
            QTest.mouseMove(d.slider,QPoint(round(bar.width()*.75),bar.height()//2))
            APP.processEvents();self.assertAlmostEqual(d.slider.value(),750,delta=25)
            self.assertIn('54.',d.time_label.text())
            d.set_info('正在读取画面…');APP.processEvents();self.assertEqual(d.canvas.geometry(),canvas)
            self.assertEqual(d.slider.geometry(),bar)
            QTest.mouseRelease(d.slider,Qt.MouseButton.LeftButton,pos=QPoint(round(bar.width()*.75),bar.height()//2))
            d.reject()
    def test_playback_is_bounded_and_pauses_on_region_interaction(self):
        with patch.object(CropDialog,'load') as load:
            d=CropDialog(Path('/absent.mp4'),None);d.meta={'duration':7200.}
            d.slider.setRange(0,7200000);d.set_position(50.123);d.play_button.setEnabled(True)
            self.assertAlmostEqual(d.selected_seconds(),50.123,places=3)
            d.toggle_play();self.assertTrue(d.playing);self.assertEqual(d.play_button.text(),'暂停')
            calls=load.call_count;d.preview_busy=True;d.play_tick();self.assertEqual(load.call_count,calls)
            d.display_seconds=50.2;d.canvas.interactionStarted.emit()
            self.assertFalse(d.playing);self.assertFalse(d.play_timer.isActive())
            self.assertAlmostEqual(d.selected_seconds(),50.2)
            d.toggle_play();d.reject();self.assertFalse(d.playing);self.assertTrue(d.closed)
    def test_seek_during_playback_preserves_user_target(self):
        with patch.object(CropDialog,'load'):
            d=CropDialog(Path('/absent.mp4'),None);d.meta={'duration':100.}
            d.play_button.setEnabled(True);d.display_seconds=20.;d.toggle_play()
            d.slider.setValue(750)
            self.assertFalse(d.playing);self.assertEqual(d.selected_seconds(),75.)
            d.reject()
    def test_continuous_drag_does_not_restart_preview_throttle(self):
        with patch.object(CropDialog,'load'),patch('crop_editor.QTimer.start') as start:
            d=CropDialog(Path('/absent.mp4'),None);d.meta={'duration':100.}
            with patch.object(d.debounce,'isActive',return_value=True):d.seek()
            start.assert_not_called();d.reject()
    def test_playback_bar_fits_minimum_dialog_without_overlapping_controls(self):
        with patch.object(CropDialog,'load'):
            d=CropDialog(Path('/absent.mp4'),None);d.resize(d.minimumSize());d.show();APP.processEvents()
            controls=[d.play_button,d.previous,d.slider,d.next,d.time_label]
            self.assertGreater(d.slider.width(),100)
            for left,right in zip(controls,controls[1:]):self.assertLess(left.geometry().right(),right.geometry().left())
            self.assertLess(controls[-1].geometry().right(),d.width());d.reject()
class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=MainWindow(Path(self.tmp.name));self.w.resize(960,680);self.w.show();APP.processEvents()
    def tearDown(self):self.w.close();self.w.deleteLater();APP.processEvents();self.tmp.cleanup()
    def test_selection_and_roi_requeue(self):
        self.assertFalse(self.w.crop_btn.isEnabled());j={'id':'x','source':'/x.mp4','relative':'x.mp4','status':'done','roi':[.1,.5,.9,.9]};self.w.jobs.append(j);self.w.refresh_queue();self.w.queue_table.selectRow(0)
        self.assertTrue(self.w.crop_btn.isEnabled());self.w.clear_roi();self.assertEqual(j['status'],'pending');self.assertTrue(j['replace_output']);self.assertEqual(self.w.selected_jobs(),[j])
    def test_equal_control_heights_and_advanced_does_not_squeeze_main(self):
        height=self.w.profile.height()
        for widget in [self.w.export_format,self.w.output,self.w.output_btn,self.w.crop_btn,self.w.start_btn,self.w.memory,self.w.language]:self.assertEqual(widget.height(),height)
        size=self.w.size();self.w.advanced_toggle.click();APP.processEvents();self.assertEqual(size,self.w.size());self.assertTrue(self.w.advanced.isVisible())
        controls=[self.w.engine if os.name!='nt' else self.w.device,self.w.memory]
        for a,b in zip(controls,controls[1:]):self.assertLess(a.geometry().bottom(),b.geometry().top())
        self.assertGreater(self.w.memory.lineEdit().height(),16)
        self.w.advanced_dialog.close()
if __name__=='__main__':unittest.main()
