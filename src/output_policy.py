"""Source-aligned subtitle names and deterministic batch collision isolation."""
from collections import Counter
from pathlib import Path, PureWindowsPath
import hashlib
import unicodedata

def video_stem(source):
    # Projects can move between Windows and macOS.
    name=PureWindowsPath(str(source)).name if '\\' in str(source) else Path(source).name
    return Path(name).stem

def aligned_stem(directory,source):
    name=video_stem(source)
    if name in ('','.','..'):raise ValueError('项目缺少有效的视频文件名')
    return Path(directory)/name

def output_stems(entries,root):
    """entries: (source, relative_video_path). Keep basename even for collisions."""
    entries=list(entries)
    paths=[Path(rel) for _,rel in entries]
    if any(p.is_absolute() or '..' in p.parts for p in paths):
        raise ValueError('输出相对路径必须位于输出目录内')
    def key(p):return unicodedata.normalize('NFC',str(p.with_suffix(''))).casefold()
    counts=Counter(key(p) for p in paths)
    results=[]
    for (source,_),p in zip(entries,paths):
        target=Path(root)/p.with_suffix('')
        if counts[key(p)]>1:
            digest=hashlib.sha256(str(source).encode('utf-8')).hexdigest()[:12]
            target=target.parent/'_同名视频'/digest/target.name
        results.append(target)
    return results
