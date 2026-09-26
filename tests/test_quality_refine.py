import unittest
import subtitle_ocr as core
from quality_refine import unstable_frames

def rows(texts):
    return [{'frame':i,'start':i/30,'end':(i+1)/30,'text':text,'confidence':.9 if text else 0,
             'ocr':{'lines':[{'box':[.1,.55,.8,.2],'candidates':[{'text':text,'confidence':.9}]}] if text else []}}
            for i,text in enumerate(texts)]

class QualityRefineTests(unittest.TestCase):
    def test_short_missing_line_is_checked_against_current_image(self):
        full='Hello there\nplease come in'
        sequence=[full]*8+['please come in']+[full]*8
        self.assertIn(8,unstable_frames(rows(sequence)))

    def test_boundary_gaps_are_not_sent_to_expensive_ocr_recheck(self):
        texts=['']*5+['Hello']*20+['']*10+['World']*20+['']*5
        self.assertEqual(unstable_frames(rows(texts)),[])
        internal=['Hello']*20+['']*2+['Hello']*20
        self.assertEqual(unstable_frames(rows(internal)),[20,21])
        longer=['Hello']*20+['']*9+['Hello']*20
        self.assertEqual(unstable_frames(rows(longer)),list(range(20,29)))
    def test_held_caption_flicker_shares_cue_but_protected_word_change_survives(self):
        sequence=['Ijust accidentally bumped into']*10+['I just accidentally bumped into']*2+['Ijust accidentally bumped into']*10
        events=core.make_segments(rows(sequence))
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['text'],'Ijust accidentally bumped into')
        self.assertIn('ocr_spacing_compacted',events[0]['flags'])
        for changed in ('Take 900 dollars',"I can't leave"):
            base='Take 100 dollars' if changed.startswith('Take') else 'I can leave'
            self.assertEqual(len(core.make_segments(rows([base]*10+[changed]*2+[base]*10))),3)
