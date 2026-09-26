"""Small native export/cache dialogs; recognition is never needed for re-export."""
import json,shutil,hashlib
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFileDialog,QMessageBox
from output_policy import output_stems
from ui_theme import polish_controls
from stable_combo import StableComboBox

def export_results(jobs,root,format):
    import subtitle_ocr as core
    planned=output_stems([(j['source'],j['relative']) for j in jobs],root);results=[]
    for job,stem in zip(jobs,planned):
        data=Path(job['result_stem']+'.subtitles.json')
        doc=json.loads(data.read_text(encoding='utf-8'))
        stem.parent.mkdir(parents=True,exist_ok=True)
        from resource_control import OutputLock
        lock=OutputLock(stem.parent)
        try:core.export_files(doc,stem,backup=True,format=format)
        finally:lock.close()
        results.append((job['id'],str(stem)))
    return results

def export_dialog(window):
    jobs=[dict(j) for j in window.selected_jobs() if j.get('result_stem') and Path(str(j['result_stem'])+'.subtitles.json').is_file()]
    if not jobs:return
    dialog=QDialog(window);dialog.setWindowTitle('导出已识别字幕');dialog.setMinimumWidth(500);layout=QVBoxLayout(dialog);layout.setContentsMargins(24,24,24,24);layout.setSpacing(12)
    layout.addWidget(QLabel(f'导出所选 {len(jobs)} 集；复用识别结果，无需重新 OCR。'))
    format=StableComboBox()
    for name,value in [('SRT','srt'),('ASS','ass'),('SRT + ASS','both')]:format.addItem(name,value)
    format.setCurrentIndex(max(0,format.findData(window.export_format.currentData())));layout.addWidget(format)
    target=QLabel(window.output.text());target.setWordWrap(True);layout.addWidget(target)
    choose=QPushButton('更换导出位置');layout.addWidget(choose)
    def select():
        path=QFileDialog.getExistingDirectory(dialog,'选择导出目录',target.text())
        if path:target.setText(path)
    choose.clicked.connect(select);layout.addWidget(QLabel('同名字幕替换前自动备份，视频文件保持原样。'))
    buttons=QHBoxLayout();cancel=QPushButton('取消');cancel.clicked.connect(dialog.reject);go=QPushButton('导出');go.setObjectName('primary');go.clicked.connect(dialog.accept);buttons.addWidget(cancel);buttons.addWidget(go);layout.addLayout(buttons);polish_controls(dialog)
    if dialog.exec()!=QDialog.DialogCode.Accepted:return
    root=Path(target.text());fmt=format.currentData();window.phase_label.setText('正在导出已识别字幕…');window.set_running_ui(True)
    window.pause_btn.setEnabled(False);window.stop_btn.setEnabled(False)
    def ready(results):
        for jid,stem in results:
            for job in window.jobs:
                if job['id']==jid:job['export_stem']=stem
        window.set_running_ui(False);window.save_state();window.phase_label.setText(f'已导出 {len(results)} 集字幕，无需重新识别。')
    thread=window.background_task(lambda:export_results(jobs,root,fmt),ready)
    thread.error.connect(lambda _:window.set_running_ui(False))

def cache_inventory(root,jobs,include_orphans=False):
    """Only disposable frame DBs for completed sources. Keep compact export records."""
    root=Path(root);size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) if root.exists() else 0
    completed={j['source'] for j in jobs if j['status']=='done'};pending={j['source'] for j in jobs if j['status']!='done'}
    # Content-equivalent sources may share a cache. Their fingerprints protect it.
    protected=set()
    for p in (root/'results').glob('*/*.subtitles.json'):
        try:
            d=json.loads(p.read_text(encoding='utf-8'))
            if d.get('source') in pending:protected.add(d.get('source_sha256'))
        except (OSError,ValueError):pass
    candidates=[]
    metadata=[]
    for meta in (root/'frames').glob('*/job.json'):
        try:
            d=json.loads(meta.read_text(encoding='utf-8'))
            metadata.append((meta,d))
            if d.get('source') in pending:protected.add(d.get('sha256'))
        except (OSError,ValueError):pass
    for meta,d in metadata:
        eligible=d.get('source') in completed-pending or (include_orphans and d.get('source') not in completed|pending)
        if eligible and d.get('sha256') not in protected and not meta.parent.is_symlink():candidates.append(meta.parent)
    return size,candidates

