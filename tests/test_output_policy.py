import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from output_policy import aligned_stem,output_stems
from safe_export import write_pair

class OutputTests(unittest.TestCase):
    def test_exact_video_names_across_platforms(self):
        self.assertEqual(aligned_stem('/out',r'C:\series\剧集.S01E01.reviewed.mp4').name,'剧集.S01E01.reviewed')
        self.assertEqual(aligned_stem('/out','/video/My Show.01.1080p.mkv').name,'My Show.01.1080p')
    def test_collision_isolation_preserves_stems(self):
        entries=[('/a/EP01.mp4','EP01.mp4'),('/b/EP01.mkv','EP01.mkv'),('/b/EP02.mp4','season/EP02.mp4')]
        stems=output_stems(entries,'/out')
        self.assertNotEqual(stems[0].parent,stems[1].parent)
        self.assertEqual([p.name for p in stems],['EP01','EP01','EP02'])
        self.assertEqual(stems[2],Path('/out/season/EP02'))
        self.assertEqual(output_stems(reversed(entries),'/out'),list(reversed(stems)))
    def test_case_collisions_and_traversal(self):
        stems=output_stems([('/a/A.mp4','A.mp4'),('/b/a.mkv','a.mkv')],'/out')
        self.assertNotEqual(stems[0].parent,stems[1].parent)
        with self.assertRaises(ValueError):output_stems([('/a.mp4','../a.mp4')],'/out')
    def test_backup_and_rollback_second_replace_failure(self):
        import safe_export
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'01.srt',Path(d)/'01.ass';a.write_text('old srt');b.write_text('old ass')
            replace=safe_export.os.replace
            def fail_second(source,dest):
                if Path(dest)==b and str(source).endswith('.tmp'):raise OSError('simulated disk failure')
                return replace(source,dest)
            with patch.object(safe_export.os,'replace',side_effect=fail_second):
                with self.assertRaises(OSError):write_pair({a:'new srt',b:'new ass'},backup=True)
            self.assertEqual(a.read_text(),'old srt');self.assertEqual(b.read_text(),'old ass')
            write_pair({a:'new srt',b:'new ass'},backup=True)
            self.assertEqual(a.read_text(),'new srt');self.assertTrue(list(Path(d).glob('.ellapuede-history/*/01.srt')))
if __name__=='__main__':unittest.main()
