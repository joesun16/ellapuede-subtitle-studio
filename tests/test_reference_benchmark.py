import tempfile
import unittest
from pathlib import Path
from tools.reference_benchmark import read_events,evaluate

class ReferenceBenchmarkTests(unittest.TestCase):
    def test_formats_normalize_wrap_but_preserve_accents_and_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            ass=Path(tmp)/'test.ass';srt=Path(tmp)/'test.srt'
            ass.write_text('[Events]\nFormat: Layer, Start, End, Text\nDialogue: 0,0:00:01.20,0:00:02.30,{\\i1}été\\N2',encoding='utf-8-sig')
            srt.write_text('1\n00:00:01,200 --> 00:00:02,300\nété 2\n',encoding='utf-8')
            report=evaluate(read_events(ass),read_events(srt))
            self.assertEqual(report['character_error_rate'],0)
            self.assertEqual(report['exact_boundary_p95'],0)
            srt.write_text('1\n00:00:01,200 --> 00:00:02,300\nete 3\n')
            self.assertGreater(evaluate(read_events(ass),read_events(srt))['character_error_rate'],0)
    def test_split_cues_are_not_hidden_by_text_normalization(self):
        ref=[dict(start=1.,end=3.,text='hello')]
        result=[dict(start=1.,end=2.,text='hello'),dict(start=2.,end=3.,text='hello')]
        report=evaluate(ref,result)
        self.assertEqual(report['unmatched_output_cues'],1)
        self.assertEqual(report['adjacent_repeat_indices'],[1])
        self.assertGreater(report['character_error_rate'],0)
    def test_identical_text_far_away_cannot_supply_missing_reference(self):
        report=evaluate([dict(start=1.,end=2.,text='yes')],[dict(start=40.,end=41.,text='yes')])
        self.assertEqual(report['exact_cues'],0)
        self.assertEqual(report['unmatched_reference_cues'],1)
        self.assertEqual(report['unmatched_output_cues'],1)
