import tempfile,unittest
from pathlib import Path
from source_relink import relink_series

class SourceRelinkTests(unittest.TestCase):
    def test_reconnects_matching_episodes_without_changing_finished_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);new=root/'new';new.mkdir()
            for name in ('ep1.mp4','ep2.mp4'):(new/name).touch()
            jobs=[{'source':str(root/'old'/f'ep{i}.mp4'),'relative':f'old/ep{i}.mp4',
                   'series':'Drama','status':status,'source_missing':True}
                  for i,status in ((1,'done'),(2,'failed'),(3,'pending'))]
            self.assertEqual(relink_series(jobs,jobs[0],new/'ep1.mp4'),2)
            self.assertEqual([j['status'] for j in jobs],['done','pending','pending'])
            self.assertEqual(jobs[1]['source'],str((new/'ep2.mp4').resolve()))
            self.assertFalse(jobs[0]['source_missing'])
            self.assertTrue(jobs[2]['source_missing'])
