"""Conservative CPU policy. GPU availability is never inferred from a device name."""
import os
import platform

LANGUAGES=[('自动识别','auto'),('英语','en-US'),('简体中文','zh-Hans'),('繁體中文','zh-Hant'),
           ('中英双语','zh-Hans,en-US'),('日本語','ja-JP'),('韩语','ko-KR'),('西班牙语','es-ES'),
           ('法语','fr-FR'),('德语','de-DE'),('葡萄牙语','pt-BR'),('意大利语','it-IT'),('泰语','th-TH')]
SUPPORTED={code for _,codes in LANGUAGES for code in codes.split(',')}

LANGUAGE_NAMES = {code: name for name, code in LANGUAGES}

def language_name(code):
    """Return the user-facing name for one resolved language code."""
    if not code:
        return '未判断'
    if ',' in code:
        return '、'.join(language_name(part) for part in code.split(','))
    return LANGUAGE_NAMES.get(code, code)

def resolve_engine(engine,languages,system=None,macos_major=None):
    if engine!='auto':return engine
    languages=languages.split(',') if isinstance(languages,str) else languages
    # Use the same script choice regardless of CPU/GPU selection. macOS Vision
    # supports Thai and is materially faster and cleaner on the current real
    # caption sample; Windows keeps its bundled offline Thai PP-OCR route.
    # Queryable Vision language support varies by OS revision. macOS 15 is
    # verified locally for Thai; earlier releases keep the bundled PP-OCR path.
    current=(system or platform.system()).lower()
    if current=='darwin' and 'th-TH' in languages:
        major=macos_major if macos_major is not None else int((platform.mac_ver()[0] or '0').split('.')[0])
        if major<15:return 'rapid'
    # macOS can combine native recognition with an offline Korean fallback.
    return 'vision' if current=='darwin' else 'rapid'

def validate_languages(languages):
    unknown=set(languages)-SUPPORTED
    if not languages or unknown:
        raise ValueError('此版本尚未开放这些识别语言：'+(', '.join(sorted(unknown)) or '空值'))

def snapshot():
    import psutil
    mem=psutil.virtual_memory()
    return {'os':platform.system(),'os_version':platform.release(),'architecture':platform.machine(),
            'logical_cpus':os.cpu_count() or 1,'physical_cpus':psutil.cpu_count(logical=False) or os.cpu_count() or 1,
            'total_gb':mem.total/1024**3,
            'available_gb':mem.available/1024**3}

def plan(engine,profile,memory_gb,hardware=None,device='auto'):
    h=hardware or snapshot()
    # Keep headroom for the GUI, decoder, buffers and other applications.
    budget=max(.1,min(float(memory_gb),h['available_gb']*.65))
    # Logical cores often share execution units; limit concurrent decoders by
    # physical cores when available, while keeping old saved snapshots valid.
    cpus=max(1,h.get('physical_cpus') or h['logical_cpus']);profile=max(0,min(2,profile))
    cpu_budget=max(1,min(cpus-1,int(cpus*(.25,.5,.75)[profile])))
    # The three presets allocate resources, never a different OCR pipeline.
    # A fixed three-process ceiling left modern Windows CPUs underused, while
    # small machines still need a strict CPU and memory cap.
    desired=([2,3,6] if engine=='vision' else
             [min(2,max(1,cpus//4)),min(4,max(2,cpus//3)),min(6,max(3,cpus//2))])[profile]
    gpu_capped=engine!='vision' and device=='gpu' and desired>2
    if gpu_capped:desired=2  # Bound duplicate model sessions on unknown VRAM.
    per_worker=.35 if engine=='vision' else 1.1
    workers=max(1,min(desired,cpu_budget,int(max(0,budget-.45)/per_worker)))
    threads=1 if profile==0 else min(2,max(1,cpu_budget//workers))
    limited_by='可用内存' if workers < min(desired,cpu_budget) else '处理器' if workers < desired else '显卡会话保护' if gpu_capped else '模式上限'
    backend=('Apple Vision（由系统调度）' if engine=='vision' else
             'ONNX Runtime CPU' if device=='cpu' else
             'ONNX Runtime DirectML（不可用时回退 CPU）' if device=='gpu' else
             'ONNX Runtime（单路测试 DirectML，其余 CPU）')
    return {'workers':workers,'threads':threads,'available_gb':round(h['available_gb'],1),'limited_by':limited_by,
            'backend':backend,
            'note':'基于可用内存与物理核心数的保守估算；运行时仍监测内存，非性能承诺。'}

def default_memory_limit(hardware=None):
    """Allow capable machines to use their RAM without requiring expert setup."""
    h=hardware or snapshot()
    return max(4,min(12,round(h['total_gb']*.5)))

def description(h=None):
    h=h or snapshot()
    return (f"{h['os']} {h['os_version']} · {h['architecture']}\n"
            f"物理核心 {h.get('physical_cpus',h['logical_cpus'])} · 逻辑核心 {h['logical_cpus']} · 总内存 {h['total_gb']:.1f} GB · 当前可用 {h['available_gb']:.1f} GB\n\n"
            '当前离线跨平台后端：ONNX Runtime。\n'
            'Mac 可选 Apple Vision，计算设备由系统调度。\n'
            'Windows 包含 DirectML；自动模式只用一路真实字幕画面测试 GPU，其余路保持 CPU；失败回退 CPU。未启用 CUDA / WinML。\n\n'
            '每次启动一集时重新评估 CPU 并发；整季顺序处理，帧识别有限并行。\n'
            '内存阈值为软限制，超限会停止并保存已提交的缓存。\n'
            '本次安装包提供 Windows x64 / Mac Apple Silicon；其他架构尚未验收。')
