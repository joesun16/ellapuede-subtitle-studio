"""Shared native desktop layout tokens. Dimensions are Qt logical pixels."""
from pathlib import Path
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QPushButton,QComboBox,QLineEdit,QDoubleSpinBox,QAbstractSpinBox,QToolButton,QToolTip
CONTROL_HEIGHT=40
GAP=12
PAGE_MARGIN=24
RADIUS=8

def info_icon(message):
    """One compact, keyboard-accessible help affordance for contextual hints."""
    icon=QToolButton()
    icon.setObjectName('infoIcon')
    icon.setText('!')
    icon.setFixedSize(22,22)
    icon.setCursor(Qt.CursorShape.PointingHandCursor)
    icon.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    icon.setAccessibleName('说明')
    icon.setToolTip(message)
    icon.clicked.connect(lambda:QToolTip.showText(QCursor.pos(),icon.toolTip(),icon))
    return icon

def polish_controls(parent):
    for kind in (QPushButton,QComboBox,QLineEdit,QDoubleSpinBox):
        for w in parent.findChildren(kind):
            if isinstance(w,QLineEdit) and isinstance(w.parent(),(QAbstractSpinBox,QComboBox)):continue
            w.ensurePolished()
            w.setFixedHeight(max(CONTROL_HEIGHT,w.fontMetrics().height()+18))
            if isinstance(w,QPushButton):w.setMinimumWidth(96)

