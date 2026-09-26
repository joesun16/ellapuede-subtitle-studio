import json
from pathlib import Path
import tempfile
import unittest
from fractions import Fraction

import subtitle_ocr as tool


def row(i, text, start=None, end=None):
    return {'frame': i, 'start': i/30 if start is None else start,
            'end': (i+1)/30 if end is None else end,
            'text': text, 'confidence': 1, 'ocr': {}}


class SegmentationTests(unittest.TestCase):
    def test_thai_native_vision_scale_does_not_change_other_language_routes(self):
        self.assertEqual(tool.select_scale(0,544,'vision',['th-TH']),1)
        self.assertEqual(tool.select_scale(0,544,'rapid',['th-TH']),2)
        self.assertEqual(tool.select_scale(0,544,'vision',['en-US']),2)
        self.assertEqual(tool.select_scale(2,544,'vision',['th-TH']),2)

    def test_recurrent_multiscript_ocr_variants_form_one_observed_caption(self):
        readings=['สวัสดีครับ']*8+['สวัสดีคับ','สวัสดีครับ','สวสดีครับ',
                                     'สวัสดีครับ','สวัสดีคับ','สวัสดีครับ']
        rows=[]
        for i,text in enumerate(readings):
            value=row(i,text,start=i*.04,end=(i+1)*.04)
            value['ocr']={'lines':[{'box':[.2,.5,.6,.2],
                                    'candidates':[{'text':text,'confidence':.9}]}]}
            rows.append(value)
        events=tool.make_segments(rows)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['text'],'สวัสดีครับ')
        self.assertAlmostEqual(events[0]['end'],len(readings)*.04)

    def test_volatile_opening_joins_only_an_observed_stable_anchor(self):
        def visual(i,text):
            value=row(i,text,start=i*.04,end=(i+1)*.04)
            value['ocr']={'lines':[{'box':[.2,.5,.6,.2],
                                    'candidates':[{'text':text,'confidence':.9}]}]}
            return value
        noisy=['สวัสดีครับ','สวัสดีคับ','สวสดีครับ','สวัสดีคับ']*2
        rows=[visual(i,text) for i,text in enumerate(noisy+['สวัสดีคับ']*8)]
        self.assertEqual(len(tool.make_segments(rows)),1)
        self.assertEqual(tool.make_segments(rows)[0]['text'],'สวัสดีคับ')
        changed=[visual(i,text) for i,text in enumerate(noisy+['สวัสดีค่ะ']*8)]
        self.assertGreaterEqual(len(tool.make_segments(changed)),2)

    def test_rapid_real_word_changes_remain_distinct(self):
        readings=['He drove the car']*8+['He drove the cat','He drove the car']*2
        rows=[]
        for i,text in enumerate(readings):
            value=row(i,text,start=i*.04,end=(i+1)*.04)
            value['ocr']={'lines':[{'box':[.2,.5,.6,.2],
                                    'candidates':[{'text':text,'confidence':.9}]}]}
            rows.append(value)
        self.assertEqual([event['text'] for event in tool.make_segments(rows)],
                         ['He drove the car','He drove the cat','He drove the car',
                          'He drove the cat','He drove the car'])

    def test_sustained_korean_spacing_variation_stays_one_caption(self):
        def visual(i,text):
            value=row(i,text,start=i*.04,end=(i+1)*.04)
            value['ocr']={'lines':[{'box':[.2,.5,.6,.2],
                                    'candidates':[{'text':text,'confidence':.9}]}]}
            return value
        texts=['아마저런 애가']*8+['아마 저런 애가']*32
        events=tool.make_segments([visual(i,text) for i,text in enumerate(texts)])
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['start'],0)
        self.assertEqual(events[0]['end'],1.6)
        self.assertEqual(events[0]['text'],'아마 저런 애가')
        punctuation=['Are you?']*8+['Are you!']*32
        self.assertEqual(len(tool.make_segments([visual(i,text) for i,text in enumerate(punctuation)])),2)
        brief=['Are you?']*12+['Are you!']*2+['Are you?']*12
        self.assertEqual(len(tool.make_segments([visual(i,text) for i,text in enumerate(brief)])),3)

    def test_rapid_korean_tail_flicker_remains_one_caption(self):
        def visual(i,text):
            value=row(i,text,start=i*.04,end=(i+1)*.04)
            value['ocr']={'lines':[{'box':[.1,.2,.8,.3],
                                    'candidates':[{'text':text,'confidence':.94}]}]}
            return value
        a='저런 촌년을 보면 기분만 언짧지'
        b='저런 촌년을 보면 기분만 언잖지'
        c='저런 촌년을 보면 기분만 언쌓지'
        readings=([a]*5+[c]*2+[a]*8+[b]*4+[a]*2+[b]*8+[a]*3+
                  [b]*6+[a]+[b]*20+[a]*2+[b]+[a]*3+[b]+[a]*3)
        after='어르신께서\n절대적인 안정이 필요'
        texts=readings+[after]*12
        events=tool.make_segments([visual(i,text) for i,text in enumerate(texts)])
        self.assertEqual(len(events),2)
        self.assertAlmostEqual(events[0]['start'],0)
        self.assertAlmostEqual(events[0]['end'],len(readings)*.04)
        self.assertIn(events[0]['text'],(a,b))
        self.assertEqual(events[1]['text'],after)

    def test_large_displaced_end_card_is_not_dialogue(self):
        calibration={'roi':[.02,.715,.98,.86],'font_height':.05,
                     'candidates':[{'roi':[.02,.715,.98,.815],
                                    'coverage':6,'unique':6}]}
        events=[{'id':1,'start':.1,'text':'哥',
                 'observed_layout':{'bottom_y':.5,'glyph_height':.32}},
                {'id':2,'start':.2,'text':'哥',
                 'observed_layout':{'bottom_y':.5,'glyph_height':.51}},
                {'id':3,'start':80,'text':'续',
                 'observed_layout':{'bottom_y':.99,'glyph_height':.47}},
                {'id':4,'start':81,'text':'待',
                 'observed_layout':{'bottom_y':.66,'glyph_height':.65}}]
        kept,excluded=tool.exclude_off_band_graphics(events,calibration)
        self.assertEqual([item['text'] for item in kept],['哥','哥'])
        self.assertEqual([item['text'] for item in excluded],['续','待'])
        self.assertEqual([item['id'] for item in kept],[1,2])

    def test_repeated_line_with_real_blank_is_separate(self):
        events = tool.make_segments([row(0,'Yes'),row(1,''),row(2,'Yes')])
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]['end'],1/30)
        self.assertEqual(events[1]['start'],2/30)

    def test_negation_and_one_word_change_are_not_merged(self):
        events=tool.make_segments([row(i,'I can go' if i<10 else "I can't go") for i in range(20)])
        self.assertEqual([e['text'] for e in events],['I can go',"I can't go"])

    def test_similar_text_never_merges_without_image_verification(self):
        rows=[row(i,'Damian Frost is here') for i in range(12)]
        rows[5]['text']='Damlan Frost is here'
        events=tool.make_segments(rows)
        self.assertEqual(len(events),3)
        self.assertEqual(events[1]['text'],'Damlan Frost is here')
        rows[5]['text']='Damian Frost is here';rows[5]['image_verified']=True
        events=tool.make_segments(rows)
        self.assertEqual(len(events),1)
        self.assertIn('image_verified_repair',events[0]['flags'])

    def test_brief_negation_between_matching_captions_is_preserved(self):
        texts=['I want to leave now']*4+["I do not want to leave now"]+['I want to leave now']*4
        events=tool.make_segments([row(i,t) for i,t in enumerate(texts)])
        self.assertEqual(len(events),3)
        self.assertEqual(events[1]['text'],texts[4])

    def test_vfr_timestamps_not_frame_number(self):
        events=tool.make_segments([row(0,'one',.07,.11),row(1,'one',.11,.29),row(2,'two',.29,.9)])
        self.assertEqual([(e['start'],e['end']) for e in events],[(.07,.29),(.29,.9)])

    def test_line_layout_is_not_new_dialogue(self):
        events=tool.make_segments([row(0,'Hello\nworld'),row(1,'Hello world')])
        self.assertEqual(len(events),1)

    def test_identical_fragment_with_detector_gap_is_compacted(self):
        def visual(i,text,start,end):
            value=row(i,text,start,end)
            value['ocr']={'lines':[{'box':[.2,.8,.4,.06], 'candidates':[{'text':text,'confidence':.9}]}]}
            return value
        events=tool.make_segments([visual(0,'피',0,.04),row(1,'',.04,.08),visual(2,'피',.08,.12)])
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['start'],0)
        self.assertEqual(events[0]['end'],.12)
        self.assertIn('fragment_compacted',events[0]['flags'])

    def test_identical_text_without_geometry_keeps_real_blank_boundary(self):
        events=tool.make_segments([row(0,'피',0,.04),row(1,'',.04,.08),row(2,'피',.08,.12)])
        self.assertEqual(len(events),2)

    def test_identical_text_after_another_caption_is_not_compacted(self):
        def visual(i,text,start,end):
            value=row(i,text,start,end)
            value['ocr']={'lines':[{'box':[.2,.8,.4,.06], 'candidates':[{'text':text,'confidence':.9}]}]}
            return value
        events=tool.make_segments([visual(0,'A',0,.04),visual(1,'B',.04,.08),visual(2,'A',.08,.12)])
        self.assertEqual([event['text'] for event in events],['A','B','A'])

    def test_held_two_line_caption_does_not_split_on_dropped_line_and_suffix_noise(self):
        caption='and before I knew it I\nclimbed into his car'
        def visual(i,text,top='and before I knew it I',top_confidence=.9):
            value=row(i,text)
            value['ocr']={'lines':[
                {'box':[.18,.20,.64,.23],'candidates':[{'text':top,'confidence':top_confidence}]},
                {'box':[.21,.53,.58,.23],'candidates':[{'text':'climbed into his car','confidence':1.0}]}
            ]}
            return value
        rows=[visual(i,caption) for i in range(20)]
        rows += [visual(i,'climbed into his car',top='and before I knewit I',top_confidence=.3)
                 for i in range(20,22)]
        rows += [visual(i,'and before I knew it Iv\nclimbed into his car',top='and before I knew it Iv')
                 for i in range(22,30)]
        rows += [visual(i,caption) for i in range(30,42)]
        events=tool.make_segments(rows)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['text'],caption)
        self.assertAlmostEqual(events[0]['end'],42/30)
        self.assertIn('bracketed_ocr_flicker',events[0]['flags'])

    def test_held_caption_does_not_invent_missing_line_without_raw_ocr_evidence(self):
        caption='and before I knew it I\nclimbed into his car'
        rows=[row(i,caption) for i in range(15)]
        rows += [row(i,'climbed into his car') for i in range(15,17)]
        rows += [row(i,caption) for i in range(17,32)]
        self.assertEqual(len(tool.make_segments(rows)),3)

    def test_bracketed_real_word_substitution_stays_separate(self):
        def visual(i,text):
            value=row(i,text)
            value['ocr']={'lines':[{'box':[.2,.7,.6,.1],
                                     'candidates':[{'text':text,'confidence':1.0}]}]}
            return value
        texts=['He drove the car']*15+['He drove the cat']*3+['He drove the car']*15
        self.assertEqual([e['text'] for e in tool.make_segments([visual(i,t) for i,t in enumerate(texts)])],
                         ['He drove the car','He drove the cat','He drove the car'])

    def test_brief_opening_hyphen_flicker_does_not_create_extra_cues(self):
        full='and out poured Flame\nfamily guards in black'
        noisy='and out-poured Flame\nfamily guards in black'
        def visual(i,text):
            value=row(i,text)
            value['ocr']={'lines':[
                {'box':[.2,.2,.6,.2],'candidates':[{'text':text.splitlines()[0],'confidence':.9}]},
                {'box':[.2,.5,.6,.2],'candidates':[{'text':text.splitlines()[1],'confidence':.9}]}
            ]}
            return value
        sequence=[full]*5+[noisy]+[full]*20
        events=tool.make_segments([visual(i,t) for i,t in enumerate(sequence)])
        self.assertEqual([(e['text'],e['start'],e['end']) for e in events],[(full,0,26/30)])

    def test_recurrent_partial_hangul_syllable_is_one_held_caption(self):
        def visual(i,text):
            value=row(i,text,start=i*.04,end=(i+1)*.04)
            value['ocr']={'lines':[{'box':[.47,.45,.06,.12],
                                     'candidates':[{'text':text,'confidence':1.0}]}]}
            return value
        sequence=['피']*22+['ㅍ']*2+['피']*2+['ㅍ']+['피']*2+['ㅍ']*2+['피']*4+['ㅍ']+['피']*3
        events=tool.make_segments([visual(i,t) for i,t in enumerate(sequence)])
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['text'],'피')
        self.assertEqual(events[0]['end'],len(sequence)*.04)
        self.assertIn('recurrent_ocr_flicker',events[0]['flags'])

    def test_recurrent_missing_han_edge_glyph_is_one_caption(self):
        def visual(i,text):
            value=row(i,text)
            value['ocr']={'lines':[{'box':[.2,.7,.6,.1],
                                     'candidates':[{'text':text,'confidence':.9}]}]}
            return value
        sequence=['你现在回来']*12+['你现在回']+['你现在回来']*2+['你现在回']+['你现在回来']*12
        events=tool.make_segments([visual(i,t) for i,t in enumerate(sequence)])
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['text'],'你现在回来')

    def test_real_short_cjk_change_is_not_swallowed(self):
        def visual(i,text):
            value=row(i,text)
            value['ocr']={'lines':[{'box':[.2,.7,.6,.1],
                                     'candidates':[{'text':text,'confidence':.9}]}]}
            return value
        sequence=['你现在回来']*12+['你不要回来']*3+['你现在回来']*12
        events=tool.make_segments([visual(i,t) for i,t in enumerate(sequence)])
        self.assertEqual([e['text'] for e in events],
                         ['你现在回来','你不要回来','你现在回来'])

    def test_recurrent_noise_does_not_cross_blank_caption_boundary(self):
        def visual(i,text):
            value=row(i,text)
            value['ocr']={'lines':[{'box':[.2,.7,.6,.1],
                                     'candidates':[{'text':text,'confidence':.9}]}]} if text else {'lines':[]}
            return value
        sequence=['피']*12+['ㅍ']+['피']*3+['']*7+['피']*12
        events=tool.make_segments([visual(i,t) for i,t in enumerate(sequence)])
        self.assertEqual(len(events),2)


