"""Reconnect a moved episode and matching siblings without guessing filenames."""
from pathlib import Path
from series_policy import series_key

def relink_series(jobs,reference,replacement):
    replacement=Path(replacement).resolve()
    if not replacement.is_file():raise FileNotFoundError(replacement)
    old_parent=Path(reference['source']).parent
    group=series_key(reference)
    occupied={j['source'] for j in jobs if series_key(j)!=group}
    updates=[]
    for job in jobs:
        if series_key(job)!=group:continue
        old=Path(job['source'])
        candidate=replacement if job is reference else replacement.parent/old.name if old.parent==old_parent else None
        if candidate is None or not candidate.is_file():continue
        candidate=str(candidate.resolve())
        if candidate in occupied or any(path==candidate for _,path in updates):continue
        updates.append((job,candidate))
    if not any(job is reference for job,_ in updates):raise ValueError('所选视频已在其他任务中，或无法连接。')
    for job,path in updates:
        job['source']=path
        job['relative']=str(Path(job['relative']).with_name(Path(path).name))
        job['source_missing']=False
        for key in ('resolved_languages','detected_language','language_phase','planned_stem'):
            job.pop(key,None)
        if job['status'] in {'failed','interrupted'}:
            job['status']='pending';job.pop('error',None)
    return len(updates)
