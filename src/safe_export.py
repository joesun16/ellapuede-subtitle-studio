"""Prepare a full export before replacing files; rollback ordinary I/O failures.

Power loss cannot make two filesystem renames atomic. Kept history allows recovery.
"""
from pathlib import Path
import os
import shutil
import tempfile
import uuid
from datetime import datetime,timezone

def write_pair(files,backup=False):
    staged={};originals={};replaced=[];history=None
    try:
        # All potentially expensive writes happen before touching any destination.
        for path,text in files.items():
            path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.ellapuede-',suffix='.tmp',dir=path.parent)
            staged[path]=Path(name)
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                f.write(text);f.flush();os.fsync(f.fileno())
        history=None
        for path in staged:
            if path.exists():
                if backup:
                    if history is None:
                        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
                        history=path.parent/'.ellapuede-history'/stamp;history.mkdir(parents=True)
                    saved=history/path.name
                else:
                    fd,name=tempfile.mkstemp(prefix='.ellapuede-old-',dir=path.parent);os.close(fd);saved=Path(name)
                originals[path]=saved
                shutil.copy2(path,saved)
        for path,tmp in staged.items():
            os.replace(tmp,path);replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            if path in originals:os.replace(originals[path],path)
            else:path.unlink(missing_ok=True)
        if not replaced and history:shutil.rmtree(history,ignore_errors=True)
        raise
    finally:
        for tmp in staged.values():tmp.unlink(missing_ok=True)
        if not backup:
            for old in originals.values():old.unlink(missing_ok=True)