class ExportTests(unittest.TestCase):
    def test_timestamps_and_hour_rollover(self):
        self.assertEqual(tool.stamp(3599.9996),'01:00:00,000')
        self.assertEqual(tool.stamp(3661.23,True),'1:01:01.23')

    def test_invalid_intervals_rejected(self):
        for a,b in [(1,1),(-1,2),(1,12)]:
            with self.assertRaises(ValueError):
                tool.validate([{'id':1,'start':a,'end':b,'text':'Hi'}],10)

    def test_ass_override_text_is_not_executable(self):
        self.assertEqual(tool.ass_text('{\\pos(0,0)}\nHello'), '｛＼pos(0,0)｝\\NHello')

    def test_dual_export_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            doc={'video':{'width':544,'height':960,'duration':3},'events':[{'id':1,'start':.03448,'end':2.1,'text':"Stella’s here\nYes"}]}
            stem=Path(d)/'Episode 01'
            tool.export_files(doc,stem)
            self.assertIn('00:00:00,034 --> 00:00:02,100',(Path(str(stem)+'.srt')).read_text())
            self.assertIn('Stella’s here\\NYes',(Path(str(stem)+'.ass')).read_text())

    def test_episode_not_resolution_or_hash(self):
        self.assertEqual(tool.episode_info('Drama.S02E03.1080p'),{'season':2,'episode':3})
        self.assertEqual(tool.episode_info('第12集')['episode'],12)
        self.assertIsNone(tool.episode_info('f330ab2a23bea20b495168081dab435a')['episode'])
        self.assertIsNone(tool.episode_info('Movie.2026.1080p')['episode'])


