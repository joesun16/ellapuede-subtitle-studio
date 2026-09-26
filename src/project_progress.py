"""Project progress is duration-weighted and reaches 100% only after export."""
def progress(jobs):
    if not jobs:return 0
    durations=[j.get('duration',0) for j in jobs if j.get('duration',0)>0]
    fallback=sum(durations)/len(durations) if durations else 1
    total=done=0
    for j in jobs:
        duration=j.get('duration') or fallback;total+=duration
        fraction=(1 if j['status']=='done' else
                  min(.99,max(0,j.get('work_fraction',j.get('processed_seconds',0)/duration))))
        done+=duration*fraction
    return min(1000 if all(j['status']=='done' for j in jobs) else 999,round(1000*done/total))
