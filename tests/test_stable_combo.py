import sys
import unittest

from PySide6.QtWidgets import QApplication

from stable_combo import StableComboBox


@unittest.skipUnless(sys.platform == 'darwin', 'Only macOS replaces the Qt list popup')
class StableComboTests(unittest.TestCase):
    def test_menu_selection_survives_background_model_refresh(self):
        app = QApplication.instance() or QApplication([])
        box = StableComboBox()
        box.addItem('默认值', None)
        box.addItem('第一部剧', 'series-1')
        box.addItem('第二部剧', 'series-2')
        box.showPopup()
        menu = box._menu
        self.assertIsNotNone(menu)
        # Queue refresh replaces the items while the selector is visible.
        box.clear()
        box.addItem('默认值', None)
        box.addItem('第二部剧', 'series-2')
        box.addItem('第一部剧', 'series-1')
        menu.actions()[1].trigger()
        app.processEvents()
        self.assertEqual(box.currentData(), 'series-1')
        menu.hide()
        app.processEvents()


if __name__ == '__main__':
    unittest.main()
