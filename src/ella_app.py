from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

from PySide6.QtCore import (QAbstractTableModel,QModelIndex,QObject,QProcess,QRectF,
    QSettings,QSize,QStandardPaths,Qt,QThread,QTimer,QUrl,Signal,QEvent)
from PySide6.QtGui import (QAccessible,QAction,QColor,QDesktopServices,QFont,QImage,QKeySequence,
    QPainter,QPen,QPixmap)
from PySide6.QtWidgets import (QAbstractItemView,QApplication,QCheckBox,
    QDialog,QDialogButtonBox,QDoubleSpinBox,QFileDialog,QFormLayout,QFrame,QGridLayout,
    QGroupBox,QHBoxLayout,QLabel,QLineEdit,QMainWindow,QMessageBox,QPlainTextEdit,
    QProgressBar,QPushButton,QSizePolicy,QSlider,QSplitter,QTabWidget,QTableView,
    QTreeView,QVBoxLayout,QWidget,QHeaderView,QMenu,QScrollArea,QAccessibleWidget,QStackedWidget)

import subtitle_ocr as core
import hardware_policy as hardware
from version import VERSION
from output_policy import aligned_stem,output_stems
from series_policy import series_key,series_jobs,effective_roi,recognition_options
from workspace_policy import settings_for,apply_settings,removal_snapshot,restore_removed,import_entries
from task_model import QueueModel
from copy import deepcopy
from project_progress import progress as project_progress
from source_relink import relink_series

BRAND='EllaPuede'
APP_NAME='EllaPuede 字幕提取工具'
STATUS={'pending':'等待处理','running':'处理中','paused':'已暂停','done':'已导出',
        'failed':'失败 · 可重试','interrupted':'已停止 · 可继续'}
from diagnostic_labels import FLAGS

from ui_theme import STYLE,info_icon,polish_controls
from stable_combo import StableComboBox
from crop_editor import CropCanvas,CropDialog

def label(text,kind=None):
    w=QLabel(text)
    if kind:w.setObjectName(kind)
    return w

def button(text,callback,primary=False):
    w=QPushButton(text);w.clicked.connect(callback)
    w.setAccessibleName(text)
    if primary:w.setObjectName('primary')
    return w

def hinted_label(text,icon):
    row=QHBoxLayout();row.setContentsMargins(0,0,0,0);row.setSpacing(6)
    row.addWidget(label(text));row.addWidget(icon);row.addStretch()
    return row

def pil_pixmap(image):
    image=image.convert('RGB')
    q=QImage(image.tobytes(),image.width,image.height,image.width*3,QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(q)

class TaskThread(QThread):
    result=Signal(object)
    error=Signal(str)
    def __init__(self,fn,parent=None):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.result.emit(self.fn())
        except Exception as e:self.error.emit(str(e))

class DataView(QTreeView):
    """Grouped virtualized task rows."""
    def __init__(self):
        super().__init__();self.setRootIsDecorated(True);self.setItemsExpandable(True);self.setUniformRowHeights(True)
    def mousePressEvent(self,event):
        from PySide6.QtWidgets import QStyleOptionViewItem,QStyle
        index=self.indexAt(event.position().toPoint())
        if index.isValid() and index.column()==0:
            option=QStyleOptionViewItem();self.itemDelegateForIndex(index).initStyleOption(option,index);option.rect=self.visualRect(index)
            rect=self.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator,option,self)
            if rect.contains(event.position().toPoint()):
                current=self.model().data(index,Qt.ItemDataRole.CheckStateRole)
                # Cocoa accessibility queries the focused row after mousePressEvent.
                # Mutating selection/model inside that event can invalidate its AX item.
                next_state=Qt.CheckState.Unchecked if current==Qt.CheckState.Checked else Qt.CheckState.Checked
                QTimer.singleShot(0,lambda:self.model().setData(index,next_state,Qt.ItemDataRole.CheckStateRole) if index.isValid() else None)
                self._checkbox_press=True;event.accept();return
        self._checkbox_press=False;super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        if getattr(self,'_checkbox_press',False):self._checkbox_press=False;event.accept();return
        super().mouseReleaseEvent(event)
    def horizontalHeader(self):return self.header()
    def selectRow(self,row):
        from PySide6.QtCore import QItemSelectionModel
        self.selectionModel().setCurrentIndex(self.model().index(row,0),QItemSelectionModel.SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows)

def _mac_queue_accessibility(class_name,obj):
    # Qt 6.8's Cocoa table-cell accessibility bridge can dereference a stale
    # selected row during hierarchy scans. Keep the view itself accessible
    # without exposing the unstable native table-cell wrappers.
    if isinstance(obj,DataView):return QAccessibleWidget(obj,QAccessible.Role.Client,'字幕任务列表')
    return None


class DesktopApplication(QApplication):
    """Route native Quit (including Dock quit) through the same saved shutdown."""
    window=None
    shutdown_ready=False
    def event(self,event):
        if event.type()==QEvent.Type.Quit and self.window is not None and not self.shutdown_ready:
            self.window.request_quit()
            return True
        return super().event(event)


