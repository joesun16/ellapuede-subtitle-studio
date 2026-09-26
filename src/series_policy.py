"""One normalized dialogue rectangle per imported series root."""
from pathlib import Path

def series_key(job):
    return job.get('series') or str(Path(job['source']).resolve().parent)

def series_jobs(jobs,selected):
    keys={series_key(j) for j in selected}
    return [j for j in jobs if series_key(j) in keys]

def effective_roi(job,regions):
    if job.get('roi_override'):return job['roi_override']
    record=regions.get(series_key(job))
    return (record or {}).get('roi') or job.get('roi')

def recognition_options(profile):
    # Performance presets must never select different OCR/content algorithms.
    return {'strategy':'accurate','scale':0}
