import unittest
import numpy as np
from PIL import Image,ImageDraw
from temporal_scan import compatible,recognize_group
class TemporalTests(unittest.TestCase):
    def test_blank_mask_never_assumes_unchanged_dialogue(self):
        m=np.zeros((40,160),dtype=bool);self.assertFalse(compatible(m,m))
    def test_small_added_word_and_blank_boundary_are_changes(self):
        a=np.zeros((40,160),dtype=bool);a[10:25,20:100]=1;b=a.copy();b[10:18,125:128]=1
        self.assertFalse(compatible(a,b));self.assertFalse(compatible(a,np.zeros_like(a)))
    def test_disagreement_restores_every_frame(self):
        class OCR:
            calls=0
            def recognize(self,im):
                self.calls+=1;txt='NO' if im.getpixel((0,0))[0]>100 else 'YES'
                return {'lines':[{'box':[0,0,1,1],'candidates':[{'text':txt,'confidence':1}]}]}
        images=[Image.new('RGB',(10,10),(i*40,0,0)) for i in range(6)];ocr=OCR();results,calls,verified=recognize_group(ocr,images,1)
        self.assertFalse(verified);self.assertEqual(calls,6);self.assertEqual(len(results),6)
    def test_matching_samples_reuse_recognized_text(self):
        class OCR:
            def recognize(self,im):return {'lines':[{'box':[0,0,1,1],'candidates':[{'text':'안녕하세요','confidence':.95}]}]}
        results,calls,verified=recognize_group(OCR(),[Image.new('RGB',(10,10),(i,0,0)) for i in range(8)],1)
        self.assertTrue(verified);self.assertEqual(calls,3);self.assertEqual(len(results),8)

class LongStableSubtitleTests(unittest.TestCase):
    def test_one_frame_word_change_survives_long_stable_groups(self):
        from types import SimpleNamespace
        from unittest.mock import patch,MagicMock
        from pathlib import Path
        import tempfile
        import subtitle_ocr as core
        import temporal_scan
        frames=[]
        for i in range(60):
            image=Image.new('RGB',(256,80));draw=ImageDraw.Draw(image)
            for x in (30,48,66):draw.rectangle((x,25,x+7,39),fill='white')
            image.putpixel((0,0),(i,0,0))
            if i==17:draw.rectangle((120,25,127,39),fill='white')
            frames.append(SimpleNamespace(pts=i,time_base=1/30,duration=1,image=image))
        class Pool:
            def recognize(self,image):
                text='안녕 2' if image.getpixel((122,30))[0]>200 else '안녕'
                return {'lines':[{'box':[.1,.2,.5,.4],'candidates':[{'text':text,'confidence':.99}]}]}
        container=MagicMock();container.__enter__.return_value=container
        container.streams=[SimpleNamespace(codec_context=SimpleNamespace())]
        container.decode.return_value=iter(frames)
        with tempfile.TemporaryDirectory() as tmp,patch('av.open',return_value=container),patch.object(core,'oriented_image',side_effect=lambda f:f.image),patch.object(core.control,'emit'),patch.object(core.control,'check'):
            rows,stats=temporal_scan.scan_frames('test',{'stream_index':0,'origin':0,'duration':2,'fps_hint':30},(0,0,1,1),Pool(),Path(tmp),1,1)
        self.assertEqual([i for i,r in enumerate(rows) if r['text']=='안녕 2'],[17])
        for i,row in enumerate(rows):
            self.assertAlmostEqual(row['start'],i/30,places=9)
            self.assertAlmostEqual(row['end'],(i+1)/30,places=9)
        self.assertLess(stats['new_ocr_frames'],20)

    def test_high_resolution_crop_buffer_has_a_byte_budget(self):
        from temporal_scan import group_capacity
        for size in [(522,97),(1920,400),(3840,1000)]:
            image=Image.new('RGB',size);n=group_capacity(image)
            self.assertTrue(n==1 or n*size[0]*size[1]*3<=8*1024*1024)
