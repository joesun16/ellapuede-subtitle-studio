import tempfile,unittest,sys,queue,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from subtitle_ocr import VisionPool
class ReuseTests(unittest.TestCase):
    def test_ocr_processes_survive_executor_recreation_between_episodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'echo.py';script.write_text('import sys,json,os,time\nfor line in sys.stdin:\n time.sleep(.02)\n print(json.dumps({"lines":[],"pid":os.getpid()}),flush=True)\n')
            class Pool(VisionPool):
                def __init__(self):self.idle=queue.Queue();self.processes=[];self.lock=threading.Lock();self.languages=[];self.words=[]
                def command(self):return [sys.executable,str(script)]
            pool=Pool();im=Image.new('RGB',(8,8))
            try:
                with ThreadPoolExecutor(max_workers=2) as ex:first={r['pid'] for r in ex.map(pool.recognize,[im]*4)}
                with ThreadPoolExecutor(max_workers=2) as ex:second={r['pid'] for r in ex.map(pool.recognize,[im]*4)}
                self.assertEqual(first,second);self.assertLessEqual(len(pool.processes),2)
            finally:pool.close()
