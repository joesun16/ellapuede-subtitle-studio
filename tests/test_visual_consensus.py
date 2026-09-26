import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

import numpy as np

from visual_consensus import (_similar_mask, _similar_gap_mask,
                              _single_glyph_disagreement, _glyph_region_match,
                              refine_recurrent_variant, refine_held_variants,
                              refine_short_multiline_openings,
                              refine_combining_mark_variants,
                              refine_sparse_visible_holds,
                              refine_low_confidence_holds, _held_variant_groups,
                              targets, refine)


def row(i,text):
    return {'frame':i,'start':i/25,'end':(i+1)/25,'text':text,
            'confidence':1,'ocr':{'lines':[{'box':[.2,.5,.6,.2],
                                           'candidates':[{'text':text,'confidence':1}]}]}}


class VisualConsensusTests(unittest.TestCase):
    def test_combining_mark_flip_needs_matching_source_glyphs(self):
        import av
        from PIL import Image
        import subtitle_ocr as core
        first='คุณค่อยนั่งแทนเธอ';later='คุณค่อยนังแทนเธอ'
        self.assertIsNotNone(_single_glyph_disagreement(first,later))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'held.mkv'
            with av.open(str(path),'w') as output:
                stream=output.add_stream('ffv1',rate=25)
                stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                for _ in range(25):
                    for packet in stream.encode(av.VideoFrame.from_image(
                            Image.new('RGB',(480,270),(40,35,30)))):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            for verified in (False,True):
                rows=[row(i,first if i<5 else later) for i in range(25)]
                with patch('visual_consensus._glyph_region_match',return_value=verified) as check:
                    repaired=refine_combining_mark_variants(rows,path,core.probe(path),
                                                            (0,0,1,1))
                self.assertEqual(repaired,20 if verified else 0)
                self.assertEqual(len(core.make_segments(rows)),1 if verified else 2)
                self.assertEqual(check.call_count,2 if verified else 1)

    def test_sparse_ocr_hit_uses_actual_visible_duration(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        with tempfile.TemporaryDirectory() as directory:
            for changed in (False,True):
                path=Path(directory)/('brief.mkv' if changed else 'held-sparse.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for i in range(25):
                        image=Image.new('RGB',(480,270),(40,35,30))
                        if i==10 or (not changed and 5<=i<20):
                            ImageDraw.Draw(image).text((190,190),'Hold',
                                font=ImageFont.load_default(size=26),fill='white',
                                stroke_width=2,stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):
                            output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,'Hold' if i==10 else '') for i in range(25)]
                for item in rows:
                    if item['text']:
                        item['ocr']['lines'][0]['box']=[.38,.68,.28,.16]
                    else:item['ocr']['lines']=[]
                    item['confidence']=1 if item['text'] else 0
                count=refine_sparse_visible_holds(rows,path,core.probe(path),(0,0,1,1))
                self.assertEqual(count,0 if changed else 14)
                event=core.make_segments(rows)[0]
                self.assertAlmostEqual(event['start'],(10 if changed else 5)/25)
                self.assertAlmostEqual(event['end'],(11 if changed else 20)/25)

    def test_two_line_opening_variant_requires_same_disputed_glyph(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        top='I remember';early='He drove the cat';later='He drove the car'
        font=ImageFont.load_default(size=26)
        with tempfile.TemporaryDirectory() as directory:
            for changed in (False,True):
                path=Path(directory)/('changed.mkv' if changed else 'held.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for i in range(25):
                        image=Image.new('RGB',(480,270),(40,35,30))
                        draw=ImageDraw.Draw(image)
                        draw.text((120,145),top,font=font,fill='white',
                                  stroke_width=2,stroke_fill='black')
                        draw.text((65,190),early if changed and i<5 else later,
                                  font=font,fill='white',stroke_width=2,
                                  stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):
                            output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[]
                for i in range(25):
                    bottom=early if i<5 else later
                    lines=[{'box':[.25,.53,.49,.09],
                            'candidates':[{'text':top,'confidence':.95}]},
                           {'box':[.135,.70,.43,.12],
                            'candidates':[{'text':bottom,'confidence':.94}]}]
                    rows.append({'frame':i,'start':i/25,'end':(i+1)/25,
                                 'text':top+'\n'+bottom,'confidence':.94,
                                 'ocr':{'lines':lines}})
                repaired=refine_short_multiline_openings(rows,path,
                    core.probe(path),(0,0,1,1))
                self.assertEqual(repaired,0 if changed else 5)
                self.assertEqual(len(core.make_segments(rows)),2 if changed else 1)

    def test_rapid_ocr_high_confidence_flips_still_receive_pixel_checks(self):
        readings=['Say hello']*6+['Sey hello']*3+['Say helo']*2+['Say hello']*8
        rows=[row(i,text) for i,text in enumerate(readings)]
        self.assertEqual(_held_variant_groups(rows),[])
        self.assertEqual(len(_held_variant_groups(rows,include_high_confidence=True)),1)

    def test_low_confidence_held_line_extends_only_while_glyphs_remain(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        with tempfile.TemporaryDirectory() as directory:
            for changed in (False,True):
                path=Path(directory)/('changed.mkv' if changed else 'held.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for i in range(14):
                        image=Image.new('RGB',(480,270),(40,35,30))
                        visible='Hold' if not changed or 5<=i<9 else 'Gone'
                        ImageDraw.Draw(image).text((170,185),visible,
                            font=ImageFont.load_default(size=26),fill='white',
                            stroke_width=2,stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,'Hold' if 5<=i<9 else '') for i in range(14)]
                for item in rows:
                    item['ocr']['lines'][0]['box']=[.34,.65,.32,.22]
                    item['ocr']['lines'][0]['candidates'][0]={'text':'Hold','confidence':.3}
                self.assertEqual(refine_low_confidence_holds(rows,path,core.probe(path),
                                  (0,0,1,1)),0 if changed else 10)

    def test_held_caption_fluctuations_use_pixels_and_repeated_readings(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        actual='Say hello'
        readings=[actual]*6+['Sey hello']*5+['Say helo']*4+[actual]*8
        class FixedReading:
            name='SyntheticOCR'
            def recognize(self,image,correction=False):
                return {'lines':[{'box':[.1,.5,.8,.2],
                                  'candidates':[{'text':actual,'confidence':.95}]}]}
        with tempfile.TemporaryDirectory() as directory:
            for changed in (False,True):
                path=Path(directory)/('changed.mkv' if changed else 'held.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for text in readings:
                        image=Image.new('RGB',(480,270),(40,35,30))
                        visible=text if changed else actual
                        ImageDraw.Draw(image).text((140,180),visible,
                            font=ImageFont.load_default(size=26),fill='white',
                            stroke_width=2,stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,text) for i,text in enumerate(readings)]
                for i in (7,8,13):
                    rows[i]['text']='';rows[i]['confidence']=0
                    rows[i]['ocr']['lines'][0]['candidates'][0]['confidence']=.3
                for item in rows:item['ocr']['lines'][0]['box']=[.27,.62,.48,.2]
                count=refine_held_variants(rows,path,core.probe(path),(0,0,1,1),FixedReading())
                self.assertEqual(bool(count),not changed)
                if changed:self.assertGreaterEqual(len(core.make_segments(rows)),3)
                else:self.assertEqual(len(core.make_segments(rows)),1)

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

    def test_recurrent_long_caption_requires_same_disputed_glyph_pixels(self):
        from PIL import Image,ImageDraw,ImageFont
        font=ImageFont.load_default(size=26)
        left,right='He drove the car','He drove the cat'
        def observed(text):
            image=Image.new('RGB',(480,270),(40,35,30))
            ImageDraw.Draw(image).text((65,190),text,font=font,fill='white',
                                       stroke_width=2,stroke_fill='black')
            data={'text':text,'ocr':{'lines':[{'box':[.135,.73,.415,.08],
                   'candidates':[{'text':text,'confidence':.9}]}]}}
            return data,image
        changed=_single_glyph_disagreement(left,right)
        self.assertEqual(changed,(15,16))
        self.assertTrue(_glyph_region_match(observed(left),observed(left),left,changed))
        self.assertFalse(_glyph_region_match(observed(left),observed(right),left,changed))

    def test_recurrent_word_change_respects_actual_video_pixels(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        left,right='He drove the car','He drove the cat'
        readings=[left]*10+[right]*2+[left]*2+[right]*20
        font=ImageFont.load_default(size=26)
        class NoSecondReading:
            def recognize(self,image):return {'lines':[]}
        with tempfile.TemporaryDirectory() as directory:
            for actual_change in (False,True):
                path=Path(directory)/('changed.mkv' if actual_change else 'held.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for text in readings:
                        image=Image.new('RGB',(480,270),(40,35,30))
                        ImageDraw.Draw(image).text((65,190),text if actual_change else left,
                                                   font=font,fill='white',stroke_width=2,
                                                   stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):
                            output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,text) for i,text in enumerate(readings)]
                for item in rows:item['ocr']['lines'][0]['box']=[.135,.73,.415,.08]
                repaired=refine_recurrent_variant(rows,path,core.probe(path),
                                                  (0,0,1,1),NoSecondReading())
                self.assertEqual(bool(repaired),not actual_change)
                self.assertEqual(len(core.make_segments(rows)),4 if actual_change else 1)

    def test_bracketed_substitution_is_candidate_for_image_check(self):
        rows=[row(i,'뭣들 해!' if i<6 or i>=8 else '윗들 해!') for i in range(14)]
        found=targets(rows)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['suspects'],[6,7])
        self.assertEqual(found[0]['reference'],'뭣들 해!')

    def test_two_different_ocr_errors_inside_one_held_caption_need_video_evidence(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        actual='She said hello'
        readings=[actual]*10+['She seid hello']*2+['She sayd hello']+[actual]*10
        self.assertEqual([item['suspects'] for item in targets([row(i,t) for i,t in enumerate(readings)])
                         if item['kind']=='substitution'],[[10,11,12]])
        font=ImageFont.load_default(size=26)
        with tempfile.TemporaryDirectory() as directory:
            for changed in (False,True):
                path=Path(directory)/('changed.mkv' if changed else 'held.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for text in readings:
                        image=Image.new('RGB',(480,270),(40,35,30))
                        ImageDraw.Draw(image).text((65,190),text if changed else actual,
                                                   font=font,fill='white',stroke_width=2,
                                                   stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):
                            output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,text) for i,text in enumerate(readings)]
                for item in rows:item['ocr']['lines'][0]['box']=[.135,.73,.415,.08]
                count=refine(rows,path,core.probe(path),(0,0,1,1))
                self.assertEqual(count,0 if changed else 3)
                self.assertEqual(len(core.make_segments(rows)),4 if changed else 1)

    def test_punctuation_ocr_slip_is_repaired_only_when_pixels_agree(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        readings=['Are you?']*10+['Are you!']*2+['Are you?']*10
        with tempfile.TemporaryDirectory() as directory:
            for changed in (False,True):
                path=Path(directory)/('punctuation-change.mkv' if changed else 'punctuation-held.mkv')
                with av.open(str(path),'w') as output:
                    stream=output.add_stream('ffv1',rate=25)
                    stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                    for text in readings:
                        image=Image.new('RGB',(480,270),(40,35,30))
                        ImageDraw.Draw(image).text((120,185),text if changed else 'Are you?',
                            font=ImageFont.load_default(size=26),fill='white',
                            stroke_width=2,stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                rows=[row(i,text) for i,text in enumerate(readings)]
                for item in rows:item['ocr']['lines'][0]['box']=[.23,.65,.55,.22]
                self.assertEqual(refine(rows,path,core.probe(path),(0,0,1,1)),
                                 0 if changed else 2)
                self.assertEqual(len(core.make_segments(rows)),3 if changed else 1)

    def test_independent_ocr_checks_the_suspect_frame_not_the_right_anchor(self):
        import av
        from PIL import Image,ImageDraw,ImageFont
        import subtitle_ocr as core
        left,right='He drove the car','He drove the cat'
        readings=[left]*8+[right]*2+[left]*8
        class FakeVision:
            name='AppleVision-test'
            languages=['en-US']
        class FakeSecondary:
            def __init__(self,*args,**kwargs):pass
            def close(self):pass
            def recognize(self,image,**kwargs):
                text=left if image.getpixel((0,0))[0]>35 else right
                return {'lines':[{'box':[.1,.6,.8,.2],
                                  'candidates':[{'text':text,'confidence':.95}]}]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'changed.mkv'
            with av.open(str(path),'w') as output:
                stream=output.add_stream('ffv1',rate=25)
                stream.width=480;stream.height=270;stream.pix_fmt='yuv420p'
                for text in readings:
                    image=Image.new('RGB',(480,270),(40,35,30) if text==left else (30,35,40))
                    ImageDraw.Draw(image).text((65,190),text,font=ImageFont.load_default(size=26),
                                               fill='white',stroke_width=2,stroke_fill='black')
                    for packet in stream.encode(av.VideoFrame.from_image(image)):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            rows=[row(i,text) for i,text in enumerate(readings)]
            for item in rows:item['ocr']['lines'][0]['box']=[.135,.73,.415,.08]
            with patch('optional_ocr.OptionalOCR',FakeSecondary):
                self.assertEqual(refine(rows,path,core.probe(path),(0,0,1,1),FakeVision()),0)
            self.assertEqual(len(core.make_segments(rows)),3)

    def test_bracketed_partial_reading_also_gets_image_check(self):
        rows=[row(i,'뭐 어쨌든' if i!=6 else '뭐') for i in range(13)]
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
