import os,plistlib,tempfile,unittest
from pathlib import Path
from mac_bundle import validate_app

class MacBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Path(self.tmp.name)/'EllaPuede.app';self.info={'CFBundlePackageType':'APPL','CFBundleExecutable':'EllaPuede','CFBundleIdentifier':'com.ellapuede.subtitle-studio','LSBackgroundOnly':False,'LSUIElement':False,'CFBundleIconFile':'icon.icns'}
        for name in ['MacOS','Resources']:(self.app/'Contents'/name).mkdir(parents=True)
        for name in ['EllaPuede','EllaPuedeWorker']:
            p=self.app/'Contents/MacOS'/name;p.write_text('fixture');p.chmod(0o755)
        (self.app/'Contents/Resources/icon.icns').write_bytes(b'fixture');self.write()
    def write(self):(self.app/'Contents/Info.plist').write_bytes(plistlib.dumps(self.info))
    def tearDown(self):self.tmp.cleanup()
    def test_foreground_application_validates(self):self.assertEqual(validate_app(self.app)['CFBundleExecutable'],'EllaPuede')
    def test_background_application_is_rejected(self):
        self.info['LSBackgroundOnly']=True;self.write()
        with self.assertRaisesRegex(ValueError,'LSBackgroundOnly'):validate_app(self.app)
    def test_agent_application_is_rejected(self):
        self.info['LSUIElement']=True;self.write()
        with self.assertRaisesRegex(ValueError,'LSUIElement'):validate_app(self.app)
    def test_worker_cannot_be_main_executable(self):
        self.info['CFBundleExecutable']='EllaPuedeWorker';self.write()
        with self.assertRaisesRegex(ValueError,'CFBundleExecutable'):validate_app(self.app)
