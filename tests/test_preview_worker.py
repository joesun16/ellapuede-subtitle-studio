"""The region editor must seek repeatedly without reopening the decoder."""
import base64
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import av
from PIL import Image


class PreviewSessionTests(unittest.TestCase):
    def test_missing_video_returns_structured_recovery_error(self):
        root=Path(__file__).resolve().parent.parent
        result=subprocess.run([sys.executable,str(root/'launch.py'),'--preview-worker','/missing/video.mp4','--serve'],
                              input='',text=True,capture_output=True,timeout=15,check=True)
        self.assertEqual(json.loads(result.stdout.strip())['code'],'source_missing')
        self.assertNotIn('Traceback',result.stderr)
    def test_multiple_seeks_in_one_preview_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'preview.mp4'
            with av.open(str(video),'w') as container:
                stream=container.add_stream('mpeg4',rate=8)
                stream.width=160;stream.height=96;stream.pix_fmt='yuv420p'
                for n in range(16):
                    for packet in stream.encode(av.VideoFrame.from_image(Image.new('RGB',(160,96),(n*12,40,70)))):
                        container.mux(packet)
                for packet in stream.encode():container.mux(packet)
            root=Path(__file__).resolve().parent.parent
            requests=''.join(json.dumps({'request_id':i,'seconds':t,'fast':True})+'\n' for i,t in enumerate((0,.5,.625,1.5,.55)))
            result=subprocess.run([sys.executable,str(root/'launch.py'),'--preview-worker',str(video),'--serve'],
                                  input=requests,text=True,capture_output=True,timeout=15,check=True)
            replies=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([x['request_id'] for x in replies],[0,1,2,3,4])
            self.assertEqual([round(x['seconds'],3) for x in replies],[0,.5,.625,1.5,.55])
            self.assertEqual([round(x['frame_seconds'],3) for x in replies],[0,.5,.625,1.5,.5])
            images=[Image.open(io.BytesIO(base64.b64decode(x['image']))).convert('RGB') for x in replies]
            self.assertEqual([im.size for im in images],[(160,96)]*5)
            self.assertLess(images[0].getpixel((50,50))[0],images[1].getpixel((50,50))[0])
            self.assertLess(images[1].getpixel((50,50))[0],images[2].getpixel((50,50))[0])
            self.assertEqual(images[1].tobytes(),images[4].tobytes())
