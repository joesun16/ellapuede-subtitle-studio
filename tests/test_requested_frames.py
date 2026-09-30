import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

import av
from PIL import Image
from video_crops import requested_frames


class RequestedFramesTests(unittest.TestCase):
    def test_sparse_seek_matches_sequential_pixels_and_variable_pts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'vfr.mp4'
            with av.open(str(path),'w') as container:
                stream=container.add_stream('mpeg4',rate=25)
                stream.width=160;stream.height=96;stream.pix_fmt='yuv420p'
                for i in range(180):
                    f=av.VideoFrame.from_image(Image.new('RGB',(160,96),(i%255,40,70)))
                    f.pts=i+i//7;f.time_base=Fraction(1,25)
                    for packet in stream.encode(f):container.mux(packet)
                for packet in stream.encode():container.mux(packet)
            with av.open(str(path)) as container:
                frames=list(container.decode(video=0))
            rows=[dict(start=f.time,frame=i) for i,f in enumerate(frames)]
            needed={0,15,16,100,178,179}
            with av.open(str(path)) as container:
                actual=dict(requested_frames(container,container.streams.video[0],rows,needed,{'origin':0}))
            self.assertEqual(set(actual),needed)
            for i,frame in actual.items():
                self.assertEqual(frame.pts,frames[i].pts)
                self.assertEqual(frame.to_image().tobytes(),frames[i].to_image().tobytes())
    def test_missing_seek_frame_falls_back_instead_of_skipping_verification(self):
        frame=SimpleNamespace(pts=10);container=MagicMock()
        container.decode.side_effect=[iter([]),iter([frame])]
        result=list(requested_frames(container,SimpleNamespace(time_base=.1),[{'start':1}],{0},{'origin':0}))
        self.assertEqual(result,[(0,frame)])
        self.assertEqual(container.seek.call_count,2)
    def test_truncated_source_reports_missing_frame(self):
        container=MagicMock();container.decode.side_effect=lambda _:iter([])
        with self.assertRaisesRegex(ValueError,'缺少原始时间戳'):
            list(requested_frames(container,SimpleNamespace(time_base=.1),[{'start':1}],{0},{'origin':0}))
    def test_seek_overshoot_falls_back_without_reordering_references(self):
        frames=[SimpleNamespace(pts=i) for i in range(4)]
        container=MagicMock();container.decode.side_effect=[iter([frames[0],frames[2]]),iter(frames)]
        rows=[dict(start=i*.1) for i in range(4)]
        actual=list(requested_frames(container,SimpleNamespace(time_base=.1),rows,{0,1,2,3},{'origin':0}))
        self.assertEqual(actual,list(enumerate(frames)))
