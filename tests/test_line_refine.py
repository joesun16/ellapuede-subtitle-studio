import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import av
from PIL import Image
import subtitle_ocr as core
from line_refine import targets,refine,confidence_tracks,restore_low_confidence_lines


def line(text,y,confidence=.95):
    return {'box':[.1,y,.8,.18],'candidates':[{'text':text,'confidence':confidence}]}


def rows_for(top='Upper line',bottom='Lower line',missing_confidence=None):
    rows=[]
    for i in range(7):
        lines=[line(top,.08),line(bottom,.65)]
        if i==3:
            if missing_confidence is None:lines=lines[1:]
            else:lines[0]['candidates'][0]['confidence']=missing_confidence
        result={'lines':lines};text,confidence=core.read_lines(result)
        rows.append(dict(frame=i,start=i/10,end=(i+1)/10,text=text,confidence=confidence,ocr=result))
    return rows


class MissingLineTests(unittest.TestCase):
    def test_punctuation_retry_requires_exact_independent_readings(self):
        from quality_refine import retry_punctuation
        from unittest.mock import Mock
        image=Image.new('RGB',(160,100))
        for other in ('Where are you?','- Where are you?','Where are you'):
            engine=Mock()
            engine.recognize.side_effect=[{'lines':[line('Where are you?',.1)]},{'lines':[line(other,.1)]}]
            result=retry_punctuation(engine,image,'Where are you?')
            self.assertEqual(bool(result),other=='Where are you?')
            self.assertEqual([call.args[0].width for call in engine.recognize.call_args_list],[160,320])

    def test_confidence_dip_does_not_recover_changed_pixels_or_a_real_blank(self):
        from PIL import ImageDraw,ImageFont
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ('held','changed','blank'):
                path=Path(tmp)/(kind+'.mkv')
                with av.open(str(path),'w') as container:
                    stream=container.add_stream('ffv1',rate=10)
                    stream.width=480;stream.height=180;stream.pix_fmt='yuv420p'
                    for i in range(7):
                        image=Image.new('RGB',(480,180),(40,35,30));draw=ImageDraw.Draw(image)
                        text=('Upper line' if kind=='held' else 'Upper lime' if kind=='changed' else '') if i==3 else 'Upper line'
                        draw.text((60,15),text,font=ImageFont.load_default(size=24),fill='white',stroke_width=2,stroke_fill='black')
                        draw.text((60,118),'Lower line',font=ImageFont.load_default(size=24),fill='white',stroke_width=2,stroke_fill='black')
                        for packet in stream.encode(av.VideoFrame.from_image(image)):container.mux(packet)
                    for packet in stream.encode():container.mux(packet)
                rows=rows_for(missing_confidence=.3)
                for row in rows:
                    row['ocr']['lines'][0]['box']=[.12,.08,.4,.2]
                self.assertEqual(len(confidence_tracks(rows)),1)
                with patch.object(core.control,'check'):
                    count=restore_low_confidence_lines(rows,path,core.probe(path),(0,0,1,1))
                self.assertEqual(count,1 if kind=='held' else 0)
                self.assertEqual(rows[3]['text'],'Upper line\nLower line' if kind=='held' else 'Lower line')
    def test_low_score_color_votes_still_require_glyph_verification(self):
        from quality_refine import retry_image
        for alternate in ('confirmed','different'):
            calls=[]
            def recognize(image):
                calls.append(image.size)
                return {'lines':[line('confirmed' if len(calls)==1 else alternate,.1,.5)]}
            pool=SimpleNamespace(name='AppleVision',languages=['th-TH'],recognize=recognize)
            reference=dict(text='confirmed',ocr={'lines':[line('confirmed',.1)]})
            result=retry_image(pool,Image.new('RGB',(120,40)),1,reference)
            # A plain black image has no glyph evidence. Color-transform votes
            # alone must not turn low-confidence Thai into accepted text.
            self.assertIsNone(result)
            self.assertGreater(len(calls),2)
    def test_missing_upper_and_rejected_upper_are_both_checked(self):
        for confidence in (None,.3):
            self.assertEqual(set(targets(rows_for(missing_confidence=confidence),(0,0,1,1))),{3})

    def test_actual_replacement_in_same_line_is_not_a_missing_line(self):
        rows=rows_for();rows[3]['ocr']['lines'].insert(0,line("I can't go",.08))
        rows[3]['text'],rows[3]['confidence']=core.read_lines(rows[3]['ocr'])
        self.assertEqual(targets(rows,(0,0,1,1)),{})

    def test_raw_boxes_cannot_overwrite_an_earlier_verified_caption(self):
        rows=rows_for(missing_confidence=.3)
        rows[3].update(text='Already verified\nLower line',image_verified=True)
        self.assertEqual(targets(rows,(0,0,1,1)),{})
        with patch('av.open') as opened:
            self.assertEqual(restore_low_confidence_lines(rows,'unused',{},(0,0,1,1)),0)
        self.assertEqual(rows[3]['text'],'Already verified\nLower line')

    def test_real_blank_breaks_caption_track(self):
        rows=rows_for();rows[2].update(text='',ocr={'lines':[]})
        rows[4].update(text='',ocr={'lines':[]})
        self.assertEqual(targets(rows,(0,0,1,1)),{})

    def test_thai_missing_line_needs_two_current_image_readings(self):
        top='สวัสดีครับ';bottom='ยินดีต้อนรับ'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.mp4'
            with av.open(str(path),'w') as container:
                stream=container.add_stream('mpeg4',rate=10)
                stream.width=160;stream.height=100;stream.pix_fmt='yuv420p'
                for i in range(7):
                    for packet in stream.encode(av.VideoFrame.from_image(Image.new('RGB',(160,100)))):container.mux(packet)
                for packet in stream.encode():container.mux(packet)
            for agrees in (True,False):
                rows=rows_for(top,bottom,.3);calls=[]
                def recognize(image):
                    calls.append(image.size)
                    return {'lines':[line(top if agrees or len(calls)==1 else 'different',.08,.5)]}
                pool=SimpleNamespace(name='AppleVision',languages=['th-TH'],recognize=recognize)
                with patch.object(core.control,'emit'),patch.object(core.control,'check'),patch('optional_ocr.OptionalOCR') as optional:
                    optional.return_value.recognize.return_value=None
                    count=refine(rows,path,core.probe(path),(0,0,1,1),pool,1,1)
                self.assertEqual(count,int(agrees));self.assertEqual(len(calls),2)
                self.assertEqual(rows[3]['text'],top+'\n'+bottom if agrees else bottom)
                self.assertEqual(rows[3]['start'],.3);self.assertEqual(rows[3]['end'],.4)

            for alternate in (top,'different'):
                rows=rows_for(top,bottom,.3)
                pool=SimpleNamespace(name='AppleVision',languages=['th-TH'],recognize=lambda image:{'lines':[]})
                with patch.object(core.control,'emit'),patch.object(core.control,'check'),patch('optional_ocr.OptionalOCR') as optional:
                    optional.return_value.recognize.side_effect=[{'lines':[line(top,.08,.95)]},{'lines':[line(alternate,.08,.95)]}]
                    count=refine(rows,path,core.probe(path),(0,0,1,1),pool,1,1)
                    self.assertEqual(optional.return_value.recognize.call_count,2)
                    optional.return_value.close.assert_called_once()
                self.assertEqual(count,int(alternate==top))
                self.assertEqual(rows[3]['text'],top+'\n'+bottom if alternate==top else bottom)

    def test_missing_line_check_keeps_full_width_to_observe_changed_prefixes(self):
        roi=(.05,.4,.95,.8)
        job=targets(rows_for(),roi)[3][1][0]
        self.assertEqual((job[2][0],job[2][2]),(roi[0],roi[2]))
