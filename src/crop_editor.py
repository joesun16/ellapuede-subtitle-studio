"""Native, keyboard-accessible subtitle region editor with cancellable preview."""
from __future__ import annotations
import base64,json,os,sys
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPointF,QProcess,QTimer,Signal,QProcessEnvironment,QElapsedTimer
from PySide6.QtGui import QColor,QPainter,QPen,QPixmap,QPalette,QShortcut,QKeySequence
from PySide6.QtWidgets import (QWidget,QDialog,QApplication,QVBoxLayout,QHBoxLayout,QGridLayout,
    QLabel,QPushButton,QSlider,QDoubleSpinBox,QDialogButtonBox,QSizePolicy,QScrollArea,QLayout,QFileDialog,QStyle,QStyleOptionSlider)
from ui_theme import polish_controls

DEFAULT_ROI=(.02,.60,.98,.85)
class SeekSlider(QSlider):
    """Click or drag anywhere on the track, without waiting for Qt's page step."""
    def position_value(self,point):
        option=QStyleOptionSlider();self.initStyleOption(option)
        groove=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,self)
        handle=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,self)
        span=max(1,groove.width()-handle.width())
        return QStyle.sliderValueFromPosition(self.minimum(),self.maximum(),round(point.x()-groove.x()-handle.width()/2),span,option.upsideDown)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.setSliderDown(True);self.setValue(self.position_value(event.position()));event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.isSliderDown():self.setValue(self.position_value(event.position()));event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setValue(self.position_value(event.position()));self.setSliderDown(False);event.accept();return
        super().mouseReleaseEvent(event)