class DecodeIntegrationTests(unittest.TestCase):
    def test_real_decode_pts_resume_and_source_change(self):
        import av
        from PIL import Image
        class FakeOCR:
            calls=0
            def recognize(self, im):
                self.calls+=1
                # Decode actual image colors; independent of input frame number.
                txt='LIGHT' if im.getpixel((10,10))[0]>100 else 'DARK'
                return {'lines':[{'box':[.1,.1,.8,.2],'candidates':[{'text':txt,'confidence':1}]}]}
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory); source=d/'vfr.mkv'
            with av.open(str(source),'w') as out:
                stream=out.add_stream('ffv1', rate=30)
                stream.width=64;stream.height=64;stream.pix_fmt='yuv420p'
                stream.time_base=Fraction(1,1000)
                stream.codec_context.time_base=Fraction(1,1000)
                for i,t in enumerate([0,40,160,200]):
                    frame=av.VideoFrame.from_image(Image.new('RGB',(64,64),'white' if i<2 else 'black'))
                    frame.pts=t;frame.time_base=Fraction(1,1000)
                    for packet in stream.encode(frame):out.mux(packet)
                for packet in stream.encode():out.mux(packet)
            meta=tool.probe(source); fake=FakeOCR()
            cache=d/'cache';cache.mkdir()
            from temporal_scan import scan_frames
            rows,first_stats=scan_frames(source,meta,(0,0,1,1),fake,cache,2,1)
            self.assertEqual(len(rows),4)
            self.assertAlmostEqual(rows[1]['end'],.16,places=3)
            self.assertEqual([e['text'] for e in tool.make_segments(rows)],['LIGHT','DARK'])
            _,stats=scan_frames(source,meta,(0,0,1,1),fake,cache,2,1)
            self.assertEqual(stats['new_ocr_frames'],0)
            self.assertEqual(fake.calls,2)
            self.assertEqual(first_stats["identical_frames_reused"],2)
            before=tool.source_fingerprint(source)
            source.write_bytes(source.read_bytes()+b'changed')
            self.assertNotEqual(before,tool.source_fingerprint(source))


if __name__=='__main__':
    unittest.main()
