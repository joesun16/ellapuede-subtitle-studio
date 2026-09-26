import unittest
from types import SimpleNamespace
import numpy as np
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hardware_policy import LANGUAGES, plan
from model_manifest import MODELS
from ocr_routes import LANGUAGE_ROUTES, ROUTES, select_route


class PortableRouteTests(unittest.TestCase):
    def test_every_language_offered_has_an_explicit_model(self):
        offered={code for _, entry in LANGUAGES for code in entry.split(',')}
        self.assertEqual(offered,set(LANGUAGE_ROUTES))
        for code,route in LANGUAGE_ROUTES.items():
            self.assertEqual(select_route([code]),route)
            for key in ('det','rec'):
                self.assertIn(ROUTES[route][key],MODELS)

    def test_unknown_combination_does_not_silently_use_chinese(self):
        with self.assertRaises(ValueError):select_route(['fr-FR','de-DE'])

    def test_physical_core_and_memory_caps_each_mode(self):
        hardware={'available_gb':8,'logical_cpus':16,'physical_cpus':4}
        counts=[plan('rapid',mode,8,hardware)['workers'] for mode in range(3)]
        self.assertEqual(counts,[1,2,3])
        constrained=plan('rapid',2,8,{'available_gb':1.5,'logical_cpus':16,'physical_cpus':4})
        self.assertEqual(constrained['workers'],1)
        self.assertEqual(constrained['limited_by'],'可用内存')

    def test_compute_device_does_not_change_language_model(self):
        from subtitle_ocr import RapidPool
        with TemporaryDirectory() as tmp,patch('subtitle_ocr.ROOT',Path(tmp)):
            models=Path(tmp)/'models';models.mkdir()
            for kind in ('det','rec'):(models/ROUTES['en_v5'][kind]).touch()
            pools=[RapidPool(['en-US'],[],1,device) for device in ('auto','cpu','gpu')]
            try:
                self.assertEqual({p.route for p in pools},{'en_v5'})
                self.assertEqual({p.name for p in pools},{pools[0].name})
                for pool,device in zip(pools,('auto','cpu','gpu')):
                    command=pool.command()
                    self.assertEqual(command[command.index('--device')+1],device)
                first=pools[0].spawn_command();second=pools[0].spawn_command()
                self.assertEqual(first[first.index('--device')+1],'auto')
                self.assertEqual(second[second.index('--device')+1],'cpu')
            finally:
                for pool in pools:pool.close()

    def test_gpu_sample_must_preserve_text_boxes_and_scores(self):
        from portable_ocr_worker import same_ocr_reading
        reading=lambda text,shift,score:SimpleNamespace(txts=[text],boxes=np.array([[[10+shift,10],[30+shift,10],[30+shift,30],[10+shift,30]]]),scores=[score])
        cpu=reading('Hello',0,.96)
        self.assertTrue(same_ocr_reading(cpu,reading('Hello',1,.95),600,120))
        self.assertFalse(same_ocr_reading(cpu,reading('Hella',0,.96),600,120))
        self.assertFalse(same_ocr_reading(cpu,reading('Hello',8,.96),600,120))
        self.assertFalse(same_ocr_reading(cpu,reading('Hello',0,.8),600,120))


if __name__=='__main__':unittest.main()
