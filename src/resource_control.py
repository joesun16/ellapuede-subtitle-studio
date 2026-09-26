"""Cooperative controls and bounded resource policy shared by CLI and desktop."""
import json
import os
from pathlib import Path
import shutil
import time
import sys
import threading

_EVENT_LOCK=threading.Lock()

class Cancelled(Exception):
    pass

def emit(kind, **values):
    message='@@ELLAPUEDE@@'+json.dumps({'type':kind,**values},ensure_ascii=False)+'\n'
    with _EVENT_LOCK:
        sys.stdout.write(message);sys.stdout.flush()

class Controller:
    def __init__(self, control_dir=None, memory_gb=4, output=None,cache=None):
        self.directory=Path(control_dir) if control_dir else None
        self.memory_gb=memory_gb
        self.output=Path(output) if output else None
        self.cache=Path(cache) if cache else None
        self.last_check=0
        self.paused=False
        self.peak_mb=0
        self.started=time.monotonic()
        try:
            import psutil
            self.psutil=psutil
            self.process=psutil.Process()
            if os.name=='nt':self.process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:self.process.nice(5)
        except (ImportError, OSError):
            self.psutil=None

    def check(self):
        if self.directory:
            if (self.directory/'stop').exists():raise Cancelled('用户停止；进度缓存已保存')
            while (self.directory/'pause').exists():
                if not self.paused:emit('paused');self.paused=True
                if (self.directory/'stop').exists():raise Cancelled('用户停止；进度缓存已保存')
                time.sleep(.2)
            if self.paused:emit('resumed');self.paused=False
        now=time.monotonic()
        if now-self.last_check<2:return
        self.last_check=now
        emit('heartbeat',elapsed_seconds=round(now-self.started,1))
        if self.cache and shutil.disk_usage(self.cache).free<256*1024**2:
            raise RuntimeError('缓存磁盘空间不足，已停止并保留进度。请在缓存管理中更换位置后继续。')
        if self.output and shutil.disk_usage(self.output).free<256*1024**2:
            raise RuntimeError('输出磁盘剩余空间低于 256 MB，停止并保留进度。清理磁盘后重试。')
        if self.psutil:
            rss=0
            for p in [self.process]+self.process.children(recursive=True):
                try:rss+=p.memory_info().rss
                except self.psutil.Error:pass
            self.peak_mb=max(self.peak_mb,rss/1024**2)
            emit('resources',rss_mb=round(rss/1024**2),peak_mb=round(self.peak_mb))
            if rss>self.memory_gb*1024**3:
                raise RuntimeError(f'进程树内存超过设定的 {self.memory_gb:g} GB 软阈值。已停止并保留进度；请降低并发或提高阈值后重试。')
            if self.psutil.virtual_memory().available<256*1024**2:
                raise RuntimeError('系统可用内存低于 256 MB，已停止并保留进度。')

CONTROL=None

def check():
    if CONTROL:CONTROL.check()

class OutputLock:
    """Prevent two processes writing the same output/cache directory."""
    def __init__(self,directory):
        self.file=(Path(directory)/'.ellapuede.lock').open('a+b')
        if os.name=='nt':
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(Path(directory)/'.ellapuede.lock'),2)
        self.file.seek(0,2)
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('另一个任务正在写入该输出目录，请等待其完成或选择不同目录。')
    def close(self):self.file.close()
