import json,os,sys,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QProcess,Qt,QEvent
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog
from ella_app import MainWindow,DesktopApplication
APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)

class ShutdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=MainWindow(Path(self.tmp.name));self.w.show();self.w.activateWindow();APP.processEvents()
    def wait_for(self,predicate,seconds=4):
        end=time.monotonic()+seconds
        while not predicate() and time.monotonic()<end:QTest.qWait(20)
        self.assertTrue(predicate())
    def tearDown(self):
        if self.w.process:
            self.w.process.kill();self.w.process.waitForFinished(2000)
        self.w.close();self.w.deleteLater();APP.processEvents();self.tmp.cleanup()
    def worker(self,code):
        p=QProcess(self.w);self.w.process=p;p.finished.connect(self.w.process_finished);p.start(sys.executable,['-c',code]);self.assertTrue(p.waitForStarted(2000));return p
    def test_standard_close_shortcut_saves_and_closes(self):
        self.assertIn(QKeySequence(QKeySequence.StandardKey.Close),self.w.close_action.shortcuts())
        QTest.keySequence(self.w,QKeySequence(QKeySequence.StandardKey.Close))
        self.wait_for(lambda:not self.w.isVisible());self.assertTrue(self.w.state_file.exists())
    def test_quit_action_closes_dialogs_and_main_window(self):
        d=QDialog(self.w);d.setModal(True);d.show();APP.processEvents()
        self.w.quit_action.trigger();self.wait_for(lambda:not self.w.isVisible());self.assertFalse(d.isVisible())
    def test_idle_worker_finishing_retries_window_close(self):
        self.worker("import sys,time;sys.stdin.readline();time.sleep(.1)")
        self.w.close();self.assertTrue(self.w.isVisible())
        self.wait_for(lambda:not self.w.isVisible());self.assertIsNone(self.w.process)
    def test_active_close_saves_interrupted_job_and_does_not_start_next(self):
        w=self.w;w.control_dir=Path(self.tmp.name)/'controls';w.control_dir.mkdir();w.job_started=time.monotonic()
        w.jobs=[{'id':'a','source':'a.mp4','relative':'a.mp4','status':'running','duration':60,'processed_seconds':23},{'id':'b','source':'b.mp4','relative':'b.mp4','status':'pending','duration':60}];w.active=w.jobs[0];w.running=True;w.refresh_queue()
        self.worker("import pathlib,time;stop=pathlib.Path("+repr(str(w.control_dir/'stop'))+");\nwhile not stop.exists():time.sleep(.01)")
        w.request_quit();self.wait_for(lambda:not w.isVisible());saved=json.loads(w.state_file.read_text())
        self.assertEqual(saved['jobs'][0]['status'],'interrupted');self.assertEqual(saved['jobs'][0]['processed_seconds'],23);self.assertEqual(saved['jobs'][1]['status'],'pending')
        QTest.qWait(150);self.assertIsNone(w.process)
    def test_close_waits_for_background_save(self):
        self.w.background_task(lambda:time.sleep(.1),lambda _:None)
        self.w.close();self.assertTrue(self.w.isVisible());self.wait_for(lambda:not self.w.isVisible())
    def test_native_quit_event_uses_saved_shutdown(self):
        class Harness:
            shutdown_ready=False
            window=self.w
        self.assertTrue(DesktopApplication.event(Harness(),QEvent(QEvent.Type.Quit)))
        self.wait_for(lambda:not self.w.isVisible());self.assertTrue(self.w.state_file.exists())