class MainWindow(QMainWindow):
    def __init__(self,state_dir=None):
        super().__init__();self.setWindowTitle(APP_NAME);self.resize(1160,860);self.setMinimumSize(920,720)
        self.setAcceptDrops(True);self.running=False;self.close_requested=False
        self.state_dir=Path(state_dir or os.environ.get('ELLAPUEDE_DATA_DIR') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        self.state_dir.mkdir(parents=True,exist_ok=True)
        self.state_file=self.state_dir/'workspace.json';self.jobs=[];self.background=[];self.process=None;self.active=None;self.stopping=False;self.paused=False;self.buffer=''
        saved={}
        try:saved=json.loads(self.state_file.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        self.jobs=saved.get('jobs',[]);self.series_regions=saved.get('series_regions',{});self.auto_region_groups=set(saved.get('auto_region_groups',[]));self.undo_stack=[];self.loading_settings=False;self.skipping=False;self.restart_current=False;self.reprocess_after_export=set()
        from control_cleanup import clean_finished_controls
        clean_finished_controls(self.state_dir/'controls',[j['id'] for j in self.jobs if j.get('status') in {'done','failed'}],
                                [j['id'] for j in self.jobs if j.get('status') not in {'done','failed'}])
        self.defaults={k:saved.get('defaults',{}).get(k,saved.get(k,v)) for k,v in {'language':'auto','engine':'auto','format':'both','output':str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))/'EllaPuede'/'字幕输出')}.items()}
        self.default_language_pinned=bool(saved.get('default_language_pinned',False))
        if not self.default_language_pinned:self.defaults['language']='auto'
        self.cache_root=Path(saved.get('cache_root') or self.state_dir/'cache')
        for job in self.jobs:
            job.setdefault('series',series_key(job));job.setdefault('settings',dict(self.defaults))
            job['source_missing']=not Path(job['source']).is_file()
            if job.get('roi') and series_key(job) not in self.series_regions:self.series_regions[series_key(job)]={'roi':job['roi'],'source':job['source'],'manual':True}
            if job['status'] in ['running','paused','pausing','stopping']:job['status']='interrupted'
            if job['status']=='done' and job.pop('settings_changed',False):
                # Older builds left the UI choice changed while keeping the
                # previously exported OCR. Never display that stale result as done.
                job['status']='pending';job['processed_seconds']=0;job.pop('work_fraction',None)
                job['replace_output']=True;job['pending_reason']='旧版设置已更改 · 待重新识别'
        central=QWidget();outer=QVBoxLayout(central);outer.setContentsMargins(24,24,24,16);outer.setSpacing(16);self.setCentralWidget(central)
        header=QHBoxLayout();header.addWidget(label(BRAND,'brand'));header.addWidget(label('字幕提取工具','title'));header.addStretch();header.addWidget(label('离线识别 · 多语言字幕','muted'));header.addWidget(label(f'{VERSION} 公测版','badge'));outer.addLayout(header)
        self.content_layout=outer
        self.build_batch(saved)
        self.statusBar().messageChanged.connect(lambda message:self.statusBar().setVisible(bool(message)))
        self.statusBar().hide()
        self.timer=QTimer(self);self.timer.timeout.connect(self.update_resources);self.timer.start(2000)
        self.create_menus();polish_controls(self)
        from language_preview import LanguagePreview
        self.language_preview=LanguagePreview(self)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'batch_layout'):
            compact=self.height()<1000;self.batch_layout.setSpacing(8 if compact else 12);self.content_layout.setSpacing(8 if compact else 16);self.content_layout.setContentsMargins(16 if compact else 24,16 if compact else 24,16 if compact else 24,12 if compact else 16)
            if hasattr(self,'queue_table'):self.queue_table.setMinimumHeight(160 if self.height()<=760 else 220)
    def create_menus(self):
        menu=self.menuBar().addMenu('文件')
        for text,shortcut,fn in [('添加视频','Ctrl+O',self.add_files),('添加文件夹','Ctrl+Shift+O',self.add_folder)]:
            action=QAction(text,self);action.setShortcut(QKeySequence(shortcut));action.triggered.connect(fn);menu.addAction(action)
        menu.addSeparator()
        self.close_action=QAction('关闭窗口',self)
        self.close_action.setMenuRole(QAction.MenuRole.NoRole)
        self.close_action.setShortcuts(QKeySequence.StandardKey.Close)
        self.close_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.close_action.triggered.connect(self.close_active_window)
        menu.addAction(self.close_action)
        self.quit_action=QAction('退出 EllaPuede',self)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.quit_action.setShortcuts(QKeySequence.StandardKey.Quit)
        self.quit_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.quit_action.triggered.connect(self.request_quit)
        menu.addAction(self.quit_action)
        help_menu=self.menuBar().addMenu('帮助');action=help_menu.addAction('关于 EllaPuede')
        action.setMenuRole(QAction.MenuRole.AboutRole)
        action.triggered.connect(lambda:QMessageBox.information(self,APP_NAME,f'EllaPuede Subtitle Extractor {VERSION} 公测版\n\n画面 OCR · 逐帧时间戳 · 批量提取与自动导出\nmacOS：Apple Vision / PP-OCRv6\nWindows：PP-OCRv6 · CPU / 经试运行验证的 DirectML\n\n完成后按所选格式自动生成同名字幕。默认只导出字幕文件；后台缓存用于继续任务。'))

    def close_active_window(self):
        window=QApplication.activeModalWidget() or QApplication.activeWindow()
        if isinstance(window,QDialog):window.reject()
        else:self.close()

    def request_quit(self):
        for window in QApplication.topLevelWidgets():
            if isinstance(window,QDialog) and window.window() is window:window.reject()
        self.close()

    def maybe_finish_close(self):
        if self.close_requested and self.process is None and not any(t.isRunning() for t in self.background):
            QTimer.singleShot(0,self.close)

    def show_hardware(self):
        QMessageBox.information(self,'硬件与加速状态',hardware.description())

    def build_batch(self,saved):
        page=QWidget();page.setObjectName('batchPage');workspace=QHBoxLayout(page);self.batch_layout=workspace
        workspace.setContentsMargins(0,0,0,0);workspace.setSpacing(16)
        queue_pane=QFrame();queue_pane.setObjectName('queuePane');self.queue_pane=queue_pane;layout=QVBoxLayout(queue_pane)
        layout.setContentsMargins(18,18,18,18);layout.setSpacing(12);workspace.addWidget(queue_pane,1)
        settings_pane=QWidget();settings_pane.setObjectName('settingsPane');settings_layout=QVBoxLayout(settings_pane)
        settings_layout.setContentsMargins(0,30,0,0);settings_layout.setSpacing(12)
        settings_pane.setFixedWidth(340);workspace.addWidget(settings_pane)
        intro=QHBoxLayout();intro.addWidget(label('剧集队列','sectionTitle'));intro.addStretch();layout.addLayout(intro)
        self.queue_summary=label('','muted');layout.addWidget(self.queue_summary)
        self.add_file_btn=button('添加视频',self.add_files);self.add_folder_btn=button('添加文件夹',self.add_folder)
        self.add_folder_btn.setToolTip('可导入整季文件夹；字幕会按每集视频原文件名自动导出。')
        actions=QHBoxLayout()
        actions.setSpacing(12);actions.addWidget(self.add_file_btn);actions.addWidget(self.add_folder_btn);actions.addStretch()
        self.crop_btn=button('框选整剧字幕区域',self.set_roi,True);self.auto_roi_btn=button('自动定位',self.clear_roi);self.remove_btn=button('移除所选',self.remove_selected)
        actions.insertWidget(2,self.crop_btn);actions.insertWidget(3,self.auto_roi_btn)
        self.more_btn=button('其他操作',self.show_task_menu);intro.addWidget(self.more_btn)
        self.reprocess_btn=button('重新处理',self.reprocess_selected)
        self.reexport_btn=button('重新导出…',self.reexport_selected)
        self.undo_btn=button('撤销移除',self.undo_remove);self.undo_btn.hide()
        self.retry_btn=button('继续未完成任务',self.retry_failed);layout.addLayout(actions)
        self.region_mode=label('请选择一部剧并框选字幕；一部剧只需设置一次。','muted');self.region_mode.setWordWrap(True)
        layout.addWidget(self.region_mode)
        self.queue_model=QueueModel(self.jobs,self.series_regions,self.auto_region_groups);self.queue_table=DataView();self.queue_table.setObjectName('queueTable');self.queue_table.setModel(self.queue_model);self.configure_table(self.queue_table)
        self.queue_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.queue_table.setColumnWidth(1,120);self.queue_table.setColumnWidth(2,145)
        self.queue_model.checked.connect(self.set_checked)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);self.queue_table.customContextMenuRequested.connect(self.show_task_menu)
        self.queue_table.selectionModel().selectionChanged.connect(self.update_selection)
        self.queue_table.setMinimumHeight(220)
        self.queue_table.doubleClicked.connect(lambda index:self.open_selected_output() if 'children' not in index.internalPointer() else None)
        self.empty_state=QFrame();self.empty_state.setObjectName('emptyDrop')
        empty_layout=QVBoxLayout(self.empty_state);empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter);empty_layout.setSpacing(10)
        empty_mark=label('＋','emptyMark');empty_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_mark,0,Qt.AlignmentFlag.AlignHCenter)
        empty_title=label('把视频或整季文件夹拖到这里','emptyTitle');empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter);empty_layout.addWidget(empty_title)
        empty_subtitle=label('字幕自动按视频原名导出','muted');empty_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter);empty_layout.addWidget(empty_subtitle)
        empty_add=button('选择视频',self.add_files,True);empty_layout.addWidget(empty_add,0,Qt.AlignmentFlag.AlignHCenter)
        self.queue_stack=QStackedWidget();self.queue_stack.addWidget(self.empty_state);self.queue_stack.addWidget(self.queue_table)
        layout.addWidget(self.queue_stack,1)
        self.task_actions_panel=QWidget();task_actions=QHBoxLayout(self.task_actions_panel);task_actions.setContentsMargins(0,0,0,0);task_actions.setSpacing(8)
        self.selection_hint=label('选择任务后可重新处理或导出。','muted');self.selection_hint.hide();task_actions.addWidget(self.selection_hint)
        self.selection_info=info_icon(self.selection_hint.text());task_actions.addWidget(self.selection_info);task_actions.addStretch()
        for control in (self.reprocess_btn,self.reexport_btn,self.remove_btn,self.undo_btn):task_actions.addWidget(control)
        layout.addWidget(self.task_actions_panel)
        settings_layout.addWidget(label('字幕设置','sectionTitle'))
        scope_label=QHBoxLayout();scope_label.addWidget(label('设置范围'));scope_label.addStretch()
        self.scope_hint=label('修改语言会重新识别；仅修改格式或位置会直接重新导出。','muted');self.scope_hint.hide();self.scope_info=info_icon(self.scope_hint.text());scope_label.addWidget(self.scope_info);settings_layout.addLayout(scope_label)
        self.settings_scope=StableComboBox();self.settings_scope.addItem('默认值 · 用于新导入任务',None);self.settings_scope.setToolTip('选择设置作用于哪一部剧。');settings_layout.addWidget(self.settings_scope)
        settings=QFrame();settings.setObjectName('settingsCard');grid=QGridLayout(settings)
        grid.setContentsMargins(16,16,16,16);grid.setHorizontalSpacing(8);grid.setVerticalSpacing(10);grid.setColumnStretch(0,1)
        self.profile=StableComboBox();self.profile.addItems(['边办公边处理','日常处理 · 推荐','优先速度']);self.profile.setCurrentIndex(saved.get('profile',1))
        self.mode_info=info_icon('处理模式只调整资源占用和速度，不改变字幕区域与识别规则。')
        grid.addLayout(hinted_label('处理模式',self.mode_info),4,0);grid.addWidget(self.profile,5,0)
        self.language=StableComboBox()
        for name,code in hardware.LANGUAGES:self.language.addItem(name,code)
        self.language.setCurrentIndex(max(0,self.language.findData(saved.get('language','auto'))))
        self.language.setToolTip('选择字幕原语言，不进行翻译。自动识别主要尝试中、英、韩；泰语、日语、繁体中文与欧洲语言请手动指定。')
        self.language_hint=label('新导入的视频默认自动识别；选择剧集后可手动指定原语言。','muted');self.language_hint.setWordWrap(True);self.language_hint.hide()
        self.mode_note=label('','muted');self.mode_note.setWordWrap(True);self.mode_note.hide()
        self.profile.currentIndexChanged.connect(self.update_mode_note);self.update_mode_note()
        self.output=QLineEdit(saved.get('output') or str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))/'EllaPuede'/'字幕输出'));self.output.setReadOnly(True)
        self.output.setToolTip(self.output.text());self.output.textChanged.connect(self.output.setToolTip)
        self.output_btn=button('更换位置',self.choose_output)
        self.export_format=StableComboBox()
        for text,value in [('SRT · 通用字幕','srt'),('ASS · 样式字幕','ass'),('SRT + ASS · 两种都导出','both')]:self.export_format.addItem(text,value)
        self.export_format.setCurrentIndex(max(0,self.export_format.findData(saved.get('format','both'))))
        grid.addWidget(label('导出格式'),2,0);grid.addWidget(self.export_format,3,0)
        self.export_format.currentIndexChanged.connect(self.format_changed)
        self.language_info=info_icon(self.language_hint.text())
        grid.addLayout(hinted_label('识别语言',self.language_info),0,0);grid.addWidget(self.language,1,0)
        grid.addWidget(label('保存到'),6,0);grid.addWidget(self.output,7,0);grid.addWidget(self.output_btn,8,0)
        self.language_hint.setParent(settings);self.mode_note.setParent(settings)
        settings_layout.addWidget(settings);settings_layout.addStretch()
        self.advanced_toggle=button('高级选项',self.toggle_advanced);self.advanced_toggle.setCheckable(True)
        self.advanced_dialog=QDialog(self);self.advanced_dialog.setWindowTitle('EllaPuede · 高级选项');self.advanced_dialog.resize(620,560);advanced_outer=QVBoxLayout(self.advanced_dialog);advanced_outer.setContentsMargins(24,24,24,24)
        self.advanced_dialog.finished.connect(lambda _:self.advanced_toggle.setChecked(False))
        self.advanced=QGroupBox('高级选项 · 通常无需修改');advanced=QGridLayout(self.advanced);advanced.setHorizontalSpacing(16);advanced.setVerticalSpacing(16);advanced.setColumnStretch(1,1)
        self.engine=StableComboBox();self.engine.addItem('自动选择 · 推荐','auto')
        if sys.platform=='darwin':self.engine.addItem('Apple Vision · Mac 原生','vision')
        self.engine.addItem('通用兼容识别（Mac 可能较慢）' if sys.platform=='darwin' else '通用离线识别','rapid');self.engine.setCurrentIndex(max(0,self.engine.findData(saved.get('engine','auto'))))
        self.device=StableComboBox()
        for title,value in [('自动测速 · 推荐','auto'),('仅使用 CPU','cpu'),('优先使用 GPU','gpu')]:self.device.addItem(title,value)
        self.device.setCurrentIndex(max(0,self.device.findData(saved.get('device','auto'))))
        self.device.setToolTip('计算设备只影响 ONNX 推理速度；字幕语言和 OCR 模型保持不变。自动测速需要画面中出现文字。')
        self.memory=QDoubleSpinBox();self.memory.setRange(1,32);self.memory.setSingleStep(1);self.memory.setValue(saved.get('memory',hardware.default_memory_limit()));self.memory.setSuffix(' GB');self.memory.setDecimals(0)
        self.memory.valueChanged.connect(self.update_mode_note);self.engine.currentIndexChanged.connect(self.update_mode_note);self.device.currentIndexChanged.connect(self.update_mode_note);self.update_mode_note()
        if sys.platform=='darwin':advanced.addWidget(label('OCR 识别方式'),0,0);advanced.addWidget(self.engine,0,1)
        else:advanced.addWidget(label('计算设备'),0,0);advanced.addWidget(self.device,0,1)
        advanced.addWidget(label('内存保护上限'),1,0);advanced.addWidget(self.memory,1,1)
        self.overwrite=QCheckBox('重新处理已完成视频');self.overwrite.setToolTip('替换前备份同名字幕；原视频不变。');advanced.addWidget(self.overwrite,3,0,1,2)
        advanced.addWidget(button('硬件与加速',self.show_hardware),4,0,1,2);advanced.addWidget(button('缓存管理',self.show_cache),2,0,1,2);self.overwrite.toggled.connect(self.update_selection)
        self.resource_label=label('','muted');advanced.addWidget(self.resource_label,5,0,1,2)
        self.logs=QPlainTextEdit();self.logs.setReadOnly(True);self.logs.setMaximumBlockCount(600);self.logs.setMinimumHeight(90);self.logs.setPlaceholderText('处理详情');advanced.addWidget(self.logs,6,0,1,2)
        advanced_outer.addWidget(self.advanced);advanced_buttons=QHBoxLayout();advanced_buttons.addWidget(button('保存运行日志',self.save_diagnostics));advanced_buttons.addStretch();advanced_buttons.addWidget(button('完成',self.advanced_dialog.accept));advanced_outer.addLayout(advanced_buttons)
        self.phase_label=label('','muted');self.phase_label.setWordWrap(True);self.phase_label.hide()
        self.progress=QProgressBar();self.progress.setRange(0,1000);self.progress.setValue(0);self.progress.setTextVisible(False)
        bottom=QHBoxLayout();self.start_btn=button('开始提取',self.start_queue,True);self.pause_btn=button('暂停',self.toggle_pause);self.stop_btn=button('稍后继续',self.stop_queue);self.pause_btn.setEnabled(False);self.stop_btn.setEnabled(False)
        bottom.setSpacing(12);bottom.addWidget(self.advanced_toggle);bottom.addWidget(button('打开字幕文件夹',self.open_output));bottom.addWidget(self.retry_btn);bottom.addStretch();bottom.addWidget(self.pause_btn);bottom.addWidget(self.stop_btn);bottom.addWidget(self.start_btn)
        scroll=QScrollArea();scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);scroll.setWidget(page)
        scroll.viewport().setAutoFillBackground(True)
        progress_row=QHBoxLayout();progress_row.setSpacing(8);progress_row.addWidget(self.progress,1)
        self.progress_info=info_icon('显示整个项目的进度，已完成的集数会计入总进度；导出字幕与原视频同名。')
        progress_row.addWidget(self.progress_info)
        self.content_layout.addWidget(scroll,1);self.content_layout.addWidget(self.phase_label);self.content_layout.addLayout(progress_row);self.content_layout.addLayout(bottom)
        self.settings_scope.currentIndexChanged.connect(self.load_scope);self.refresh_queue()
        QWidget.setTabOrder(self.settings_scope,self.language);QWidget.setTabOrder(self.language,self.export_format)
        QWidget.setTabOrder(self.export_format,self.profile);QWidget.setTabOrder(self.profile,self.output_btn)
        for key,fn in [('Delete',self.remove_selected),('Backspace',self.remove_selected),('Ctrl+Z',self.undo_remove),('Ctrl+A',self.select_all_tasks)]:
            action=QAction(self);action.setShortcut(QKeySequence(key));action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);action.triggered.connect(fn);self.queue_table.addAction(action)
        self.load_scope()
        groups={series_key(j) for j in self.jobs}
        if len(groups)==1:self.settings_scope.setCurrentIndex(self.settings_scope.findData(next(iter(groups))))
        for combo in (self.engine,self.language):combo.currentIndexChanged.connect(self.recognition_settings_changed)
        self.profile.currentIndexChanged.connect(self.save_state)
        self.device.currentIndexChanged.connect(self.save_state)

    def current_settings(self):
        return {'language':self.language.currentData(),'engine':self.engine.currentData(),'format':self.export_format.currentData(),'output':self.output.text()}
    def load_scope(self,*args):
        if not hasattr(self,'language'):return
        scope=self.settings_scope.currentData();job=next((j for j in self.jobs if series_key(j)==scope),None)
        values=settings_for(job,self.defaults) if job else self.defaults
        self.loading_settings=True
        for name in ('language','engine','format'):
            widget=self.export_format if name=='format' else getattr(self,name);widget.setCurrentIndex(max(0,widget.findData(values[name])))
        self.output.setText(values['output']);self.loading_settings=False;self.update_language_presentation();self.update_mode_note()

    def update_language_presentation(self):
        """Show resolved language without changing the user's `auto` setting."""
        if not hasattr(self,'language_hint'):return
        from hardware_policy import language_name
        jobs=self.selected_jobs() if hasattr(self,'queue_table') else []
        if not jobs and hasattr(self,'settings_scope') and self.settings_scope.currentData() is not None:
            jobs=[j for j in self.jobs if series_key(j)==self.settings_scope.currentData()]
        resolved=[]
        for job in jobs:
            values=job.get('resolved_languages') or ([job.get('detected_language')] if job.get('detected_language') else [])
            resolved.extend(x for x in values if x and x != 'auto')
        resolved=list(dict.fromkeys(resolved))
        index=self.language.findData('auto')
        if index >= 0:
            text='自动识别'+(f' · 本剧：{language_name(resolved[0])}' if len(resolved)==1 else '')
            self.language.setItemText(index,text)
        explicit=self.language.currentData()
        if explicit!='auto':
            self.language_hint.setText('已手动指定：'+language_name(explicit)+'；不会自动切换。选择“自动识别”可重新判断。')
        elif resolved:
            self.language_hint.setText('本剧暂判为：'+language_name(','.join(resolved))+'；如发现误判，请手动指定原语言。')
        else:
            pending=next((j.get('language_phase') for j in jobs if j.get('language_phase')),None)
            self.language_hint.setText(pending or '新导入的视频默认自动判断中、英、韩；其他语言请选中剧集后指定。')
        self.language.setToolTip(self.language_hint.text())
        self.language_info.setToolTip(self.language_hint.text())
    def recognition_settings_changed(self,*args):
        self.commit_settings()
    def commit_settings(self):
        if self.loading_settings:return
        values=self.current_settings();scope=self.settings_scope.currentData()
        # A one-series workspace has no ambiguous target. Editing the visible
        # language must change that series, even if the default scope was shown.
        groups={series_key(j) for j in self.jobs}
        if scope is None and len(groups)==1:
            scope=next(iter(groups))
            from PySide6.QtCore import QSignalBlocker
            blocker=QSignalBlocker(self.settings_scope)
            self.settings_scope.setCurrentIndex(self.settings_scope.findData(scope))
            del blocker
        if scope is None:
            if values['language']!=self.defaults['language']:self.default_language_pinned=values['language']!='auto'
            self.defaults.update(values)
        else:apply_settings(self.jobs,values,scope)
        self.save_state();self.refresh_queue()
        if hasattr(self,'language_preview'):self.language_preview.cancel();self.language_preview.attempted.clear();self.language_preview.start()
    def format_changed(self):
        self.commit_settings()

    def update_mode_note(self):
        note=['降低电脑负担，适合一边办公一边处理。','自动平衡处理速度和电脑负担。','提高本机允许的并行度；对白区域与识别规则保持一致。'][self.profile.currentIndex()]
        if hasattr(self,'memory') and hasattr(self,'engine'):
            try:
                resolved=hardware.resolve_engine(self.engine.currentData(),[self.language.currentData()])
                allocation=hardware.plan(resolved,self.profile.currentIndex(),self.memory.value(),device=self.device.currentData())
                note+=f"  本机预计同时处理 {allocation['workers']} 路（受{allocation['limited_by']}约束）；实际速度以运行进度为准。"
            except Exception:pass
        self.mode_note.setText(note);self.profile.setToolTip(note);self.mode_info.setToolTip(note)
    def toggle_advanced(self):
        self.advanced_dialog.setVisible(self.advanced_toggle.isChecked())

    @staticmethod
    def configure_table(table):
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);table.setAlternatingRowColors(True);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def background_task(self,fn,ready):
        thread=TaskThread(fn,self);self.background.append(thread);thread.result.connect(ready);thread.error.connect(self.show_error)
        def cleanup():
            if thread in self.background:self.background.remove(thread)
            thread.deleteLater()
            self.maybe_finish_close()
        thread.finished.connect(cleanup);thread.start();return thread

    def show_status(self,message):self.statusBar().showMessage(message,7000)
    def show_error(self,message):self.logs.appendPlainText(str(message));QMessageBox.warning(self,APP_NAME,str(message))
    def save_state(self):core.save_json(self.state_file,{'defaults':self.defaults,'default_language_pinned':self.default_language_pinned,'cache_root':str(self.cache_root),'jobs':self.jobs,'series_regions':self.series_regions,'auto_region_groups':sorted(self.auto_region_groups),'output':self.output.text(),'profile':self.profile.currentIndex(),'format':self.export_format.currentData(),'memory':self.memory.value(),'engine':self.engine.currentData(),'device':self.device.currentData(),'language':self.language.currentData()})
    def update_project_progress(self):
        value=project_progress(self.jobs);self.progress.setRange(0,1000);self.progress.setValue(value);self.progress.setFormat(f'项目进度 {value/10:.1f}%'+('（估算）' if any(not j.get('duration') for j in self.jobs) else ''));self.progress.setTextVisible(True)
    def refresh_queue(self):
        selected=getattr(self,'selected_ids',set());self._refreshing=True
        reset=self.queue_model.refresh()
        if reset:self.queue_table.expandAll()
        self.queue_model.set_selected(selected)
        self.sync_row_selection(selected)
        if hasattr(self,'settings_scope'):
            scope=self.settings_scope.currentData();groups=list(dict.fromkeys(series_key(j) for j in self.jobs))
            effective_scope=groups[0] if scope is None and len(groups)==1 else scope
            self.settings_scope.blockSignals(True);self.settings_scope.clear();self.settings_scope.addItem('默认值 · 仅影响以后导入的任务',None)
            for key in groups:self.settings_scope.addItem(Path(key).name,key)
            self.settings_scope.setCurrentIndex(max(0,self.settings_scope.findData(effective_scope)));self.settings_scope.blockSignals(False)
            self.settings_scope.setToolTip('当前设置范围：'+self.settings_scope.currentText())
            if effective_scope!=scope:self.load_scope()
        self._refreshing=False
        counts={s:sum(j['status']==s for j in self.jobs) for s in STATUS};self.queue_summary.setText(f'{len(self.jobs)} 集 · 已导出 {counts["done"]} · 等待 {counts["pending"]} · 待继续 {counts["failed"]+counts["interrupted"]}')
        self.queue_summary.setVisible(bool(self.jobs));self.more_btn.setVisible(bool(self.jobs))
        self.queue_stack.setCurrentWidget(self.queue_table if self.jobs else self.empty_state)
        self.region_mode.setVisible(bool(self.jobs))
        self.retry_btn.setVisible(bool(counts['failed']+counts['interrupted']));self.update_selection();self.update_project_progress()
    def sync_row_selection(self,ids):
        from PySide6.QtCore import QItemSelectionModel,QItemSelection,QSignalBlocker
        model=self.queue_table.selectionModel();blocker=QSignalBlocker(model);selection=QItemSelection()
        for index in self.queue_model.indexes_for(ids):selection.select(index,index.siblingAtColumn(2))
        model.select(selection,QItemSelectionModel.SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows)
    def set_checked(self,ids,checked):
        selected=set(getattr(self,'selected_ids',set()))
        selected.update(ids) if checked else selected.difference_update(ids)
        self.selected_ids=selected;self.queue_model.set_selected(selected);self.sync_row_selection(selected);self._scope_sync_requested=True;self.update_selection()
    def select_all_tasks(self):
        self.selected_ids={j['id'] for j in self.jobs};self._scope_sync_requested=True;self.refresh_queue()
    def update_selection(self,*args):
        if getattr(self,'_refreshing',False) or getattr(self,'_normalizing_selection',False):return
        jobs=self.selected_jobs();self.selected_ids={j['id'] for j in jobs};self.queue_model.set_selected(self.selected_ids)
        # Keep group selection as a group. Replacing it with child rows inside
        # selectionChanged invalidates Cocoa's focused accessibility row.
        self.queue_table.viewport().update();keys={series_key(j) for j in jobs};editable=bool(jobs) and not self.running
        available=jobs or next((j for j in self.jobs if j['status'] in {'pending','interrupted'}),None)
        self.crop_btn.setEnabled(bool(available) and not self.running and len(keys)<=1);self.remove_btn.setEnabled(bool(jobs) and all(j is not self.active for j in jobs))
        self.remove_btn.setToolTip('先取消勾选正在处理的集，或停止任务后再移除。' if self.active in jobs else '仅从队列移除，可撤销；视频与字幕文件保留。')
        self.auto_roi_btn.setEnabled(bool(available) and not self.running and len(keys)<=1)
        self.retry_btn.setEnabled(not self.running);self.more_btn.setEnabled(bool(self.jobs))
        can_reprocess=(not self.running or self.active is not None) and any(j['status']!='pending' and (j is not self.active or not self.restart_current) for j in jobs)
        self.reprocess_btn.setEnabled(can_reprocess)
        self.reprocess_btn.setText('停止并重做本集' if self.running and self.active in jobs and self.process else '重新处理所选')
        self.reprocess_btn.setToolTip('从画面重新识别；替换已有字幕前会自动备份。' if not self.running else '当前集先停止并重新排队；其他选中集加入待处理队列。')
        can_reexport=not self.running and any(j.get('result_stem') and Path(str(j['result_stem'])+'.subtitles.json').is_file() for j in jobs)
        self.reexport_btn.setEnabled(can_reexport)
        self.reexport_btn.setToolTip('复用已保存的识别记录，按所选格式和位置再次导出；不重新 OCR。')
        target=jobs[0] if jobs else available
        region=self.series_regions.get(series_key(target),{}) if target else {}
        if target and region.get('manual'):region_text='已框选 · 本剧共用区域'
        elif target and series_key(target) in self.auto_region_groups:region_text='自动定位 · 首集确认后全剧共用'
        elif target and effective_roi(target,self.series_regions):region_text='已定位 · 本剧共用区域'
        else:region_text='待框选 · 本剧只需设置一次'
        self.region_mode.setText(region_text)
        self.selection_hint.setText(f'已选 {len(jobs)} 集 · '+('本剧共用区域' if len(keys)==1 else '跨剧选择') if jobs else '勾选或点击选择任务')
        self.selection_info.setToolTip(self.selection_hint.text()+'；可使用右侧按钮重新处理、导出或移除。')
        self.task_actions_panel.setVisible(bool(jobs) or bool(self.undo_stack))
        sync_scope=bool(args) or getattr(self,'_scope_sync_requested',False)
        self._scope_sync_requested=False
        if sync_scope and hasattr(self,'settings_scope') and not self.running:
            desired=next(iter(keys)) if len(keys)==1 else None
            if self.settings_scope.currentData()!=desired:
                from PySide6.QtCore import QSignalBlocker
                blocker=QSignalBlocker(self.settings_scope);self.settings_scope.setCurrentIndex(self.settings_scope.findData(desired));del blocker
                self.load_scope()
        self.update_language_presentation()
        pending=[j for j in self.jobs if j['status'] in ('pending','interrupted')]
        self.start_btn.setEnabled(not self.running and bool(pending))
        self.start_btn.setText('应用更改并导出' if pending and all(j.get('export_only') for j in pending) else '开始提取')
    def show_task_menu(self,*args):
        from PySide6.QtCore import QPoint,QItemSelectionModel
        context_point=args[0] if args and isinstance(args[0],QPoint) else None
        if context_point is not None:
            index=self.queue_table.indexAt(context_point)
            if index.isValid() and index not in self.queue_table.selectionModel().selectedIndexes():
                self.queue_table.selectionModel().select(index,QItemSelectionModel.SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows)
        elif not self.selected_jobs() and len(self.queue_model.groups)==1:
            index=self.queue_model.index(0,0)
            self.queue_table.selectionModel().select(index,QItemSelectionModel.SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows)
        jobs=self.selected_jobs();single=len(jobs)==1;one_series=bool(jobs) and len({series_key(j) for j in jobs})==1
        menu=QMenu(self)
        def action(title,callback):menu.addAction(title).triggered.connect(callback)
        if self.running and self.process:action('停止当前集，继续下一集',self.skip_current)
        if not jobs:
            action('全选任务',self.select_all_tasks)
            if any(j['status'] in {'failed','interrupted'} for j in self.jobs):action('选择失败项',lambda:self.select_status({'failed','interrupted'}))
            if any(j['status']=='done' for j in self.jobs):action('移除已完成项',self.remove_completed)
        else:
            if self.reprocess_btn.isEnabled():action(self.reprocess_btn.text(),self.reprocess_selected)
            if self.reexport_btn.isEnabled():action('重新导出字幕…',self.reexport_selected)
            if any(j.get('result_stem') for j in jobs):action('打开字幕位置',self.open_selected_output)
            if any(j.get('result_stem') or j.get('error') for j in jobs):action('查看处理摘要',self.show_processing_summary)
            if not self.running and one_series:
                if single:action('仅设置本集区域',lambda:self.set_roi(single=True))
                if any(j.get('roi_override') for j in jobs):action('恢复本剧共用区域',self.clear_episode_override)
                if any(j.get('source_missing') for j in jobs):action('找回原视频…',self.relocate_video)
                if len(jobs)<len(series_jobs(self.jobs,jobs)):action('将所选集分为单独一组',self.split_selected)
            if self.remove_btn.isEnabled():action('移除所选',self.remove_selected)
            if len(jobs)<len(self.jobs):action('全选任务',self.select_all_tasks)
        if not menu.actions():return
        position=self.queue_table.viewport().mapToGlobal(context_point) if context_point is not None else self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft())
        menu.exec(position)
    def select_status(self,statuses):self.selected_ids={j['id'] for j in self.jobs if j['status'] in statuses};self._scope_sync_requested=True;self.refresh_queue()
    def remove_completed(self):self.select_status({'done'});self.remove_selected()
    def undo_remove(self):
        if not self.undo_stack:return
        restore_removed(self.jobs,self.undo_stack.pop());self.undo_btn.setVisible(bool(self.undo_stack));self.refresh_queue();self.save_state();self.show_status('已恢复移除的任务。')
    def reprocess_selected(self):
        if self.running and self.active is None:return
        jobs=[j for j in self.selected_jobs() if j['status']!='pending']
        if not jobs:return
        for job in jobs:
            if job is self.active:
                if self.process:
                    if not self.restart_current:
                        self.restart_current=True;self.skip_current()
                else:self.reprocess_after_export.add(job['id'])
            else:self.mark_for_reprocessing(job)
        self.refresh_queue();self.save_state()
        self.show_status(f'已将 {len(jobs)} 集加入重新识别队列；已有字幕会在替换前备份。')

    @staticmethod
    def mark_for_reprocessing(job):
        job['status']='pending';job['processed_seconds']=0;job.pop('work_fraction',None);job['replace_output']=True
        for key in ('error','settings_changed','export_only','pending_reason','phase'):job.pop(key,None)
    def split_selected(self):
        if self.running:return
        jobs=self.selected_jobs()
        if not jobs:return
        group=str(Path(jobs[0]['source']).parent/('单独组-'+uuid.uuid4().hex[:6]))
        for j in jobs:
            j['series']=group;j.pop('roi',None);j.pop('detected_roi',None);j.pop('roi_override',None)
        self.refresh_queue();self.save_state()
    def clear_episode_override(self):
        if self.running:return
        for j in self.selected_jobs():
            if j.pop('roi_override',None):j['status']='pending';j['processed_seconds']=0;j.pop('work_fraction',None);j['replace_output']=True
        self.refresh_queue();self.save_state()
    def reconnect_source(self,job,path):
        if hasattr(self,'language_preview'):self.language_preview.cancel()
        count=relink_series(self.jobs,job,path)
        region=self.series_regions.get(series_key(job))
        if region:region['source']=job['source']
        if hasattr(self,'language_preview'):
            self.language_preview.attempted.clear()
        self.refresh_queue();self.save_state()
        self.show_status(f'已重新连接 {count} 集视频；同名文件已自动匹配。')
        if hasattr(self,'language_preview'):self.language_preview.start()
        return count
    def prompt_relink(self,job):
        path,_=QFileDialog.getOpenFileName(self,f'找不到 {Path(job["source"]).name}，请选择原视频的新位置',
            str(Path(job['source']).parent),'视频文件 (*.mp4 *.mkv *.mov *.m4v *.avi *.webm *.ts *.m2ts)')
        if not path:return False
        try:self.reconnect_source(job,path)
        except (OSError,ValueError) as error:self.show_error(str(error));return False
        return True
    def relocate_video(self):
        jobs=self.selected_jobs()
        if self.running or not jobs or len({series_key(j) for j in jobs})!=1:return
        self.prompt_relink(jobs[0])
    def show_processing_summary(self):
        from processing_summary import describe
        QMessageBox.information(self,'处理摘要',describe(self.selected_jobs()))

    def reexport_selected(self):
        from workspace_dialogs import export_dialog
        export_dialog(self)
    def show_cache(self):
        from workspace_dialogs import cache_dialog
        cache_dialog(self)
    def skip_current(self):
        if not self.process:return
        self.skipping=True;(self.control_dir/'stop').touch();(self.control_dir/'pause').unlink(missing_ok=True)
        if self.active:self.active['status']='stopping';self.queue_model.notify({self.active['id']})
        self.phase_label.setText('正在停止本集并重新排队…' if self.restart_current else '正在保存当前集进度，随后继续下一集…')
        process=self.process;QTimer.singleShot(95000,lambda:self.terminate_worker(process) if self.process is process and self.skipping else None)

    def add_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'添加视频','','视频文件 (*.mp4 *.mkv *.mov *.m4v *.avi *.webm *.ts *.m2ts)')
        if paths:self.import_paths(paths)
    def add_folder(self):
        path=QFileDialog.getExistingDirectory(self,'选择整季视频文件夹')
        if path:self.import_paths([path])
    def import_paths(self,paths):
        if self.running:self.show_status('请先停止队列，再添加视频，以便检查同名冲突。');return
        self.phase_label.show();self.phase_label.setText('正在扫描文件列表…')
        def scan():return import_entries(paths)
        def ready(entries):
            known={j['source'] for j in self.jobs}
            added=[]
            for source,relative,series,duration in entries:
                if source not in known:
                    settings=dict(self.defaults)
                    job={'id':uuid.uuid4().hex,'source':source,'relative':relative,'series':series,'status':'pending','roi':None,'settings':settings,'duration':duration,'source_missing':False}
                    self.jobs.append(job);added.append(job);known.add(source)
            if added:self.selected_ids={added[0]['id']};self._scope_sync_requested=True
            self.refresh_queue();self.save_state();self.phase_label.setText(f'扫描完成：队列中有 {len(self.jobs)} 个视频')
            self.language_preview.start()
        self.background_task(scan,ready)
    def set_drop_active(self,active):
        for widget in (self.queue_pane,self.empty_state):
            widget.setProperty('dropActive',active)
            widget.style().unpolish(widget);widget.style().polish(widget);widget.update()
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():self.set_drop_active(True);event.acceptProposedAction()
    def dragLeaveEvent(self,event):self.set_drop_active(False);event.accept()
    def dropEvent(self,event):
        self.set_drop_active(False)
        self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
    def selected_jobs(self):
        ids=set()
        for index in self.queue_table.selectionModel().selectedRows():ids.update(j['id'] for j in self.queue_model.jobs_at(index))
        return [j for j in self.jobs if j['id'] in ids]
    def remove_selected(self):
        jobs=self.selected_jobs()
        if self.active in jobs:
            self.show_status('选中项包含正在处理的集；请取消勾选本集或先停止任务。');return
        ids={j['id'] for j in jobs};snapshot=removal_snapshot(self.jobs,ids,self.active)
        if not snapshot:return
        removed={j['id'] for _,j in snapshot};self.undo_stack.append(snapshot);self.undo_stack=self.undo_stack[-20:]
        self.jobs[:]=[j for j in self.jobs if j['id'] not in removed];self.selected_ids=set();self.undo_btn.show();self.refresh_queue();self.save_state();self.show_status(f'已移除 {len(snapshot)} 个任务；可撤销。视频和字幕文件均保留。')
    def retry_failed(self):
        if self.process:return
        for j in self.jobs:
            if j['status'] in ['failed','interrupted']:j['status']='pending';j.pop('error',None)
        self.refresh_queue();self.save_state();self.start_queue()
    def choose_output(self):
        path=QFileDialog.getExistingDirectory(self,'选择字幕输出目录',self.output.text())
        if path:self.output.setText(path);self.commit_settings()
    def open_output(self):
        p=Path(self.output.text())
        if p.exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        else:self.show_status('输出目录将在开始处理时创建。')
    def set_roi(self,*args,single=False,target=None):
        selected=[target] if target else self.selected_jobs()
        if not selected: selected=[next((j for j in self.jobs if j['status'] in {'pending','interrupted'}),None)]
        selected=[j for j in selected if j]
        if len({series_key(j) for j in selected})>1:self.show_error('请只选择一部剧设置区域；不同剧不共用框选。');return
        jobs=selected if single else series_jobs(self.jobs,selected)
        if not jobs:return False
        if self.running:self.show_error('请先停止当前任务，再修改该视频的字幕区域。');return False
        if hasattr(self,'language_preview'):self.language_preview.cancel()
        dialog=CropDialog(Path(jobs[0]['source']),effective_roi(jobs[0],self.series_regions),self,count=len(jobs),engine=settings_for(jobs[0],self.defaults)['engine'],language=settings_for(jobs[0],self.defaults)['language'])
        if dialog.exec()==QDialog.DialogCode.Accepted:
            if dialog.relocated_path:
                try:self.reconnect_source(jobs[0],dialog.relocated_path)
                except (OSError,ValueError) as error:self.show_error(str(error));return False
            for j in jobs:
                if single:
                    j['roi_override']=list(dialog.canvas.roi);j['status']='pending';j['processed_seconds']=0;j.pop('work_fraction',None);j['replace_output']=True;continue
                j.pop('roi_override',None);self.change_roi(j,list(dialog.canvas.roi))
                self.series_regions[series_key(j)]={'roi':list(dialog.canvas.roi),'source':jobs[0]['source'],'manual':True}
                self.auto_region_groups.discard(series_key(j))
            record=dict(dialog.calibration or {},roi=list(dialog.canvas.roi),automatic=False,
                        aspect=dialog.meta['width']/dialog.meta['height'],source=jobs[0]['source'])
            target=self.state_dir/'series'/(__import__('hashlib').sha256((jobs[0]['id'] if single else series_key(jobs[0])).encode()).hexdigest()+'.json')
            target.parent.mkdir(parents=True,exist_ok=True);core.save_json(target,record)
            self.refresh_queue();self.save_state();return True
        return False
    @staticmethod
    def change_roi(job,roi):
        if job.get('roi')==roi:return
        job['roi']=roi;job['processed_seconds']=0;job.pop('work_fraction',None);job['status']='pending';job['replace_output']=True;job.pop('error',None)
    def clear_roi(self):
        if self.running:return
        selected=self.selected_jobs() or [next((j for j in self.jobs if j['status'] in {'pending','interrupted'}),None)]
        selected=[j for j in selected if j]
        if len({series_key(j) for j in selected})!=1:return
        for j in series_jobs(self.jobs,selected):
            j['replace_output']=True;j['status']='pending';j['processed_seconds']=0;j.pop('work_fraction',None)
            self.auto_region_groups.add(series_key(j))
            self.series_regions.pop(series_key(j),None);j.pop('detected_roi',None);j.pop('roi_override',None);self.change_roi(j,None)
            (self.state_dir/'series'/(__import__('hashlib').sha256(series_key(j).encode()).hexdigest()+'.json')).unlink(missing_ok=True)
        self.refresh_queue();self.save_state()

    def start_queue(self):
        self.language_preview.cancel()
        if self.process:return
        if any(t.isRunning() for t in self.background):self.show_status('正在读取文件，请稍候再开始。');return
        if self.overwrite.isChecked():
            for j in self.jobs:
                if j['status']=='done':j['status']='pending';j['processed_seconds']=0;j.pop('work_fraction',None);j['replace_output']=True
        if not any(j['status'] in ['pending','interrupted'] for j in self.jobs):self.show_status('请添加视频，或点击“继续未完成任务”。');return
        for job in self.jobs:
            if job['status'] not in {'pending','interrupted'}:continue
            if job.get('export_only') and Path(str(job.get('result_stem',''))+'.subtitles.json').is_file():continue
            if Path(job['source']).is_file():job['source_missing']=False;continue
            job['source_missing']=True;self.queue_model.notify({job['id']})
            self.phase_label.show();self.phase_label.setText(f'找不到原视频：{Path(job["source"]).name}。请重新定位后继续。')
            if not self.prompt_relink(job):return
        # Manual region is the primary route. Automatic placement is an explicit choice.
        for job in self.jobs:
            if job['status'] not in {'pending','interrupted'}:continue
            if job.get('export_only') and Path(str(job.get('result_stem',''))+'.subtitles.json').is_file():continue
            if effective_roi(job,self.series_regions) or series_key(job) in self.auto_region_groups:continue
            if not self.set_roi(target=job):return
        try:
            output=Path(self.output.text()).expanduser().resolve();output.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(output).free<512*1024**2:raise ValueError('输出磁盘剩余空间不足 512 MB。')
        except Exception as e:self.show_error(str(e));return
        for root in {settings_for(j,self.defaults)['output'] for j in self.jobs}:
            batch=[j for j in self.jobs if settings_for(j,self.defaults)['output']==root]
            for j,stem in zip(batch,output_stems([(j['source'],j['relative']) for j in batch],Path(root).expanduser().resolve())):j['planned_stem']=str(stem)
        self.stopping=False;self.set_running_ui(True);self.save_state();self.start_next()
    def set_running_ui(self,running):
        self.running=running;self.update_selection();self.pause_btn.setEnabled(running);self.stop_btn.setEnabled(running)
        if running:self.phase_label.show()
        for w in [self.settings_scope,self.add_file_btn,self.add_folder_btn,self.output,self.output_btn,self.profile,self.export_format,self.engine,self.device,self.language,self.memory,self.overwrite]:w.setEnabled(not running)
    def export_existing_job(self,job):
        """Apply format/location changes from a completed OCR record, without decoding."""
        from workspace_dialogs import export_results
        settings=settings_for(job,self.defaults);snapshot=dict(job)
        self.active=job;job['status']='running';job['phase']='导出已有识别结果';job.pop('error',None)
        self.job_started=time.monotonic();self.stage_started=self.job_started
        self.phase_label.setText(f'正在按新设置导出：{Path(job["source"]).name}')
        self.pause_btn.setEnabled(False);self.stop_btn.setEnabled(False)
        self.refresh_queue();self.save_state()
        def ready(results):
            job['export_stem']=results[0][1];job['status']='done';job['processed_seconds']=job.get('duration',0)
            for key in ('export_only','pending_reason','settings_changed','phase'):job.pop(key,None)
            if job['id'] in self.reprocess_after_export:
                self.reprocess_after_export.remove(job['id']);self.mark_for_reprocessing(job)
            self.active=None;self.refresh_queue();self.save_state();QTimer.singleShot(0,self.start_next)
        def failed(message):
            job['status']='failed';job['error']=message;self.active=None
            if job['id'] in self.reprocess_after_export:
                self.reprocess_after_export.remove(job['id']);self.mark_for_reprocessing(job)
            self.refresh_queue();self.save_state();QTimer.singleShot(0,self.start_next)
        thread=self.background_task(lambda:export_results([snapshot],Path(settings['output']),settings['format']),ready)
        thread.error.connect(failed)
    def start_next(self):
        if self.stopping or self.close_requested:self.finish_queue();return
        job=next((j for j in self.jobs if j['status'] in ['pending','interrupted']),None)
        if not job:self.finish_queue();return
        if job.get('export_only') and Path(str(job.get('result_stem',''))+'.subtitles.json').is_file():
            self.export_existing_job(job);return
        job.pop('export_only',None)
        self.active=job;job['status']='running';job.pop('error',None);self.refresh_queue();self.save_state();self.update_project_progress()
        self.pause_btn.setEnabled(True);self.stop_btn.setEnabled(True)
        if self.settings_scope.currentData()!=series_key(job):
            self.settings_scope.setCurrentIndex(self.settings_scope.findData(series_key(job)))
        self.control_dir=self.state_dir/'controls'/job['id'];self.control_dir.mkdir(parents=True,exist_ok=True)
        for f in ['pause','stop']:(self.control_dir/f).unlink(missing_ok=True)
        self.paused=False;self.pause_btn.setText('暂停');self.buffer='';self.job_started=time.monotonic();self.last_output=self.job_started;self.stage_started=self.job_started;self.stage_name='启动离线识别程序';self.last_progress=self.job_started;self.media_done=0;self.media_duration=0;self.speed_samples=[]
        settings=settings_for(job,self.defaults);engine=settings['engine'];resolved=hardware.resolve_engine(engine,settings['language']);device=self.device.currentData()
        policy=hardware.plan(resolved,self.profile.currentIndex(),self.memory.value(),device=device);workers=policy['workers'];threads=policy['threads']
        self.logs.appendPlainText(f"本集：{policy['backend']} · {workers} 个 OCR 进程 × {threads} 计算线程（仅 ONNX） · 可用内存 {policy['available_gb']} GB")
        same=[j for j in self.jobs if settings_for(j,self.defaults)['output']==settings['output']]
        planned=output_stems([(j['source'],j['relative']) for j in same],Path(settings['output']).expanduser().resolve())
        output=Path(job.get('planned_stem') or planned[same.index(job)]).parent
        if '_同名视频' in output.parts:self.logs.appendPlainText(f'同名视频已分目录保存：{output}')
        options=recognition_options(self.profile.currentIndex());strategy=options['strategy'];scale=options['scale']
        args=['extract',job['source'],'-o',str(output),'--organize-output','--strategy',strategy,'--scale',str(scale),'--format',settings['format'],'--engine',engine,'--device',device,'--language',settings['language'],'--workers',str(workers),'--threads',str(threads),'--memory-gb',str(self.memory.value()),'--control-dir',str(self.control_dir),'--cache-root',str(self.cache_root)]
        region=effective_roi(job,self.series_regions)
        if region and (job.get('roi_override') or self.series_regions.get(series_key(job),{}).get('manual',bool(job.get('roi')))):args+=['--roi',','.join(map(str,region))]
        args+=['--series-file',str(self.state_dir/'series'/(__import__('hashlib').sha256((job['id'] if job.get('roi_override') else series_key(job)).encode()).hexdigest()+'.json'))]
        if self.overwrite.isChecked() or job.get('replace_output'):args+=['--overwrite']
        executable=sys.executable
        if getattr(sys,'frozen',False):
            worker=Path(sys.executable).with_name('EllaPuedeWorker.exe' if os.name=='nt' else 'EllaPuedeWorker')
            if worker.exists():executable=str(worker)
        cmd=[executable]
        if not getattr(sys,'frozen',False):cmd+=[str(Path(__file__).resolve().parent.parent/'launch.py')]
        cmd+=['--batch-worker']
        if self.process and self.process.state()==QProcess.ProcessState.Running:
            self.process.write((json.dumps({'args':args})+'\n').encode('utf-8'));self.phase_label.setText(f'复用识别组件：{Path(job["source"]).name}');return
        proc=QProcess(self);self.process=proc;proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self.read_process);proc.finished.connect(self.process_finished);proc.errorOccurred.connect(self.process_error)
        from PySide6.QtCore import QProcessEnvironment
        env=QProcessEnvironment.systemEnvironment();env.insert('PYTHONUNBUFFERED','1');env.insert('PYTHONUTF8','1');env.insert('OMP_NUM_THREADS',str(threads));proc.setProcessEnvironment(env)
        proc.started.connect(lambda:proc.write((json.dumps({'args':args})+'\n').encode('utf-8')))
        proc.start(cmd[0],cmd[1:]);self.phase_label.setText(f'启动：{Path(job["source"]).name}')
    def process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            if self.active:self.active['error']='后台进程无法启动'
            self.process_finished(1,QProcess.ExitStatus.CrashExit)
    def read_process(self):
        if not self.process:return
        self.last_output=time.monotonic()
        self.buffer+=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if line.startswith('@@ELLAPUEDE@@'):
                try:self.handle_event(json.loads(line[len('@@ELLAPUEDE@@'):]))
                except (ValueError,KeyError):self.logs.appendPlainText(line)
            elif line.strip():self.logs.appendPlainText(line)
    def handle_event(self,e):
        kind=e['type']
        if kind in {'progress','verify_progress','region','result','paused','resumed','error'} and self.active is None:return
        if kind=='job_done':
            QTimer.singleShot(0,lambda:self.complete_job(e['code']));return
        if kind=='backend':self.logs.appendPlainText('实际计算后端：'+e['backend']);return
        if kind=='phase':
            if self.active:self.active['phase']=e['phase'];self.queue_model.notify({self.active['id']})
            if self.active:
                phase=e['phase']
                preparation=.01 if '检查视频' in phase else .03 if '对白区域' in phase or '定位字幕区域' in phase else .05 if '判断' in phase else .08 if '逐帧识别' in phase else 0
                if preparation:self.active['work_fraction']=max(self.active.get('work_fraction',0),preparation)
                self.update_project_progress()
            self.stage_name=e['phase'];self.stage_started=time.monotonic()
            if not self.active or self.active['status'] not in {'pausing','stopping','paused'}:self.phase_label.setText(e['phase'])
            self.logs.appendPlainText(time.strftime('%H:%M:%S')+' '+e['phase'])
            if '逐帧' not in e['phase'] and '整理字幕' not in e['phase']:self.update_project_progress()
        elif kind=='progress':
            self.stage_started=time.monotonic();self.last_progress=self.stage_started;self.media_done=e['seconds'];self.media_duration=e['duration'];self.progress.setRange(0,1000)
            self.active['duration']=e['duration'];self.active['processed_seconds']=max(0,e['seconds'])
            self.active['work_fraction']=max(self.active.get('work_fraction',0),.08+.72*min(1,e['seconds']/max(.001,e['duration'])))
            self.update_project_progress()
            if time.monotonic()-getattr(self,'last_workspace_save',0)>3:self.save_state();self.last_workspace_save=time.monotonic()
            now=time.monotonic();elapsed=max(1,now-self.job_started);self.active['elapsed_seconds']=round(elapsed,1)
            samples=getattr(self,'speed_samples',[]);samples.append((now,e['seconds']));samples=[x for x in samples if now-x[0]<=20];self.speed_samples=samples
            span=now-samples[0][0];advance=e['seconds']-samples[0][1];done=sum(j['status']=='done' for j in self.jobs)
            eta=f' · 扫描约剩 {(e["duration"]-e["seconds"])*span/advance/60:.1f} 分钟' if span>=8 and advance>1 else ' · 正在测量扫描速度'
            self.queue_model.notify({self.active['id']})
            if self.active['status'] not in {'pausing','stopping','paused'}:self.phase_label.setText(f'{Path(self.active["source"]).name} · 已扫描 {e["seconds"] / max(.001,e["duration"]):.0%}'+eta+f' · 全部 {done}/{len(self.jobs)} 集已导出')
        elif kind=='verify_progress':
            self.active['work_fraction']=max(self.active.get('work_fraction',0),.8+.18*e['done']/max(1,e['total']))
            self.active['phase']=f'复核画面 {e["done"]}/{e["total"]}'
            self.queue_model.notify({self.active['id']});self.update_project_progress()
            if self.active['status'] not in {'pausing','stopping','paused'}:
                self.phase_label.setText(f'{Path(self.active["source"]).name} · 复核画面 {e["done"]}/{e["total"]} · 项目进度 {self.progress.value()/10:.1f}%')
        elif kind=='region':
            self.active['detected_roi']=e['roi']
            if not self.active.get('roi_override'):
                self.series_regions[series_key(self.active)]={'roi':e['roi'],'source':self.active['source'],'manual':not e.get('automatic',False)}
                for job in series_jobs(self.jobs,[self.active]):
                    if not job.get('roi_override'):job['detected_roi']=e['roi']
            self.queue_model.notify();self.save_state();self.region_mode.setText('已锁定本剧对白区域 · 停止后可调整')
        elif kind=='resources':self.resource_label.setText(f'处理进程内存 {e["rss_mb"]} MB · 峰值 {e["peak_mb"]} MB')
        elif kind=='result':
            self.active['work_fraction']=.99
            self.active['performance']=e.get('performance',{});self.active['cached_result']=e.get('cached',False);self.active['backend']=e.get('backend','')
            self.active['flag_counts']=e.get('flag_counts',{});self.active['result_stem']=e['stem'];self.active['export_stem']=e.get('export_stem','');self.active['events']=e['events'];self.active['flagged']=e['flagged'];self.update_project_progress()
            if e.get('resolved_languages'):
                self.active['resolved_languages']=e['resolved_languages'];self.update_language_presentation();self.queue_model.notify({self.active['id']})
        elif kind=='language':
            resolved=[x for x in (e.get('resolved') or []) if x and x != 'auto']
            if self.active and resolved:
                self.active['resolved_languages']=resolved
                self.active['detected_language']=e.get('detected') or resolved[0]
                for job in series_jobs(self.jobs,[self.active]):
                    if settings_for(job,self.defaults)['language']=='auto':job['resolved_languages']=resolved
                self.update_language_presentation();self.queue_model.notify();self.save_state()
        elif kind=='warning':
            self.logs.appendPlainText(e['message'])
            if self.active:
                warnings=self.active.setdefault('warnings',[])
                if e['message'] not in warnings:warnings.append(e['message'])
                self.queue_model.notify({self.active['id']})
        elif kind=='error':
            self.active['error']=e['message']
            if e.get('action')=='choose_language':
                for job in series_jobs(self.jobs,[self.active]):
                    if job is not self.active and job['status']=='pending' and settings_for(job,self.defaults)['language']=='auto':
                        job['status']='failed';job['error']=e['message'];job['language_phase']='请选择原语言'
                self.queue_model.notify();self.save_state()
        elif kind=='paused':
            if self.paused and not self.stopping:self.phase_label.setText('已暂停，进度已保留');self.active['status']='paused';self.refresh_queue()
        elif kind=='resumed':
            if not self.paused and not self.stopping:self.active['status']='running';self.refresh_queue()
    def complete_job(self,exit_code):
        if not self.active:return
        job=self.active;job['status']='done' if exit_code==0 else 'interrupted' if self.stopping or exit_code==130 else 'failed'
        if self.restart_current:
            self.mark_for_reprocessing(job);self.restart_current=False;self.skipping=False
        elif self.skipping:job['status']='failed';job['error']='已跳过当前集，可稍后继续';self.skipping=False
        if job['status']=='failed' and not job.get('error'):job['error']='处理未完成，请查看运行详情后重试。'
        if job['status']=='done':
            for key in ('replace_output','settings_changed','pending_reason','export_only'):job.pop(key,None)
        job['elapsed_seconds']=round(time.monotonic()-self.job_started,1)
        from control_cleanup import clean_finished_controls
        clean_finished_controls(self.state_dir/'controls',[job['id']],[j['id'] for j in self.jobs if j is not job])
        self.write_runtime_log();self.active=None;self.refresh_queue();self.save_state();QTimer.singleShot(100,self.start_next)
    def process_finished(self,exit_code,exit_status):
        if self.process is None:return
        self.read_process();proc=self.process;self.process=None;proc.deleteLater()
        if self.active:self.complete_job(exit_code or 1)
        self.maybe_finish_close()
    def toggle_pause(self):
        if not self.process or not self.active or self.stopping:return
        self.paused=not self.paused
        if self.paused:(self.control_dir/'pause').touch();self.pause_btn.setText('继续');self.phase_label.setText('等待当前帧处理完成后暂停…');self.active['status']='pausing';self.queue_model.notify({self.active['id']})
        else:(self.control_dir/'pause').unlink(missing_ok=True);self.pause_btn.setText('暂停');self.speed_samples=[];self.active['status']='running';self.queue_model.notify({self.active['id']});self.phase_label.setText('正在继续处理…')
    def stop_queue(self):
        self.stopping=True
        if self.process:
            if self.active:
                (self.control_dir/'stop').touch();(self.control_dir/'pause').unlink(missing_ok=True)
            else:
                self.process.write(b'{"shutdown":true}\n');self.process.closeWriteChannel()
            if self.active:self.active['status']='stopping';self.queue_model.notify({self.active['id']})
            self.phase_label.setText('正在保存进度并停止…');self.stop_btn.setEnabled(False);self.pause_btn.setEnabled(False)
            process=self.process
            QTimer.singleShot(10000,lambda:self.terminate_worker(process) if self.process is process and self.stopping else None)
        else:self.finish_queue()
    def terminate_worker(self,process):
        if self.process is not process:return
        try:
            import psutil
            parent=psutil.Process(int(process.processId()))
            for child in parent.children(recursive=True):
                try:child.kill()
                except psutil.Error:pass
        except Exception:pass
        process.kill()
    def write_runtime_log(self):
        try:(self.state_dir/'runtime.log').write_text(self.logs.toPlainText(),encoding='utf-8')
        except OSError:pass
    def save_diagnostics(self):
        filename,_=QFileDialog.getSaveFileName(self,'保存运行日志','EllaPuede-运行日志.txt','文本文件 (*.txt)')
        if filename:
            text=f'EllaPuede {VERSION}\n'+hardware.description()+'\n\n当前状态：'+self.phase_label.text()+'\n\n'+self.logs.toPlainText()
            try:Path(filename).write_text(text,encoding='utf-8');self.show_status('运行日志已保存。')
            except OSError as e:self.show_error(str(e))
    def finish_queue(self):
        if self.process:
            self.process.write(b'{"shutdown":true}\n');self.process.closeWriteChannel()
        self.update_project_progress();self.set_running_ui(False);self.phase_label.setText('进度已保存，点击开始可继续。' if self.stopping else f'处理结束：{sum(j["status"]=="done" for j in self.jobs)} 个视频已导出；{sum(j["status"]=="failed" for j in self.jobs)} 个未完成。点击“打开字幕文件夹”查看。');self.pause_btn.setText('暂停');self.save_state()
        self.maybe_finish_close()
    def update_resources(self):
        now=time.monotonic();last=getattr(self,'last_watchdog_tick',now);self.last_watchdog_tick=now
        if now-last>30 and self.process:
            self.last_output=now;self.last_progress=now;self.stage_started=now;self.logs.appendPlainText('检测到系统休眠或界面长时间暂停，重新等待后台响应。')
        if self.process and self.active:
            now=time.monotonic();elapsed=int(now-self.job_started);waiting=int(now-self.stage_started)
            message=f'本集已用 {elapsed} 秒'
            if not self.paused and not self.stopping and waiting>=15:message+=f' · 当前阶段已等待 {waiting} 秒；可打开高级选项查看或保存日志'
            self.show_status(message)
            if not self.paused and not self.stopping and now-self.last_progress>60 and self.media_done:
                message+=f' · 已 {int(now-self.last_progress)} 秒无识别进展';self.show_status(message)
            if now-self.last_output>180 and not self.paused and not self.stopping:
                self.active['error']='后台连续 180 秒没有反馈，已停止本集。请保存运行日志后重试。';self.logs.appendPlainText(self.active['error']);self.terminate_worker(self.process)
            self.write_runtime_log();return
        try:
            import psutil
            mem=psutil.virtual_memory();self.resource_label.setText(f'系统可用内存 {mem.available/1024**3:.1f} GB · 空闲')
        except ImportError:pass

    def open_selected_output(self,*args):
        jobs=self.selected_jobs()
        if jobs and jobs[0].get('export_stem'):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(jobs[0]['export_stem']).parent)))
        else:self.open_output()

    def closeEvent(self,event):
        self.close_requested=True
        self.language_preview.cancel()
        if self.process:
            if not self.stopping:self.stop_queue()
            self.show_status('正在保存后台进度；停止完成后自动关闭。');event.ignore();return
        for thread in self.background:
            if thread.isRunning():self.show_status('文件读取完成后自动关闭。');event.ignore();return
        try:self.save_state()
        except OSError as error:
            self.close_requested=False;self.show_error(f'无法保存任务状态：{error}');event.ignore();return
        app=QApplication.instance()
        if getattr(app,'window',None) is self:
            app.shutdown_ready=True
            QTimer.singleShot(0,app.quit)
        event.accept()

def main():
    app=DesktopApplication(sys.argv);app.setOrganizationName('EllaPuede')
    # Keep the historical application-data directory across upgrades; the
    # visible product name is APP_NAME / CFBundleDisplayName.
    app.setApplicationName('EllaPuede Subtitle Studio');app.setStyle('Fusion');app.setStyleSheet(STYLE)
    if sys.platform=='darwin':QAccessible.installFactory(_mac_queue_accessibility)
    from PySide6.QtCore import QLockFile
    state_dir=Path(os.environ.get('ELLAPUEDE_DATA_DIR') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation));state_dir.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(state_dir/'application.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None,APP_NAME,'EllaPuede 已在运行，请使用现有窗口。');return 0
    window=MainWindow();app.window=window;app.setQuitOnLastWindowClosed(True);window.show()
    if len(sys.argv)>1:QTimer.singleShot(0,lambda:window.import_paths(sys.argv[1:]))
    return app.exec()

if __name__=='__main__':raise SystemExit(main())
