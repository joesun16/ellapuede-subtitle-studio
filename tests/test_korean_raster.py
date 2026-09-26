import unittest
from unittest.mock import patch
from PIL import Image
from korean_raster import repair
from hardware_policy import resolve_engine
from pathlib import Path

class KoreanRasterTests(unittest.TestCase):
    def setUp(self):self.image=Image.new('RGB',(500,100));self.plan={'words':[self.image,self.image],'word_count':2,'punctuation':[]}
    def line(self,text):return {'box':[0,0,1,1],'candidates':[{'text':text,'confidence':.99}]}
    def test_character_gaps_are_not_treated_as_word_spaces(self):
        from korean_raster import prepare
        image=Image.open(Path(__file__).resolve().parent.parent/'assets/smoke-korean.png')
        self.assertEqual(prepare(image,(0,0,1,1))['word_count'],3)
    def test_space_requires_visible_gaps_and_identical_recognized_letters(self):
        with patch('korean_raster.prepare',return_value=self.plan):
            result=repair(self.image,[self.line('좋은날')],lambda ims:[('좋은',.98),('날',.98)])
            self.assertEqual(result[0]['candidates'][0]['text'],'좋은 날')
            original=[self.line('좋은날')]
            self.assertEqual(repair(self.image,original,lambda ims:[('건강',.99),('마',.99)]),original)
    def test_no_geometric_evidence_means_no_text_rewrite(self):
        with patch('korean_raster.prepare',return_value=None):
            original=[self.line('좋은날')]
            self.assertEqual(repair(self.image,original,lambda ims:self.fail('Unexpected OCR')),original)
    def test_punctuation_repair_requires_two_matching_current_image_readings(self):
        plan={'words':[self.image],'word_count':1,'punctuation':[self.image,self.image]}
        with patch('korean_raster.prepare',return_value=plan):
            original=[self.line('안녀하세요!')]
            result=repair(self.image,original,lambda ims:[('안녕하세요!',.96),('안녕하세요!',.97)])
            self.assertEqual(result[0]['candidates'][0]['text'],'안녕하세요!')
            self.assertEqual(repair(self.image,original,lambda ims:[('안녕하세요!',.96),('안녀하세요!',.97)]),original)
            self.assertEqual(repair(self.image,original,lambda ims:[('안녕하세요!',.60),('안녕하세요!',.97)]),original)
    def test_detected_exclamation_can_be_recovered_without_deleting_spaces(self):
        plan={'words':[self.image],'word_count':1,'punctuation':[self.image,self.image]}
        with patch('korean_raster.prepare',return_value=plan):
            result=repair(self.image,[self.line('안녀하세요')],lambda ims:[('안녕하세요!',.96),('안녕하세요!',.97)])
            self.assertEqual(result[0]['candidates'][0]['text'],'안녕하세요!')
            result=repair(self.image,[self.line('좋은 하루!')],lambda ims:[('좋은하루!',.96),('좋은하루!',.97)])
            self.assertEqual(result[0]['candidates'][0]['text'],'좋은 하루!')
    def test_auto_engine_uses_available_platform_capabilities(self):
        self.assertEqual(resolve_engine('auto','ko-KR','Darwin'),'vision')
        self.assertEqual(resolve_engine('auto',['ko-KR'],'Windows'),'rapid')
        self.assertEqual(resolve_engine('auto','en-US','Darwin'),'vision')
        self.assertEqual(resolve_engine('vision','ko-KR','Darwin'),'vision')

class ColoredBackgroundSpacingTests(unittest.TestCase):
    def test_warm_highlights_do_not_fill_the_visible_word_gap(self):
        from PIL import ImageDraw,ImageFont
        image=Image.new('RGB',(250,80),'black');draw=ImageDraw.Draw(image)
        font=ImageFont.load_default(size=36)
        draw.text((12,18),'AA',fill='white',font=font)
        draw.text((135,18),'BB',fill='white',font=font)
        # Small warm highlights resemble pale fabric within the word gap.
        for x in range(70,130,8):draw.rectangle((x,28,x+3,42),fill=(255,225,200))
        line={'box':[0,0,1,1],'candidates':[{'text':'가나다라','confidence':.99}]}
        def read(images):
            self.assertEqual(len(images),2)
            return [('가나',.99),('다라',.99)]
        self.assertEqual(repair(image,[line],read)[0]['candidates'][0]['text'],'가나 다라')
