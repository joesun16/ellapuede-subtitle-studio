import unittest
import numpy as np
from spacing_refine import same_layout


class SpacingEvidenceTests(unittest.TestCase):
    def test_equal_glyph_layout_passes_but_visible_space_change_does_not(self):
        a=np.zeros((40,120),dtype=bool);a[10:30,10:20]=True;a[10:30,30:40]=True;a[10:30,60:70]=True
        self.assertTrue(same_layout(a,a.copy(),[[0,0,1,1]]))
        b=a.copy();b[:,60:70]=False;b[10:30,80:90]=True
        self.assertFalse(same_layout(a,b,[[0,0,1,1]]))
        self.assertFalse(same_layout(np.zeros_like(a),np.zeros_like(a),[[0,0,1,1]]))
