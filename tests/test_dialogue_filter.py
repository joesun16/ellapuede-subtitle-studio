import unittest,tempfile
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PIL import Image
import subtitle_ocr as core
from dialogue_filter import filter_lines,prune_isolated_small_lines,typical_height,restore_connected_fades

class DialogueRegionTests(unittest.TestCase):
    def test_small_orphan_glyph_above_full_dialogue_is_removed(self):
        image=Image.new('RGB',(1000,250))
        subtitle={'box':[.30,.46,.39,.22],
                  'candidates':[{'text':'สวัสดีครับ','confidence':.98}]}
        overlay={'box':[.63,.36,.035,.11],
                 'candidates':[{'text':'9','confidence':.99}]}
        self.assertEqual(filter_lines({'lines':[overlay,subtitle]},image,0)['lines'],[subtitle])
        self.assertEqual(filter_lines({'lines':[overlay]},image,0)['lines'],[overlay])

    def test_small_embedded_or_below_glyph_is_removed_without_harming_short_dialogue(self):
        subtitle={'box':[.27,.36,.45,.23],
                  'candidates':[{'text':'เรากลับบ้านกัน','confidence':.98}]}
        below={'box':[.29,.57,.02,.07],
               'candidates':[{'text':'9','confidence':.99}]}
        embedded={'box':[.69,.38,.03,.08],
                  'candidates':[{'text':'A','confidence':.99}]}
        equal_size={'box':[.30,.62,.30,.22],
                    'candidates':[{'text':'5','confidence':.98}]}
        result=prune_isolated_small_lines({'lines':[below,subtitle,embedded]})
        self.assertEqual(result['lines'],[subtitle])
        self.assertEqual(len(result['excluded_small_overlay_lines']),2)
        self.assertEqual(prune_isolated_small_lines({'lines':[below]})['lines'],[below])
        self.assertEqual(prune_isolated_small_lines({'lines':[subtitle,equal_size]})['lines'],[subtitle,equal_size])

    def test_role_labels_do_not_widen_dominant_dialogue_region(self):
        class OCR:
            n=0
            def recognize(self,image):
                self.n+=1
                def line(text,y,h):return {'box':[.2,y,.6,h],'candidates':[{'text':text,'confidence':1}]}
                return {'lines':[line('dialogue '+str(self.n),.65,.03),line('small overlay '+str(self.n),.61,.012)]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(core,'frame_at',return_value=Image.new('RGB',(1000,1000))):
            result=core.calibrate(Path('video.mp4'),{'duration':100},OCR(),Path(tmp))
        self.assertGreater(result['roi'][1],.62)
        self.assertLess(result['roi'][3],.71)
        self.assertAlmostEqual(result['font_height'],.03)
    def test_pixel_scale_survives_nested_crops_and_keeps_dialogue(self):
        image=core.image_crop(Image.new('RGB',(1000,1000)),(0,.5,1,.8),2)
        image=core.image_crop(image,(0,0,1,.5),2)
        lines=[{'box':[0,0,1,40/image.height],'candidates':[]},{'box':[0,0,1,160/image.height],'candidates':[]}]
        result=filter_lines({'lines':lines},image,30)
        self.assertEqual(result['lines'],[lines[1]])
        self.assertEqual(len(filter_lines({'lines':lines},image,0)['lines']),2)
    def test_learned_korean_font_rejects_large_scenery_and_small_overlay(self):
        image=Image.new('RGB',(544,100))
        lines=[{'box':[0,0,.4,h/100],'candidates':[]} for h in [20,45,51,97]]
        result=filter_lines({'lines':lines},image,30,82)
        self.assertEqual(result['lines'],lines[1:3])

    def test_actual_glyph_coverage_rejects_large_ocr_box_around_tiny_overlay(self):
        image=Image.new('RGB',(400,100))
        mask=np.zeros((100,400),dtype=bool)
        mask[30:65,40:220]=True
        mask[20:23,250:280]=True
        image.info['ellapuede_text_mask']=mask
        caption={'box':[.1,.2,.45,.55],'candidates':[{'text':'对白','confidence':.9}]}
        overlay={'box':[.6,.1,.2,.55],'candidates':[{'text':'滚动评论','confidence':.9}]}
        result=filter_lines({'lines':[caption,overlay]},image,20,minimum_mask_density=.04)
        self.assertEqual(result['lines'],[caption])
        # An uncalibrated/plain subtitle style keeps the older height rule.
        self.assertEqual(filter_lines({'lines':[caption,overlay]},image,20)['lines'],[caption,overlay])

    def test_fading_caption_keeps_ocr_observed_text_but_not_unrelated_overlay(self):
        def line(text,y=.3,h=.4):
            return {'box':[.2,y,.6,h],'candidates':[{'text':text,'confidence':.9}]}
        rows=[]
        for i in range(6):
            caption=line('真的');overlay=line('评论',.7,.2)
            visible=i<3
            ocr={'lines':[caption] if visible else [],
                 'excluded_mask_lines':[] if visible else [caption] if i<5 else [overlay]}
            rows.append({'start':i*.04,'end':(i+1)*.04,'text':'真的' if visible else '',
                         'confidence':.9 if visible else 0,'ocr':ocr})
        self.assertEqual(restore_connected_fades(rows),2)
        self.assertEqual([r['text'] for r in rows],['真的']*5+[''])

    def test_mixed_fonts_do_not_create_unreliable_height_filter(self):
        values=[.01,.01,.04,.04,.09,.09]
        self.assertIsNone(typical_height([{'text':'text','box':[0,0,1,h]} for h in values]))
    def test_old_auto_region_upgrades_once_manual_is_preserved(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'series.json';meta={'width':1000,'height':1000};args=SimpleNamespace(roi=None,series_file=p)
            p.write_text(json.dumps({'aspect':1,'roi':[.1,.4,.9,.9],'automatic':True}))
            with patch.object(core,'calibrate',return_value={'roi':[.1,.6,.9,.8],'automatic':True}) as calibrate:
                core.resolve_series_region(root/'E1',meta,Mock(),root,args);core.resolve_series_region(root/'E2',meta,Mock(),root,args)
                calibrate.assert_called_once()
            p.write_text(json.dumps({'aspect':1,'roi':[.1,.4,.9,.9],'automatic':False}))
            with patch.object(core,'calibrate') as calibrate:
                result=core.resolve_series_region(root/'E1',meta,Mock(),root,args);calibrate.assert_not_called()
                self.assertEqual(result['roi'],[.1,.4,.9,.9])
