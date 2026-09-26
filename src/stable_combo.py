"""A native-looking selector that avoids Qt's unstable macOS list popup."""
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QComboBox, QMenu


class StableComboBox(QComboBox):
    def showPopup(self):
        if sys.platform != 'darwin':
            return super().showPopup()
        # Qt 6.8's QListView popup can crash while Cocoa posts an accessibility
        # selection notification. A menu has no QListView/currentChanged path.
        if getattr(self, '_menu', None) is not None:
            return
        menu = QMenu(self)
        menu.setMinimumWidth(self.width())
        for index in range(self.count()):
            title, value = self.itemText(index), self.itemData(index)
            action = menu.addAction(title)
            action.setEnabled(bool(self.model().flags(self.model().index(index, 0)) & Qt.ItemFlag.ItemIsEnabled))
            action.setCheckable(True)
            action.setChecked(index == self.currentIndex())
            action.triggered.connect(lambda checked=False, i=index, t=title, v=value: self._choose_menu_item(i,t,v))
        self._menu = menu
        menu.aboutToHide.connect(self._clear_menu)
        menu.popup(self.mapToGlobal(QPoint(0, self.height())))

    def _choose_menu_item(self, index, title, value):
        # The queue can refresh while this menu is open. Resolve against the
        # current model rather than trusting a stale popup row number.
        if index >= self.count() or self.itemText(index) != title or self.itemData(index) != value:
            index = self.findData(value) if value is not None else self.findText(title)
        if 0 <= index < self.count():
            self.setCurrentIndex(index)
            self.activated.emit(index)

    def _clear_menu(self):
        menu = self._menu
        self._menu = None
        if menu is not None:
            menu.deleteLater()
