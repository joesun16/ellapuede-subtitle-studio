import unittest
import numpy as np
from PIL import Image,ImageDraw
import frame_features as f
class FeatureTests(unittest.TestCase):
    def test_native_matches_reference_on_edges_and_components(self):
        if f.glyph_features is None:self.skipTest('native extension built during packaging')
        for seed in range(5):
            im=Image.fromarray(np.random.default_rng(seed).integers(0,256,(45,91),dtype=np.uint8))
            np.testing.assert_array_equal(f.text_mask(im),f.python_text_mask(im))
        im=Image.new('RGB',(522,140),'black');d=ImageDraw.Draw(im);d.text((2,0),'Hello world',fill='white',font_size=24);d.text((230,80),'it',fill='white',font_size=20)
        np.testing.assert_array_equal(f.text_mask(im),f.python_text_mask(im))
    def test_local_short_word_change_is_detected(self):
        a=np.zeros((120,522),dtype=bool);a[10:30,20:500]=True;b=a.copy();b[80:90,250:253]=True
        self.assertTrue(f.changed(a,b));self.assertFalse(f.changed(a,a))
    def test_native_rejects_invalid_buffer(self):
        if f.glyph_features is None:self.skipTest('native extension built during packaging')
        with self.assertRaises(ValueError):f.glyph_features.mask(b'123',2,2)
        with self.assertRaises(ValueError):f.glyph_features.mask(b'',-1,2)
if __name__=='__main__':unittest.main()
