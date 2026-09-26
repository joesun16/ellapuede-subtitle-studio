import tempfile
import unittest
from pathlib import Path
import subtitle_ocr as core


class FormatTests(unittest.TestCase):
    def test_only_selected_files_are_written(self):
        doc={'video':{'width':1920,'height':1080,'duration':3},
             'events':[{'id':1,'start':0,'end':2,'text':'Hello\n世界'}]}
        for choice,expected in [('srt',{'srt'}),('ass',{'ass'}),('both',{'srt','ass'})]:
            with self.subTest(choice=choice),tempfile.TemporaryDirectory() as temp:
                stem=Path(temp)/'片名.S01E01'
                core.export_files(doc,stem,format=choice)
                self.assertEqual({p.suffix[1:] for p in Path(temp).iterdir()},expected)
                for ext in expected:self.assertIn('世界',Path(str(stem)+'.'+ext).read_text(encoding='utf-8'))

    def test_other_format_is_not_modified(self):
        doc={'video':{'width':100,'height':100,'duration':3},
             'events':[{'id':1,'start':0,'end':2,'text':'Hello'}]}
        with tempfile.TemporaryDirectory() as temp:
            stem=Path(temp)/'E01';existing=stem.with_suffix('.ass')
            existing.write_text('externally edited',encoding='utf-8')
            core.export_files(doc,stem,format='srt')
            self.assertEqual(existing.read_text(),'externally edited')

    def test_invalid_format_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):core.export_files({},Path(temp)/'E01',format='txt')
            self.assertEqual(list(Path(temp).iterdir()),[])