class CropCanvas(QWidget):
    changed=Signal(tuple)
    interactionStarted=Signal()
    def __init__(self):
        super().__init__();self.pixmap=QPixmap();self.roi=DEFAULT_ROI;self.drag=None;self.draw_new=False;self.candidates=[]
        self.source_size=(1000,1000);self.placeholder='正在读取视频画面…';self.setMinimumSize(320,240);self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.setAccessibleName('字幕区域：拖动内部移动，拖动边角缩放；方向键微调，Shift 加速，Ctrl 调整右下边界')
    def image_rect(self):
        if self.pixmap.isNull():return QRectF()
        s=self.pixmap.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width()-s.width())/2,(self.height()-s.height())/2,s.width(),s.height())
    def selection_rect(self):
        r=self.image_rect();a,b,c,d=self.roi
        return QRectF(r.x()+a*r.width(),r.y()+b*r.height(),(c-a)*r.width(),(d-b)*r.height())
    def handles(self):
        r=self.selection_rect();x,y=r.center().x(),r.center().y()
        return {'lt':r.topLeft(),'t':QPointF(x,r.top()),'rt':r.topRight(),'r':QPointF(r.right(),y),
                'rb':r.bottomRight(),'b':QPointF(x,r.bottom()),'lb':r.bottomLeft(),'l':QPointF(r.left(),y)}
    def hit(self,p):
        if self.draw_new:return 'new'
        nearby=[((p-pt).manhattanLength(),name) for name,pt in self.handles().items() if abs(p.x()-pt.x())<=9 and abs(p.y()-pt.y())<=9]
        if nearby:return min(nearby)[1]
        r=self.selection_rect()
        if r.adjusted(-6,-6,6,6).contains(p):
            for name,dist in [('l',abs(p.x()-r.left())),('r',abs(p.x()-r.right())),('t',abs(p.y()-r.top())),('b',abs(p.y()-r.bottom()))]:
                if dist<=6:return name
            if r.contains(p):return 'move'
        return 'new'
    def point(self,p):
        r=self.image_rect()
        return (max(0,min(1,(p.x()-r.x())/max(1,r.width()))),max(0,min(1,(p.y()-r.y())/max(1,r.height()))))
    def set_roi(self,values):
        a,b,c,d=(max(0,min(1,float(v))) for v in values)
        if c-a<self.minimum()[0] or d-b<self.minimum()[1]:return False
        self.roi=(a,b,c,d);self.update();self.changed.emit(self.roi);return True
    def minimum(self):return (min(.05,8/max(1,self.source_size[0])),min(.05,8/max(1,self.source_size[1])))
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#17231f'));r=self.image_rect()
        if r.isEmpty():
            p.setPen(QColor('#d8e7de'));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.placeholder);return
        p.drawPixmap(r,self.pixmap,QRectF(self.pixmap.rect()));s=self.selection_rect()
        p.fillRect(QRectF(r.left(),r.top(),r.width(),s.top()-r.top()),QColor(0,0,0,120))
        p.fillRect(QRectF(r.left(),s.bottom(),r.width(),r.bottom()-s.bottom()),QColor(0,0,0,120))
        p.fillRect(QRectF(r.left(),s.top(),s.left()-r.left(),s.height()),QColor(0,0,0,120))
        p.fillRect(QRectF(s.right(),s.top(),r.right()-s.right(),s.height()),QColor(0,0,0,120))
        p.setPen(QPen(QColor('#68e3ae'),2));p.drawRect(s);p.setBrush(QColor('#ffffff'))
        for pt in self.handles().values():p.drawRect(QRectF(pt.x()-4,pt.y()-4,8,8))
        for candidate in self.candidates:
            a,b,c,d=candidate['roi'];p.fillRect(QRectF(r.right()-6,r.y()+b*r.height(),6,(d-b)*r.height()),QColor('#68e3ae'))
        if self.hasFocus():p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor('#68e3ae'),1,Qt.PenStyle.DotLine));p.drawRect(self.rect().adjusted(2,2,-3,-3))
    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or not self.image_rect().contains(event.position()):return
        self.interactionStarted.emit()
        self.setFocus();self.drag=(self.hit(event.position()),self.point(event.position()),self.roi,event.position())
    def mouseMoveEvent(self,event):
        if self.drag:self.update_drag(event.position());return
        mode=self.hit(event.position()) if self.image_rect().contains(event.position()) else ''
        cursors={'move':Qt.CursorShape.SizeAllCursor,'l':Qt.CursorShape.SizeHorCursor,'r':Qt.CursorShape.SizeHorCursor,
                 't':Qt.CursorShape.SizeVerCursor,'b':Qt.CursorShape.SizeVerCursor,'lt':Qt.CursorShape.SizeFDiagCursor,'rb':Qt.CursorShape.SizeFDiagCursor,
                 'rt':Qt.CursorShape.SizeBDiagCursor,'lb':Qt.CursorShape.SizeBDiagCursor,'new':Qt.CursorShape.CrossCursor}
        self.setCursor(cursors.get(mode,Qt.CursorShape.ArrowCursor))
    def update_drag(self,p):
        mode,(x0,y0),(a,b,c,d),origin=self.drag;x,y=self.point(p);dx=x-x0;dy=y-y0;mw,mh=self.minimum()
        if mode=='new':
            if (p-origin).manhattanLength()<4:return
            self.set_roi((min(x,x0),min(y,y0),max(x,x0),max(y,y0)));return
        if mode=='move':
            dx=max(-a,min(1-c,dx));dy=max(-b,min(1-d,dy));self.set_roi((a+dx,b+dy,c+dx,d+dy));return
        if 'l' in mode:a=max(0,min(c-mw,a+dx))
        if 'r' in mode:c=min(1,max(a+mw,c+dx))
        if 't' in mode:b=max(0,min(d-mh,b+dy))
        if 'b' in mode:d=min(1,max(b+mh,d+dy))
        self.set_roi((a,b,c,d))
    def mouseReleaseEvent(self,event):
        if self.drag and event.button()==Qt.MouseButton.LeftButton:
            mode,_,_,origin=self.drag
            if mode=='new' and not self.draw_new and (event.position()-origin).manhattanLength()<4:
                _,y=self.point(event.position());matches=[x for x in self.candidates if x['roi'][1]<=y<=x['roi'][3]]
                if matches:self.set_roi(max(matches,key=lambda x:x.get('score',0))['roi'])
            else:self.update_drag(event.position())
            self.drag=None;self.draw_new=False;self.update()
    def keyPressEvent(self,event):
        delta={Qt.Key.Key_Left:(-1,0),Qt.Key.Key_Right:(1,0),Qt.Key.Key_Up:(0,-1),Qt.Key.Key_Down:(0,1)}.get(event.key())
        if not delta:return super().keyPressEvent(event)
        self.interactionStarted.emit()
        speed=10 if event.modifiers()&Qt.KeyboardModifier.ShiftModifier else 1
        dx=delta[0]*speed/max(1,self.source_size[0]);dy=delta[1]*speed/max(1,self.source_size[1]);a,b,c,d=self.roi
        if event.modifiers()&Qt.KeyboardModifier.ControlModifier:self.set_roi((a,b,c+dx,d+dy))
        else:
            dx=max(-a,min(1-c,dx));dy=max(-b,min(1-d,dy));self.set_roi((a+dx,b+dy,c+dx,d+dy))
        event.accept()

