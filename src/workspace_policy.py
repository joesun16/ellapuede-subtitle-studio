"""Explicit task settings and reversible queue operations, independent of Qt."""
from copy import deepcopy
from pathlib import Path
from series_policy import series_key

SETTING_KEYS=('language','engine','format','output')
def settings_for(job,defaults):
    return {k:job.get('settings',{}).get(k,defaults[k]) for k in SETTING_KEYS}

def apply_settings(jobs,changes,scope):
    changed=[]
    for job in jobs:
        if scope is None or series_key(job)!=scope:continue
        current=job.setdefault('settings',{})
        delta={k:v for k,v in changes.items() if current.get(k)!=v}
        if not delta:continue
        current.update(delta);changed.append(job)
        needs_ocr=bool({'language','engine'} & delta.keys())
        if needs_ocr:
            for key in ('resolved_languages','detected_language','language_phase'):job.pop(key,None)
            # A format-only edit may already have queued a cheap re-export.
            # A later language/engine edit must always invalidate that shortcut.
            job.pop('export_only',None)
            job['replace_output']=True
            job['pending_reason']='语言或引擎已更改 · 待重新识别'
            if job['status']=='pending':
                job['processed_seconds']=0;job.pop('work_fraction',None)
        if job['status']=='done':
            job['status']='pending';job['processed_seconds']=0;job.pop('work_fraction',None)
            job.pop('settings_changed',None)
            if not needs_ocr:
                if not job.get('replace_output'):
                    job['export_only']=True;job['pending_reason']='导出设置已更改 · 待重新导出'
        elif job['status'] in ('failed','interrupted'):
            job['status']='pending';job.pop('error',None)
    return changed

def removal_snapshot(jobs,ids,active=None):
    return [(i,deepcopy(j)) for i,j in enumerate(jobs) if j['id'] in ids and j is not active]

def restore_removed(jobs,snapshot):
    known={j['source'] for j in jobs}
    for pos,job in snapshot:
        if job['source'] not in known:
            jobs.insert(min(pos,len(jobs)),job);known.add(job['source'])

def import_entries(paths):
    import subtitle_ocr as core
    entries=[]
    for value in paths:
        root=Path(value).resolve()
        if root.is_dir():
            for source in sorted(root.rglob('*'),key=core.natural_key):
                if not source.is_file() or source.suffix.lower() not in core.VIDEO_EXTS:continue
                rel=source.relative_to(root)
                # A collection containing several drama subfolders stays separated.
                series=root/rel.parts[0] if len(rel.parts)>1 else root
                entries.append((str(source),str(Path(root.name)/rel),str(series)))
        elif root.is_file() and root.suffix.lower() in core.VIDEO_EXTS:
            entries.append((str(root),root.name,str(root.parent)))
    result=[]
    import av
    for source,relative,series in entries:
        duration=0
        try:
            with av.open(source) as c:
                stream=c.streams.video[0]
                duration=float(c.duration/av.time_base) if c.duration else float((stream.duration or 0)*stream.time_base)
        except Exception:pass
        result.append((source,relative,series,duration))
    return result
