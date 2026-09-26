import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import subtitle_ocr as core
class AutoExportTests(unittest.TestCase):
    def test_report_failure_does_not_block_subtitles(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=root/'片名.S01E01.mp4';video.write_bytes(b'fixture')
            args=SimpleNamespace(output=root,roi=(0,0,1,1),language=['auto'],scale=1,workers=1,overwrite=False,subtitle_stem=root/'export/片名.S01E01',evidence_report=False)
            pool=SimpleNamespace(words=[],name='test')
            meta={'width':64,'height':64,'duration':2}
            rows=[{'frame':i,'start':i/30,'end':(i+1)/30,'text':'Hello','confidence':1,'ocr':{'lines':[]}} for i in range(30)]
            def calibrate(path,meta,pool,cache,roi):
                Image.new('RGB',(64,64)).save(cache/'calibration.jpg');return {'roi':[0,0,1,1]}
            with patch.object(core,'probe',return_value=meta),patch.object(core,'calibrate',side_effect=calibrate),patch('temporal_scan.scan_frames',return_value=(rows,{})),patch.object(core,'write_diagnostics',side_effect=OSError('report unavailable')),patch.object(core,'evidence_and_report') as evidence,patch.object(core.control,'CONTROL',None):
                result=core.run_one(video,root/'识别记录/片名.S01E01',args,pool)
            self.assertEqual(result['status'],'completed_exported')
            self.assertTrue((root/'export/片名.S01E01.srt').exists())
            self.assertTrue((root/'export/片名.S01E01.ass').exists())
            evidence.assert_not_called()

    def test_normal_export_skips_counterfactual_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=root/'E01.mp4';video.write_bytes(b'fixture')
            args=SimpleNamespace(output=root,roi=(0,0,1,1),language=['en-US'],scale=1,workers=1,overwrite=False,subtitle_stem=root/'export/E01',evidence_report=False)
            pool=SimpleNamespace(words=[],name='test',languages=['en-US'])
            meta={'width':64,'height':64,'duration':2}
            rows=[{'frame':i,'start':i/30,'end':(i+1)/30,'text':'Hello','confidence':1,'ocr':{'lines':[]}} for i in range(30)]
            with patch.object(core,'probe',return_value=meta),patch.object(core,'calibrate',return_value={'roi':[0,0,1,1]}),patch('temporal_scan.scan_frames',return_value=(rows,{})),patch('segmentation_diagnostics.analyze',side_effect=RuntimeError('diagnostic unavailable')) as diagnostic,patch.object(core.control,'CONTROL',None):
                result=core.run_one(video,root/'records/E01',args,pool)
            self.assertEqual(result['status'],'completed_exported')
            diagnostic.assert_not_called()
            self.assertNotIn('segmentation_diagnostics',(root/'records/E01.subtitles.json').read_text())
            for suffix in ('srt','ass'):
                self.assertIn('Hello',(root/f'export/E01.{suffix}').read_text())
if __name__=='__main__':unittest.main()