STYLE='''
QWidget {font-size:13px;color:#24312e;}
QMainWindow,QDialog,QScrollArea,QWidget#batchPage {background:white;}
QScrollArea#cropSidebarScroll,QWidget#cropSidebarViewport,QWidget#cropSidebar {background:white;}
QLabel#brand {font-size:25px;font-weight:700;color:#125c50;}
QLabel#title {font-size:18px;font-weight:600;}
QLabel#sectionTitle {font-size:18px;font-weight:700;color:#193b32;}
QLabel#emptyTitle {font-size:18px;font-weight:600;color:#193b32;}
QLabel#emptyMark {font-size:34px;font-weight:400;color:#126b5e;background:#e2f1e8;border-radius:32px;min-width:64px;max-width:64px;min-height:64px;max-height:64px;}
QLabel#muted {color:#596762;}
QLabel#badge {color:#125c50;background:#dfede5;border-radius:6px;padding:6px 10px;}
QToolButton#infoIcon {background:#f3f7f4;color:#356b5d;border:1px solid #a9beb2;border-radius:11px;font-size:12px;font-weight:700;padding:0;}
QToolButton#infoIcon:hover,QToolButton#infoIcon:focus {background:#e1efe6;border-color:#247969;color:#125c50;}
QFrame#card {background:white;border:1px solid #d5ded7;border-radius:8px;}
QFrame#queuePane {background:white;border:1px solid #d5ded7;border-radius:12px;}
QFrame#queuePane[dropActive="true"] {border:2px solid #126b5e;}
QFrame#settingsCard {background:white;border:1px solid #d5ded7;border-radius:12px;}
QFrame#emptyDrop {background:#f8fbf9;border:1px dashed #bbd1c2;border-radius:12px;}
QFrame#emptyDrop[dropActive="true"] {background:#ebf7ee;border:2px solid #126b5e;}
QTreeView#queueTable {background:white;border:1px solid #d5ded7;border-radius:10px;}
QTreeView#queueTable QHeaderView {background:white;}
QTreeView#queueTable QHeaderView::section {background:#f3f8f4;border-bottom:1px solid #d5ded7;}
QTreeView#queueTable QHeaderView::section:first {border-top-left-radius:9px;}
QTreeView#queueTable QHeaderView::section:last {border-top-right-radius:9px;}
QGroupBox {background:white;border:1px solid #d5ded7;border-radius:8px;margin-top:16px;padding:16px;}
QGroupBox::title {subcontrol-origin:margin;left:16px;padding:0 6px;font-weight:600;}
QPushButton {background:white;border:1px solid #bac9c0;border-radius:8px;padding:0 14px;min-height:38px;}
QPushButton:hover {background:#eaf1ec;border-color:#32796a;}
QPushButton:pressed,QPushButton:checked {background:#dcece2;border-color:#32796a;}
QPushButton:disabled {background:#eef1ed;color:#858f88;border-color:#d8dfda;}
QPushButton#primary {background:#126b5e;color:white;border-color:#126b5e;font-weight:600;}
QPushButton#primary:hover {background:#0d544a;}
QPushButton#primary:disabled {background:#b5c9bf;color:white;border-color:#b5c9bf;}
QPushButton#softPrimary {background:#e5f2eb;color:#125c50;border-color:#b7d4c1;font-weight:600;}
QPushButton#softPrimary:hover {background:#d6eadd;border-color:#32796a;}
QLineEdit,QComboBox,QDoubleSpinBox {background:white;border:1px solid #bac9c0;border-radius:8px;padding:0 10px;min-height:38px;selection-background-color:#cfe4d8;}
QLineEdit:disabled,QComboBox:disabled,QDoubleSpinBox:disabled {background:#edf1ee;color:#858f88;}
QPushButton:focus,QLineEdit:focus,QComboBox:focus,QDoubleSpinBox:focus {border:2px solid #247969;}
QComboBox {padding-right:34px;}
QComboBox::drop-down {subcontrol-origin:padding;subcontrol-position:top right;width:30px;border:0;border-left:1px solid #d5ded7;}
QComboBox::down-arrow {image:url(__ASSETS__/chevron-down.svg);width:16px;height:16px;}
QComboBox QAbstractItemView {background:white;color:#24312e;border:1px solid #bac9c0;outline:0;selection-background-color:#dcece2;selection-color:#125c50;padding:4px;}
QComboBox QAbstractItemView::item {min-height:32px;padding:4px 10px;}
QDoubleSpinBox {padding-right:28px;}
QDoubleSpinBox QLineEdit {min-height:0;max-height:16777215px;border:0;border-radius:0;padding:0;background:transparent;}
QDoubleSpinBox::up-button,QDoubleSpinBox::down-button {subcontrol-origin:border;width:26px;border:0;border-left:1px solid #d5ded7;background:#edf3ef;}
QDoubleSpinBox::up-button {subcontrol-position:top right;border-top-right-radius:8px;}
QDoubleSpinBox::down-button {subcontrol-position:bottom right;border-bottom-right-radius:8px;}
QDoubleSpinBox::up-arrow {image:url(__ASSETS__/chevron-up.svg);width:12px;height:12px;}
QDoubleSpinBox::down-arrow {image:url(__ASSETS__/chevron-down.svg);width:12px;height:12px;}
QTreeView {background:white;alternate-background-color:#f8faf8;border:1px solid #d5ded7;border-radius:8px;outline:0;selection-background-color:#dcece2;selection-color:#193b31;}
QTreeView::item {height:44px;border-bottom:1px solid #edf1ed;}
QTreeView::item:hover {background:#edf5ef;}
QTreeView::item:selected {background:#dcece2;color:#193b31;}
QHeaderView::section {background:#eaf0eb;border:none;border-bottom:1px solid #cbd8ce;padding:12px 10px;font-weight:600;}
QScrollBar:vertical {background:#edf2ee;width:12px;margin:2px;border-radius:5px;}
QScrollBar:horizontal {background:#edf2ee;height:12px;margin:2px;border-radius:5px;}
QScrollBar::handle:vertical {background:#9eb8aa;min-height:32px;border-radius:4px;}
QScrollBar::handle:horizontal {background:#9eb8aa;min-width:32px;border-radius:4px;}
QScrollBar::handle:hover {background:#568e78;}
QScrollBar::add-line,QScrollBar::sub-line {width:0;height:0;border:0;}
QScrollBar::add-page,QScrollBar::sub-page,QAbstractScrollArea::corner {background:transparent;}
QProgressBar {border:0;border-radius:4px;background:#e0e9e3;min-height:22px;}
QProgressBar::chunk {background:#438d75;border-radius:4px;}
QSlider::groove:horizontal {height:6px;background:#dbe5dd;border-radius:3px;}
QSlider::sub-page:horizontal {background:#599a80;}
QSlider::handle:horizontal {background:#126b5e;width:18px;margin:-6px 0;border-radius:9px;}
QCheckBox {spacing:8px;}
QCheckBox::indicator {width:16px;height:16px;border:1px solid #93aa9c;border-radius:4px;background:white;}
QCheckBox::indicator:checked {background:#126b5e;border-color:#126b5e;image:url(__ASSETS__/check.svg);}
QPlainTextEdit {background:#f8faf8;border:1px solid #d5ded7;border-radius:8px;padding:10px;}
QMenu {background:white;border:1px solid #bac9c0;padding:5px;}
QMenu::item {padding:8px 20px;border-radius:4px;}
QMenu::item:selected {background:#dcece2;}
QMenu::separator {height:1px;background:#d5ded7;margin:4px;}
QToolTip {background:white;color:#24312e;border:1px solid #9eb4a7;padding:6px;}
QStatusBar {background:white;color:#596762;border:0;border-top:1px solid #edf1ed;}
QStatusBar::item {border:0;}
'''.replace('__ASSETS__',(Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'assets').as_posix())
