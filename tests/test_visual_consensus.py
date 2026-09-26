import unittest
from pathlib import Path
import tempfile

import numpy as np

from visual_consensus import _similar_mask, _similar_gap_mask, targets, refine


def row(i,text):
    return {'frame':i,'start':i/25,'end':(i+1)/25,'text':text,
            'confidence':1,'ocr':{'lines':[{'box':[.2,.5,.6,.2],
                                           'candidates':[{'text':text,'confidence':1}]}]}}


class VisualConsensusTests(unittest.TestCase):
    def test_same_glyph_mask_and_changed_glyph_mask(self):
        stable=np.zeros((24,80),dtype=bool);stable[5:15,20:50]=True
        jitter=stable.copy();jitter[5,20]=False
        changed=np.zeros_like(stable);changed[5:15,30:60]=True
        self.assertTrue(_similar_mask(stable,jitter))
        self.assertFalse(_similar_mask(stable,changed))

    def test_changed_final_letter_cannot_hide_in_long_caption(self):
        from PIL import Image,ImageDraw,ImageFont
        from frame_features import text_mask
        font=ImageFont.load_default(size=26)
        def mask(text):
            image=Image.new('RGB',(480,270),(40,35,30))
            ImageDraw.Draw(image).text((65,190),text,font=font,fill='white',
                                       stroke_width=2,stroke_fill='black')
            return text_mask(image)[170:245,48:432]
        self.assertTrue(_similar_mask(mask('He drove the car'),mask('He drove the car')))
        self.assertFalse(_similar_mask(mask('He drove the car'),mask('He drove the cat')))

    def test_bracketed_substitution_is_candidate_for_image_check(self):
        rows=[row(i,'오늘 좋아!' if i<6 or i>=8 else '오널 좋아!') for i in range(14)]
        found=targets(rows)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['suspects'],[6,7])
        self.assertEqual(found[0]['reference'],'오늘 좋아!')

    def test_bracketed_partial_reading_also_gets_image_check(self):
        rows=[row(i,'오늘 갑니다' if i!=6 else '오늘') for i in range(13)]
        self.assertEqual(targets(rows)[0]['suspects'],[6])

    def test_one_frame_unrelated_ocr_glyph_is_checked_against_pixels(self):
        rows=[row(i,'哥' if i!=6 else 'f') for i in range(13)]
        found=targets(rows)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['suspects'],[6])

    def test_blank_gap_needs_visible_glyphs_not_just_matching_neighbors(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        font=ImageFont.load_default(size=26)
        with tempfile.TemporaryDirectory() as directory:
            for gap_kind in ('held','blank','changed'):
                path=Path(directory)/(gap_kind+'.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for i in range(16):
                        image=Image.new('RGB',(480,270),(40,35,30))
                        visible=('' if gap_kind=='blank' else 'Gone' if gap_kind=='changed' else 'Hold') if 5<=i<9 else 'Hold'
                        if visible:
                            ImageDraw.Draw(image).text((170,185),visible,font=font,
                                                       fill='white',stroke_width=2,stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,'' if 5<=i<9 else 'Hold') for i in range(16)]
                for item in rows:
                    item['ocr']['lines'][0]['box']=[.34,.65,.32,.22]
                repaired=refine(rows,path,core.probe(path),(0,0,1,1))
                self.assertEqual(repaired,4 if gap_kind=='held' else 0)
                self.assertEqual(len(core.make_segments(rows)),1 if gap_kind=='held' else 2)

    def test_blank_gap_keeps_bracketed_text_when_left_ocr_boxes_were_missing(self):
        rows=[row(i,'Hold' if i<5 or i>=8 else '') for i in range(13)]
        for item in rows[:5]:item['ocr']['lines']=[]
        found=[item for item in targets(rows) if item['kind']=='blank']
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['suspects'],[5,6,7])
        self.assertEqual(found[0]['bracketed_text'],'Hold')
        self.assertEqual(len(found[0]['anchors']),1)

    def test_number_change_is_not_candidate(self):
        rows=[row(i,'Room 2' if i<6 or i>=8 else 'Room 3') for i in range(14)]
        self.assertEqual(targets(rows),[])

    def test_real_unbracketed_change_is_not_candidate(self):
        rows=[row(i,'你好' if i<6 else '再见') for i in range(14)]
        self.assertEqual(targets(rows),[])

    def test_video_pixels_decide_whether_ocr_substitution_is_repaired(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        font=ImageFont.load_default(size=26)
        readings=['He drove the car']*10+['He drove the cat']*2+['He drove the car']*10
        with tempfile.TemporaryDirectory() as directory:
            for actual_change in (False,True):
                path=Path(directory)/('changed.mkv' if actual_change else 'same.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for i,text in enumerate(readings):
                        image=Image.new('RGB',(480,270),(40,35,30))
                        visible=text if actual_change else readings[0]
                        ImageDraw.Draw(image).text((65,190),visible,font=font,
                                                   fill='white',stroke_width=2,stroke_fill='black')
                        frame=av.VideoFrame.from_image(image)
                        for packet in stream.encode(frame):output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,text) for i,text in enumerate(readings)]
                for item in rows:item['ocr']['lines'][0]['box']=[.12,.65,.74,.22]
                repaired=refine(rows,path,core.probe(path),(0,0,1,1))
                self.assertEqual(repaired,0 if actual_change else 2)
                self.assertEqual(len(core.make_segments(rows)),3 if actual_change else 1)


if __name__=='__main__':unittest.main()
