import io,json,tempfile,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from image_transport import encode_image
from hardware_policy import plan
from version import VERSION

class PerformanceTests(unittest.TestCase):
    def test_crop_transport_is_pixel_exact(self):
        image=Image.fromarray(np.random.default_rng(7).integers(0,256,(71,193,3),dtype=np.uint8));data=encode_image(image)
        self.assertEqual(data[:2],b'BM');self.assertEqual(Image.open(io.BytesIO(data)).convert('RGB').tobytes(),image.tobytes())
    def test_decoder_crop_matches_full_frame_conversion(self):
        import av
        from fractions import Fraction
        from video_crops import FrameCropper
        import subtitle_ocr as core
        rng=np.random.default_rng(23)
        cropper=FrameCropper((.13,.46,.91,.86))
        for _ in range(3):
            source=av.VideoFrame.from_ndarray(rng.integers(0,256,(240,320,3),dtype=np.uint8),format='rgb24').reformat(format='yuv420p')
            source.time_base=Fraction(1,1000)
            selected=cropper.crop(source)
            expected=core.image_crop(core.oriented_image(source),(.13,.46,.91,.86),1)
            self.assertEqual(selected.tobytes(),expected.tobytes())
    def test_large_images_keep_bounded_compressed_transport(self):
        image=Image.new('RGB',(2000,1000),(22,77,191));data=encode_image(image)
        self.assertTrue(data.startswith(b'\x89PNG'));self.assertEqual(Image.open(io.BytesIO(data)).tobytes(),image.tobytes())
    def test_all_profiles_respect_cpu_and_memory_budgets(self):
        for engine in ('vision','rapid'):
            for cpus in (1,2,4,8,32):
                for memory in (1,2,8,32):
                    previous=0
                    for mode in range(3):
                        p=plan(engine,mode,4,{'logical_cpus':cpus,'available_gb':memory})
                        self.assertLessEqual(p['workers']*p['threads'],max(1,cpus-1));self.assertGreaterEqual(p['workers'],previous);previous=p['workers']
    def test_single_version_used_by_core_and_installer(self):
        import subtitle_ocr,package_installers
        self.assertEqual(subtitle_ocr.VERSION,VERSION+'-beta');self.assertEqual(package_installers.VERSION,VERSION)
    def test_partial_frame_batch_is_saved_and_resumes(self):
        import av,sqlite3
        import subtitle_ocr as core
        import temporal_scan
        from resource_control import Cancelled
        class Pool:
            def recognize(self,image):return {'lines':[]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'test.mp4';cache=root/'cache';cache.mkdir()
            with av.open(str(video),'w') as c:
                stream=c.add_stream('mpeg4',rate=8);stream.width=80;stream.height=40;stream.pix_fmt='yuv420p'
                for n in range(64):
                    for packet in stream.encode(av.VideoFrame.from_image(Image.new('RGB',(80,40),(n*3,30,20)))):c.mux(packet)
                for packet in stream.encode():c.mux(packet)
            meta=core.probe(video);checks=0
            def cancel():
                nonlocal checks
                checks+=1
                if checks==23:raise Cancelled('test')
            with patch.object(core.control,'check',side_effect=cancel),patch.object(core.control,'emit'):
                with self.assertRaises(Cancelled):temporal_scan.scan_frames(video,meta,(0,0,1,1),Pool(),cache,2,1)
            with closing(sqlite3.connect(cache/'frames.sqlite')) as db:cached=db.execute('SELECT COUNT(*) FROM frames').fetchone()[0]
            self.assertGreater(cached,0);self.assertLess(cached,64)
            with patch.object(core.control,'check'),patch.object(core.control,'emit'):
                rows,perf=temporal_scan.scan_frames(video,meta,(0,0,1,1),Pool(),cache,2,1)
            self.assertEqual(len(rows),64);self.assertEqual(perf['cache_frames'],cached);self.assertEqual([r['frame'] for r in rows],list(range(64)))
            self.assertLess(perf['cache_commits'],perf['new_frame_rows'])
    def test_missing_line_requires_current_frame_evidence(self):
        import av
        import subtitle_ocr as core
        from line_refine import refine
        def line(text,y):return {'box':[.1,y,.8,.15],'candidates':[{'text':text,'confidence':.95}]}
        rows=[{'frame':i,'start':i/10,'end':(i+1)/10,'text':'Hello\nworld' if i!=2 else 'Hello','ocr':{'lines':[line('Hello',.1)]+([line('world',.65)] if i!=2 else [])},'confidence':.95} for i in range(5)]
        class Pool:
            def recognize(self,im):return {'lines':[line('different',.65)]}
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'test.mp4'
            with av.open(str(video),'w') as c:
                stream=c.add_stream('mpeg4',rate=10);stream.width=80;stream.height=40;stream.pix_fmt='yuv420p'
                for _ in range(5):
                    for packet in stream.encode(av.VideoFrame.from_image(Image.new('RGB',(80,40)))):c.mux(packet)
                for packet in stream.encode():c.mux(packet)
            with patch.object(core.control,'check'),patch.object(core.control,'emit'):
                self.assertEqual(refine(rows,video,core.probe(video),(0,0,1,1),Pool(),1,2),0)
            self.assertEqual(rows[2]['text'],'Hello')