def clear_completed_cache(root,jobs,include_orphans=False):
    _,dirs=cache_inventory(root,jobs,include_orphans);released=0
    for directory in dirs:
        released+=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file());shutil.rmtree(directory)
    return released

def migrate_cache(old,new):
    old=Path(old).resolve();new=Path(new).resolve()
    if old==new:return
    if new in old.parents or old in new.parents:raise ValueError('新位置不能是当前缓存目录的父目录或子目录。')
    if new.exists() and any(new.iterdir()):raise ValueError('请选择空文件夹存放缓存。')
    new.mkdir(parents=True,exist_ok=True)
    if not old.exists():return
    for p in old.rglob('*'):
        dest=new/p.relative_to(old)
        if p.is_dir():dest.mkdir(exist_ok=True)
        else:
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
            with p.open('rb') as a,dest.open('rb') as b:
                if hashlib.file_digest(a,'sha256').digest()!=hashlib.file_digest(b,'sha256').digest():raise IOError('缓存迁移校验失败，原缓存保留。')
    # Original data is retained until user removes it; no irreversible migration.

def cache_dialog(window):
    d=QDialog(window);d.setWindowTitle('EllaPuede · 缓存管理');d.setMinimumWidth(520);v=QVBoxLayout(d);v.setContentsMargins(24,24,24,24);v.setSpacing(12)
    path=QLabel(str(window.cache_root));path.setWordWrap(True);v.addWidget(path);info=QLabel('正在统计缓存…');info.setWordWrap(True);v.addWidget(info)
    v.addWidget(QLabel('清理仅删除已完成任务的逐帧缓存，保留字幕、导出记录及未完成进度。'))
    clear=QPushButton('清理已完成任务缓存');orphans=QPushButton('清理已移除及已完成任务的帧缓存');move=QPushButton('更换缓存位置');close=QPushButton('关闭');close.clicked.connect(d.accept)
    orphans.setToolTip('不删除字幕或导出记录；重新添加已移除的视频时，需要重新识别已清理的帧。')
    for b in (clear,orphans,move,close):v.addWidget(b)
    clear.setEnabled(not window.running);move.setEnabled(not window.running)
    def busy(value):
        for button in (clear,orphans,move):button.setEnabled(not value and not window.running)
    def failed(_):busy(False);info.setText('操作未完成，原缓存保留。')
    def refresh():
        busy(True);info.setText('正在统计缓存…')
        jobs=[dict(j) for j in window.jobs];root=window.cache_root
        def done(result):
            size,dirs=result;info.setText(f'缓存占用 {size/1024**2:.1f} MB · 可清理 {len(dirs)} 组已完成帧缓存');busy(False)
        thread=window.background_task(lambda:cache_inventory(root,jobs),done);thread.error.connect(failed)
    def purge(include_orphans=False):
        if window.running:return
        busy(True);info.setText('正在清理帧缓存…');jobs=[dict(j) for j in window.jobs];root=window.cache_root
        def done(released):
            refresh();window.statusBar().showMessage(f'已释放 {released/1024**2:.1f} MB，字幕和未完成进度保留。')
        thread=window.background_task(lambda:clear_completed_cache(root,jobs,include_orphans),done);thread.error.connect(failed)
    def relocate():
        if window.running:return
        selected=QFileDialog.getExistingDirectory(d,'选择空的缓存文件夹')
        if not selected:return
        new=Path(selected);old=window.cache_root;busy(True);info.setText('正在复制并校验缓存，原位置保留…')
        def done(_):
            for j in window.jobs:
                if j.get('result_stem'):
                    try:j['result_stem']=str(new/Path(j['result_stem']).relative_to(old))
                    except ValueError:pass
            window.cache_root=new;window.save_state();path.setText(str(new));refresh()
        thread=window.background_task(lambda:migrate_cache(old,new),done);thread.error.connect(failed)
    clear.clicked.connect(lambda:purge(False));orphans.clicked.connect(lambda:purge(True));move.clicked.connect(relocate);refresh();polish_controls(d);d.exec()
