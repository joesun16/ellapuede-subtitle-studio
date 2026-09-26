import unittest
from hardware_policy import plan,validate_languages,default_memory_limit,LANGUAGES,language_name,resolve_engine
class PolicyTests(unittest.TestCase):
    def test_low_memory_caps_parallelism(self):
        p=plan('rapid',2,16,{'available_gb':2,'logical_cpus':32})
        self.assertEqual(p['workers'],1)
    def test_cpu_thread_budget(self):
        p=plan('rapid',2,16,{'available_gb':32,'logical_cpus':2})
        self.assertEqual(p['workers']*p['threads'],1)
    def test_language_validation(self):
        validate_languages(['zh-Hans','en-US','ko-KR'])
        with self.assertRaises(ValueError):validate_languages(['ru-RU'])
    def test_korean_uses_the_same_ui_label_style_as_other_languages(self):
        self.assertEqual(dict((code,name) for name,code in LANGUAGES)['ko-KR'],'韩语')
        self.assertEqual(language_name('ko-KR'),'韩语')
        self.assertEqual(language_name('th-TH'),'泰语')
        self.assertEqual(resolve_engine('auto','th-TH','Darwin',macos_major=15),'vision')
        self.assertEqual(resolve_engine('auto','th-TH','Darwin',macos_major=14),'rapid')
        self.assertEqual(resolve_engine('auto','th-TH','Windows'),'rapid')
    def test_large_windows_cpu_can_use_more_lanes_without_changing_ocr_rules(self):
        h={'available_gb':24,'logical_cpus':32,'physical_cpus':16}
        counts=[plan('rapid',mode,12,h)['workers'] for mode in range(3)]
        self.assertEqual(counts,[2,4,6])
        gpu=plan('rapid',2,12,h,device='gpu')
        self.assertEqual(gpu['workers'],2)
        self.assertEqual(gpu['limited_by'],'显卡会话保护')
        self.assertEqual(default_memory_limit({'total_gb':8}),4)
        self.assertEqual(default_memory_limit({'total_gb':32}),12)
if __name__=='__main__':unittest.main()
