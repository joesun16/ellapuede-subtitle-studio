"""Serial, cancellable import-time language probes outside the GUI process."""
import json,os,sys,hashlib
from pathlib import Path
from PySide6.QtCore import QObject,QProcess,QTimer
from series_policy import series_key,effective_roi
from workspace_policy import settings_for

class LanguagePreview(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.process=None;self.attempted=set()
    def signature(self,job):
        w=self.window;s=settings_for(job,w.defaults)
        return (series_key(job),s['language'],s['engine'],tuple(effective_roi(job,w.series_regions) or ()),job['source'])
    def cancel(self):
        p=self.process;self.process=None
        if p and p.state()!=QProcess.ProcessState.NotRunning:
            self.attempted={sig for sig in self.attempted if sig[0]!=p.group}
            for job in self.window.jobs:
                if series_key(job)==p.group:job.pop('language_phase',None)
            p.kill();self.window.queue_model.notify()
    def start(self):
        w=self.window
        if self.process or w.running or w.close_requested:return
        job=next((j for j in w.jobs if settings_for(j,w.defaults)['language']=='auto'
                  and not j.get('resolved_languages') and self.signature(j) not in self.attempted
                  and Path(j['source']).is_file()),None)
        if job is None:return
        sig=self.signature(job);self.attempted.add(sig);group=sig[0]
        # One attempt represents the whole series, not one attempt per episode.
        for j in w.jobs:
            if series_key(j)==group:self.attempted.add(self.signature(j));j['language_phase']='正在判断语言'
        w.queue_model.notify();w.update_language_presentation()
        executable=sys.executable;args=[str(Path(__file__).resolve().parent.parent/'launch.py')]
        if getattr(sys,'frozen',False):
            executable=str(Path(sys.executable).with_name('EllaPuedeWorker.exe' if os.name=='nt' else 'EllaPuedeWorker'));args=[]
        cache=w.state_dir/'series'/(hashlib.sha256(group.encode()).hexdigest()+'.json')
        args+=['--preview-worker',job['source'],'--detect-language','--engine',sig[2],'--series-file',str(cache)]
        if sig[3]:args+=['--read-roi',','.join(map(str,sig[3]))]
        p=QProcess(self);p.group=group;self.process=p;timer=QTimer(p);timer.setSingleShot(True);timer.setInterval(180000)
        def finished(code,*unused):
            timer.stop()
            if self.process is p:
                self.process=None
                try:
                    if code:raise ValueError('取样未完成，请手动选择语言或开始后重新判断。')
                    data=json.loads(bytes(p.readAllStandardOutput()).decode('utf-8'));resolved=data.get('resolved_languages',[])
                    message=data.get('roi_error') or ('已判断语言' if resolved else '请选择原语言')
                except (ValueError,UnicodeError):resolved=[];message='暂未判断语言，可手动选择或开始后重试。'
                for j in w.jobs:
                    current=self.signature(j)
                    if current[:4]==sig[:4]:
                        j['language_phase']=message
                        if resolved:j['resolved_languages']=resolved;j['detected_language']=resolved[0]
                w.queue_model.notify();w.update_language_presentation();w.save_state()
                QTimer.singleShot(0,self.start)
            p.deleteLater()
        p.finished.connect(finished)
        p.errorOccurred.connect(lambda error:finished(1) if error==QProcess.ProcessError.FailedToStart else None)
        timer.timeout.connect(p.kill);p.start(executable,args);timer.start()