class CropDialog(QDialog):
    def __init__(self,path,roi,parent=None,count=1,engine="auto",language="auto"):
        super().__init__(parent);self.path=Path(path);self.relocated_path=None;self.series_count=count;self.meta=None;self.process=None;self.closed=False;self.detect_roi=False;self.engine=engine;self.language=language;self.calibration=None;self.read_roi=False;self.failure_reason=None
        self.preview_buffer='';self.preview_busy=False;self.preview_pending=None;self.preview_number=0
        self.playing=False;self.play_clock=QElapsedTimer();self.play_anchor=0.;self.display_seconds=0.
        self.play_timer=QTimer(self);self.play_timer.setInterval(33);self.play_timer.setTimerType(Qt.TimerType.PreciseTimer);self.play_timer.timeout.connect(self.play_tick)
        self.setWindowTitle('EllaPuede · 字幕区域');self.resize(1020,720);self.setMinimumSize(860,600)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,24);layout.setSpacing(12)
        title=QLabel('框选对白字幕区域');title.setObjectName('title');layout.addWidget(title)
        self.caption=QLabel(f'{self.path.name}'+(f' · 区域将应用到整剧共 {count} 个视频' if count>1 else ''));self.caption.setWordWrap(True);layout.addWidget(self.caption)
        row=QHBoxLayout();row.setSpacing(16);self.canvas=CropCanvas();self.canvas.roi=tuple(roi or DEFAULT_ROI);row.addWidget(self.canvas,1)
        side=QWidget();side.setObjectName('cropSidebar');side.setFixedWidth(240)
        side_palette=side.palette();side_palette.setColor(QPalette.ColorRole.Window,QColor('white'))
        side.setPalette(side_palette);side.setAutoFillBackground(True)
        sl=QVBoxLayout(side);sl.setContentsMargins(0,0,0,0);sl.setSpacing(12);sl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        preview_title=QLabel('框内预览');preview_title.setObjectName('sectionTitle');sl.addWidget(preview_title)
        self.preview=QLabel();self.preview.setFixedSize(240,124);self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setStyleSheet('background:#17231f;border-radius:8px;');sl.addWidget(self.preview)
        self.canvas.setToolTip('拖动框内移动；拖动边角调整；在框外拖动重新框选。')
        self.redraw=QPushButton('重新框选');self.redraw.setObjectName('softPrimary');self.redraw.clicked.connect(self.new_selection);sl.addWidget(self.redraw)
        self.read_button=QPushButton('识别当前框内文字');self.read_button.setEnabled(False);self.read_button.clicked.connect(self.read_selection);sl.addWidget(self.read_button)
        self.reading=QLabel('');self.reading.setWordWrap(True);self.reading.setMaximumHeight(100);self.reading.hide();sl.addWidget(self.reading)
        secondary_title=QLabel('辅助调整');secondary_title.setObjectName('muted');sl.addWidget(secondary_title)
        self.locate=QPushButton('查找字幕位置');self.locate.clicked.connect(self.find_region);sl.addWidget(self.locate)
        self.reset=QPushButton('重置区域');self.reset.clicked.connect(self.pause_playback);self.reset.clicked.connect(lambda:self.canvas.set_roi(DEFAULT_ROI));sl.addWidget(self.reset)
        self.precision=QPushButton('精确调整');self.precision.setCheckable(True);sl.addWidget(self.precision)
        self.precision_dialog=QDialog(self);self.precision_dialog.setWindowTitle('EllaPuede · 精确调整字幕区域');self.precision_dialog.setWindowModality(Qt.WindowModality.WindowModal);self.precision_dialog.setMinimumSize(360,350)
        precise_layout=QVBoxLayout(self.precision_dialog);precise_layout.setContentsMargins(24,24,24,24);precise_layout.setSpacing(16)
        precise_layout.addWidget(QLabel('坐标为视频宽度 / 高度的百分比'))
        coords=QWidget();grid=QGridLayout(coords);grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(16);grid.setVerticalSpacing(12);grid.setColumnStretch(1,1);self.coords=[]
        for i,name in enumerate(('左','上','右','下')):
            spin=QDoubleSpinBox();spin.setRange(0,100);spin.setDecimals(1);spin.setSuffix(' %');spin.setSingleStep(.1);spin.setValue(self.canvas.roi[i]*100)
            spin.setAccessibleName('区域'+name+'边界百分比');spin.editingFinished.connect(self.apply_coords);self.coords.append(spin);grid.addWidget(QLabel(name),i,0);grid.addWidget(spin,i,1)
        precise_layout.addWidget(coords);back=QPushButton('返回画面');back.clicked.connect(self.precision_dialog.accept);precise_layout.addWidget(back)
        self.precision.toggled.connect(lambda visible:self.pause_playback() if visible else None)
        self.precision.toggled.connect(self.precision_dialog.setVisible);self.precision_dialog.finished.connect(lambda _:self.precision.setChecked(False))
        sl.addStretch();sidebar=QScrollArea();sidebar.setObjectName('cropSidebarScroll')
        sidebar.setFrameShape(QScrollArea.Shape.NoFrame);sidebar.setWidgetResizable(True);sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);sidebar.setFixedWidth(260)
        sidebar.viewport().setObjectName('cropSidebarViewport');sidebar.viewport().setPalette(side_palette);sidebar.viewport().setAutoFillBackground(True)
        sidebar.setWidget(side);row.addWidget(sidebar);layout.addLayout(row,1)
        timebar=QHBoxLayout();self.previous=QPushButton('前 1 秒');self.next=QPushButton('后 1 秒');self.slider=SeekSlider(Qt.Orientation.Horizontal);self.slider.setRange(0,1000);self.slider.setValue(330);self.slider.setAccessibleName('视频预览时间；点击或拖动立即选择时间');self.slider.setEnabled(False)
        self.play_button=QPushButton('播放');self.play_button.setFixedWidth(80);self.play_button.setEnabled(False);self.play_button.setToolTip('播放 / 暂停画面（空格，无声预览）');self.play_button.clicked.connect(self.toggle_play)
        self.play_shortcut=QShortcut(QKeySequence(Qt.Key.Key_Space),self);self.play_shortcut.activated.connect(self.toggle_play)
        self.time_label=QLabel('读取中');self.time_label.setFixedWidth(142);self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter);timebar.addWidget(self.play_button);timebar.addWidget(self.previous);timebar.addWidget(self.slider,1);timebar.addWidget(self.next);timebar.addWidget(self.time_label);layout.addLayout(timebar)
        self.previous.setEnabled(False);self.next.setEnabled(False)
        self.info=QLabel('');self.info.setObjectName('muted');self.info.setFixedHeight(20);layout.addWidget(self.info)
        footer=QHBoxLayout();self.relink=QPushButton('重新定位视频');self.relink.clicked.connect(self.relocate_source);self.relink.hide();footer.addWidget(self.relink)
        self.retry=QPushButton('重新读取');self.retry.clicked.connect(self.load);self.retry.hide();footer.addWidget(self.retry);footer.addStretch()
        self.cancel=QPushButton('取消');self.cancel.clicked.connect(self.reject);self.apply=QPushButton('应用字幕区域');self.apply.setObjectName('primary');self.apply.setEnabled(False);self.apply.clicked.connect(self.accept);footer.addWidget(self.cancel);footer.addWidget(self.apply);layout.addLayout(footer)
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.setInterval(45);self.debounce.timeout.connect(self.load)
        self.slider.valueChanged.connect(self.seek);self.slider.sliderReleased.connect(self.load);self.previous.clicked.connect(lambda:self.step(-1));self.next.clicked.connect(lambda:self.step(1));self.canvas.changed.connect(self.sync_roi)
        self.slider.sliderPressed.connect(self.pause_playback);self.canvas.interactionStarted.connect(self.pause_playback)
        polish_controls(self);self.load()
    def set_info(self,message):
        self.info.setText(message);self.info.setToolTip(message)
    def relocate_source(self):
        path,_=QFileDialog.getOpenFileName(self,'选择原视频的新位置',str(self.path.parent),
            '视频文件 (*.mp4 *.mkv *.mov *.m4v *.avi *.webm *.ts *.m2ts)')
        if not path:return
        candidate=Path(path).resolve()
        if not candidate.is_file():
            self.show_failure('选择的视频不存在，请重新定位。',missing=True);return
        self.cancel_process();self.path=candidate;self.relocated_path=candidate;self.meta=None
        self.canvas.pixmap=QPixmap();self.canvas.placeholder='正在读取视频画面…';self.canvas.update()
        self.preview.clear();self.preview_buffer='';self.slider.blockSignals(True);self.slider.setValue(330);self.slider.blockSignals(False)
        self.caption.setText(candidate.name+(f' · 区域将应用到整剧共 {self.series_count} 个视频' if self.series_count>1 else ''))
        self.load()
    def show_failure(self,message,missing=False):
        self.pause_playback();self.play_button.setEnabled(False)
        self.failure_reason=message;self.set_info(message);self.info.setToolTip(str(self.path));self.retry.setVisible(not missing)
        self.relink.show();usable=not missing and self.meta is not None and not self.canvas.pixmap.isNull()
        self.apply.setEnabled(usable);self.read_button.setEnabled(False)
        self.previous.setEnabled(usable);self.next.setEnabled(usable);self.slider.setEnabled(usable)
        for control in (self.redraw,self.reset,self.locate,self.precision):control.setEnabled(usable)
        if not usable:
            self.canvas.pixmap=QPixmap();self.canvas.placeholder='找不到原视频，请点击“重新定位视频”' if missing else '暂时无法预览视频画面';self.canvas.update();self.preview.clear()
        self.reading.hide()
    def new_selection(self):
        self.pause_playback()
        self.canvas.draw_new=True;self.canvas.setCursor(Qt.CursorShape.CrossCursor);self.canvas.setFocus();self.set_info('在画面上拖动以重新框选。')
    def find_region(self):
        self.pause_playback()
        self.detect_roi=True;self.load()
    def read_selection(self):
        self.pause_playback()
        self.set_position(self.display_seconds)
        self.read_roi=True;self.load()
    def sync_roi(self,roi):
        if self.calibration and tuple(self.calibration['roi'])!=tuple(roi):self.calibration=None
        self.reading.hide()
        for spin,value in zip(self.coords,roi):spin.setValue(value*100)
        if self.canvas.pixmap.isNull():return
        p=self.canvas.pixmap;a,b,c,d=roi;crop=p.copy(round(a*p.width()),round(b*p.height()),max(1,round((c-a)*p.width())),max(1,round((d-b)*p.height())))
        self.preview.setPixmap(crop.scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def apply_coords(self):
        self.pause_playback()
        if not self.canvas.set_roi([s.value()/100 for s in self.coords]):
            self.sync_roi(self.canvas.roi);self.set_info('区域不能倒置或小于 8 像素，已保留上一次有效区域。')
    def seek(self):
        if self.meta:
            target=self.selected_seconds()
            self.pause_playback()
            self.set_position(target)
            self.time_label.setText(f'{self.selected_seconds():.2f} / {self.meta["duration"]:.2f} 秒')
            # Throttle rather than restarting a debounce on every mouse move:
            # continuously dragging must still produce preview frames.
            if not self.debounce.isActive():self.debounce.start()
    def step(self,direction):
        if self.meta:self.slider.setValue(self.slider.value()+round(direction*self.slider.maximum()/max(.001,self.meta['duration'])))
    def selected_seconds(self):
        return self.slider.value()/max(1,self.slider.maximum())*self.meta['duration'] if self.meta else 0.
    def set_position(self,seconds):
        self.slider.blockSignals(True)
        self.slider.setValue(round(seconds/max(.001,self.meta['duration'])*self.slider.maximum()))
        self.slider.blockSignals(False)
        self.time_label.setText(f'{seconds:.2f} / {self.meta["duration"]:.2f} 秒')
    def pause_playback(self):
        if not self.playing:return
        self.playing=False;self.play_timer.stop();self.play_button.setText('播放')
        self.preview_number+=1;self.preview_pending=None
        if self.meta:self.set_position(self.display_seconds)
    def toggle_play(self):
        if not self.play_button.isEnabled() or self.closed:return
        if self.playing:
            self.pause_playback();self.load();return
        self.debounce.stop()
        self.play_anchor=self.selected_seconds()
        if self.play_anchor>=self.meta['duration']-.1:self.play_anchor=0.;self.set_position(0.)
        self.playing=True;self.play_button.setText('暂停');self.play_clock.start();self.play_timer.start();self.play_tick()
    def play_tick(self):
        if not self.playing or self.closed:return
        seconds=self.play_anchor+self.play_clock.elapsed()/1000
        if seconds>=self.meta['duration']-.001:
            self.pause_playback();self.set_position(max(0,self.meta['duration']-.001));self.load();return
        # One in-flight request bounds memory. The wall clock skips stale
        # preview frames under load; extraction never skips video frames.
        if self.preview_busy:return
        self.set_position(seconds);self.load()
    def cancel_process(self):
        self.pause_playback()
        p=self.process;self.process=None
        self.preview_busy=False;self.preview_pending=None
        if p:
            p.blockSignals(True)
            if p.state()!=QProcess.ProcessState.NotRunning:
                p.kill();p.waitForFinished(500)
            p.deleteLater()
    def load(self):
        if self.closed:return
        self.debounce.stop();self.retry.hide();self.relink.hide();self.failure_reason=None
        if self.canvas.pixmap.isNull():self.apply.setEnabled(False);self.canvas.placeholder='正在读取视频画面…';self.canvas.update()
        if self.detect_roi or self.read_roi:
            self.read_button.setEnabled(False)
            self.set_info('正在自动定位字幕区域…' if self.detect_roi else '正在识别框内文字…')
        else:self.set_info('')
        if not self.path.is_file():
            self.cancel_process()
            self.show_failure(f'找不到原视频：{self.path.name}。视频可能已移动或删除，请重新定位。',missing=True)
            return
        self.preview_number+=1
        request={'request_id':self.preview_number,'engine':self.engine,'language':self.language}
        if self.meta:request['seconds']=self.selected_seconds()
        request['fast']=self.playing or self.slider.isSliderDown()
        if self.detect_roi:request['detect_roi']=True
        if self.read_roi:request['read_roi']=','.join(map(str,self.canvas.roi))
        self.detect_roi=False;self.read_roi=False;self.preview_pending=request
        if self.process and self.process.state()==QProcess.ProcessState.Running:
            self.send_preview_request();return
        self.preview_busy=False;self.preview_buffer=''
        executable=sys.executable;args=[]
        if getattr(sys,'frozen',False):executable=str(Path(sys.executable).with_name('EllaPuedeWorker.exe' if os.name=='nt' else 'EllaPuedeWorker'))
        else:args=[str(Path(__file__).resolve().parent.parent/'launch.py')]
        args+=['--preview-worker',str(self.path),'--serve']
        # Parent survives this dialog: closing never waits on a decoder thread.
        p=QProcess(QApplication.instance());self.process=p;env=QProcessEnvironment.systemEnvironment();env.insert('PYTHONUTF8','1');p.setProcessEnvironment(env)
        timer=QTimer(p);timer.setSingleShot(True)
        p.preview_timer=timer
        def failure(message):
            if self.process is p and not self.closed:
                self.show_failure(message,missing=not self.path.is_file())
        def ready():
            self.preview_buffer+=bytes(p.readAllStandardOutput()).decode('utf-8','replace')
            while '\n' in self.preview_buffer:
                line,self.preview_buffer=self.preview_buffer.split('\n',1)
                try:data=json.loads(line)
                except ValueError:continue
                timer.stop();self.preview_busy=False
                if self.closed or self.process is not p:return
                if data.get('error') and data.get('request_id') is None:
                    failure('找不到原视频，请重新定位。' if data.get('code')=='source_missing' else '无法打开视频，请确认文件可正常播放，或重新选择。')
                    continue
                if self.preview_pending:self.send_preview_request()
                # While dragging show the newest completed frame even if a
                # newer request is queued. After release only the exact target
                # may replace the paused image.
                if data.get('request_id')!=self.preview_number and not self.slider.isSliderDown():continue
                try:
                    if data.get('error'):
                        failure('找不到原视频，请重新定位。' if data.get('code')=='source_missing' else '无法读取此视频，请确认文件可正常播放，或重新选择视频。')
                        continue
                    pix=QPixmap()
                    if not pix.loadFromData(base64.b64decode(data['image'])):raise ValueError('画面数据无效')
                    first=self.meta is None
                    self.meta=data['meta'];self.canvas.pixmap=pix;self.display_seconds=data.get('frame_seconds',data['seconds'])
                    if first:
                        self.slider.blockSignals(True);self.slider.setRange(0,max(1,round(self.meta['duration']*1000)));self.slider.blockSignals(False)
                        self.set_position(self.display_seconds)
                    if data.get('roi'):self.canvas.roi=tuple(data['roi'])
                    if data.get('calibration'):self.calibration=data['calibration'];self.canvas.candidates=self.calibration.get('candidates',[])
                    self.canvas.source_size=(self.meta['width'],self.meta['height']);self.canvas.update();self.sync_roi(self.canvas.roi)
                    if data.get('read_roi')==list(self.canvas.roi):
                        self.reading.setText(('当前帧原始识别：'+data['text']) if data.get('text') else '当前画面未读到文字；可切换时间查看。')
                        self.reading.show()
                    if self.canvas.candidates:self.reading.setToolTip('右侧绿色刻度为取样 OCR 找到的候选带；点击框外对应高度可吸附。候选带不保证都是对白。')
                    # The label follows the pointer. An older decoded frame must
                    # not pull it backwards while another request is pending.
                    self.time_label.setText(f'{self.selected_seconds():.2f} / {self.meta["duration"]:.2f} 秒')
                    self.set_info(('自动定位未成功，请手动框选。'+data['roi_error']) if data.get('roi_error') else ('已定位字幕区域，请确认后应用。' if data.get('roi') else ''))
                    for w in (self.apply,self.previous,self.next,self.slider,self.read_button,self.play_button):w.setEnabled(True)
                    for w in (self.redraw,self.reset,self.locate,self.precision):w.setEnabled(True)
                except Exception:failure('画面读取失败，请重新读取；如仍失败，请确认视频文件可正常播放。')
        def finished(code,status):
            timer.stop()
            if self.process is p and not self.closed:
                if not self.failure_reason:failure('视频预览意外结束，请重新读取；如仍失败，请检查视频文件。')
                self.process=None;self.preview_busy=False;self.preview_pending=None
            p.deleteLater()
        def error(e):
            if e==QProcess.ProcessError.FailedToStart:
                failure('预览程序无法启动，请重新安装完整应用。');self.process=None;self.preview_busy=False;self.preview_pending=None;timer.stop();p.deleteLater()
        def timeout():
            failure('读取超时，请重新读取或取消后重试。');self.process=None;self.preview_busy=False;self.preview_pending=None;p.kill()
        p.started.connect(self.send_preview_request);p.readyReadStandardOutput.connect(ready)
        p.finished.connect(finished);p.errorOccurred.connect(error);timer.timeout.connect(timeout);p.start(executable,args)
    def send_preview_request(self):
        if self.closed or self.preview_busy or not self.preview_pending:return
        p=self.process
        if not p or p.state()!=QProcess.ProcessState.Running:return
        request=self.preview_pending;self.preview_pending=None;self.preview_busy=True
        p.write((json.dumps(request,ensure_ascii=False)+'\n').encode('utf-8'))
        p.preview_timer.start(120000 if request.get('detect_roi') or request.get('read_roi') else 20000)
    def done(self,result):
        self.closed=True;self.debounce.stop();self.cancel_process();super().done(result)
