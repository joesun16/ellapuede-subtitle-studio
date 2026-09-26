import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import resource_control as rc

class ControlTests(unittest.TestCase):
    def test_progress_messages_are_single_complete_utf8_records(self):
        import io,json
        from concurrent.futures import ThreadPoolExecutor
        output=io.StringIO()
        with patch('sys.stdout',output),ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda n:rc.emit('phase',phase='识别中',sequence=n),range(100)))
        records=[json.loads(line[len('@@ELLAPUEDE@@'):]) for line in output.getvalue().splitlines()]
        self.assertEqual(sorted(r['sequence'] for r in records),list(range(100)))
        self.assertTrue(all(r['phase']=='识别中' for r in records))

    def test_pause_resume_and_stop(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'pause').touch();c=rc.Controller(root);c.psutil=None
            complete=[]
            thread=threading.Thread(target=lambda:(c.check(),complete.append(True)))
            thread.start();time.sleep(.08);self.assertEqual(complete,[])
            (root/'pause').unlink();thread.join(2);self.assertEqual(complete,[True])
            (root/'stop').touch()
            with self.assertRaises(rc.Cancelled):c.check()
    def test_low_disk_preserves_work_by_stopping(self):
        with tempfile.TemporaryDirectory() as d:
            c=rc.Controller(output=d);c.psutil=None
            class Space:free=1
            with patch('resource_control.shutil.disk_usage',return_value=Space()):
                with self.assertRaisesRegex(RuntimeError,'磁盘'):c.check()

if __name__=='__main__':unittest.main()
