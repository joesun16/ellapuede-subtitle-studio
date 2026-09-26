"""User-facing measured timings; cached exports never masquerade as OCR speed."""
from pathlib import Path

def describe(jobs):
    lines=[]
    for job in jobs[:12]:
        title=Path(job['source']).name
        if job.get('cached_result'):
            lines.append(f'{title}\n本次使用已完成结果直接导出，没有重新识别。');continue
        perf=job.get('performance',{});elapsed=job.get('elapsed_seconds') or perf.get('pipeline_seconds')
        if job.get('status')!='done' or not elapsed:
            lines.append(f'{title}\n尚无完整处理记录；完成后可查看实际耗时。');continue
        duration=job.get('duration',0)
        text=f'{title}\n视频 {duration/60:.1f} 分钟 · 实际用时 {elapsed:.1f} 秒'
        if duration:text+=f' · 约 {duration/elapsed:.1f} 倍实时速度'
        if perf:
            verification=sum(perf.get(name,0) for name in ('line_check_seconds','quality_check_seconds','visual_consensus_seconds'))
            text+=f"\n扫描 {perf.get('seconds',0):.1f} 秒 · 图像复查 {verification:.1f} 秒"
            text+=f"\n主识别调用 {perf.get('new_ocr_frames',0)} 次 · 断点恢复 {perf.get('cache_frames',0)} 帧"
        if job.get('backend'):text+='\n实际后端：'+job['backend']
        if job.get('events') is not None:text+=f"\n已自动导出 {job['events']} 条。"
        if job.get('warnings'):text+='\n注意：'+'；'.join(job['warnings'])
        lines.append(text)
    if len(jobs)>12:lines.append(f'另有 {len(jobs)-12} 项，请缩小选择范围查看。')
    return '\n\n'.join(lines) or '请选择视频。'
