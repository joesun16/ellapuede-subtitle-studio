import tempfile,unittest,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
import subtitle_ocr as core
from series_policy import series_key,series_jobs,recognition_options

class SeriesTests(unittest.TestCase):
    def test_all_performance_modes_have_identical_content_configuration(self):
        self.assertEqual(recognition_options(0),recognition_options(1));self.assertEqual(recognition_options(1),recognition_options(2))
    def test_series_scope_does_not_mix_folders(self):
        a={'source':'/A/e1.mp4','series':'/A'};b={'source':'/A/season/e2.mp4','series':'/A'};c={'source':'/B/e1.mp4','series':'/B'}
        self.assertEqual(series_jobs([a,b,c],[a]),[a,b])
    def test_calibrate_once_for_two_episodes_and_refuse_aspect_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=SimpleNamespace(roi=None,series_file=root/'series.json');meta={'width':1280,'height':720};pool=Mock()
            with patch.object(core,'calibrate',return_value={'roi':[.1,.7,.9,.95],'automatic':True}) as calibrate:
                first=core.resolve_series_region(root/'E01.mp4',meta,pool,root,args)
                second=core.resolve_series_region(root/'E02.mp4',meta,pool,root,args)
                calibrate.assert_called_once();self.assertEqual(first['roi'],second['roi'])
                with self.assertRaisesRegex(ValueError,'画幅'):core.resolve_series_region(root/'E03.mp4',{'width':720,'height':1280},pool,root,args)
    def test_manual_series_region_never_runs_ocr_or_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=SimpleNamespace(roi=[.1,.7,.9,.95],series_file=root/'series.json')
            with patch.object(core,'calibrate') as calibrate,patch.object(core,'frame_at') as frame:
                core.resolve_series_region(root/'E01.mp4',{'width':1280,'height':720},Mock(),root,args)
                calibrate.assert_not_called();frame.assert_not_called()
    def test_output_is_subtitles_only_with_private_resume_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'E01.mp4';video.write_bytes(b'fake');out=root/'out';out.mkdir();cache=root/'internal'
            args=SimpleNamespace(output=out,cache_root=cache,series_file=root/'series.json',roi=(.1,.7,.9,.95),language=['en-US'],scale=2,workers=1,overwrite=False,subtitle_stem=out/'E01',evidence_report=False,format='both')
            rows=[{'frame':i,'start':i/10,'end':(i+1)/10,'text':'Hello','confidence':1,'ocr':{'lines':[]}} for i in range(10)]
            meta={'width':1280,'height':720,'duration':1}
            with patch.object(core,'calibrate',return_value={'roi':args.roi,'font_height':.04}),patch.object(core,'probe',return_value=meta),patch('temporal_scan.scan_frames',return_value=(rows,{})),patch.object(core,'write_diagnostics') as report,patch.object(core.control,'CONTROL',None):
                stem=core.private_result_stem(video,args.subtitle_stem,args);core.run_one(video,stem,args,SimpleNamespace(words=[],name='mock'))
                report.assert_not_called()
            self.assertEqual({p.name for p in out.iterdir()},{'E01.srt','E01.ass'})
            self.assertTrue(Path(str(stem)+'.subtitles.json').exists())
    def test_scanners_never_receive_text_outside_dialogue_roi(self):
        import av
        class OCR:
            def recognize(self,im):
                self.check(im)
                return {'lines':[{'box':[.1,.1,.8,.5],'candidates':[{'text':'DIALOGUE','confidence':1}]}]}
            def check(self,im):
                self_outer.assertTrue(all(v>245 for v in im.getpixel((im.width//2,im.height//2))))
                self_outer.assertLess(im.height,50)
        self_outer=self
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);v=root/'caption.mkv';im=Image.new('RGB',(160,160),'black')
            # Bright subtitle strip; surrounding picture is excluded before OCR.
            from PIL import ImageDraw
            ImageDraw.Draw(im).rectangle((0,120,159,143),fill='white')
            with av.open(str(v),'w') as c:
                st=c.add_stream('ffv1',rate=10);st.width=160;st.height=160;st.pix_fmt='yuv420p'
                for _ in range(3):
                    for packet in st.encode(av.VideoFrame.from_image(im)):c.mux(packet)
                for packet in st.encode():c.mux(packet)
            for workers in (1,2,4):
                cache=root/str(workers);cache.mkdir();rows,_=__import__('temporal_scan').scan_frames(v,core.probe(v),(0,.75,1,.9),OCR(),cache,workers,1)
                self.assertEqual({r['text'] for r in rows},{'DIALOGUE'})
if __name__=='__main__':unittest.main()
