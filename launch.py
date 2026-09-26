"""Single entrypoint for source and packaged desktop/worker processes."""
import os
import sys
from pathlib import Path

# Running from source, every module lives in src/. PyInstaller flattens them into
# the bundle root instead, so this is a no-op there (the directory is absent).
_SRC = Path(__file__).resolve().parent / 'src'
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

def configure_stdio():
    # PyInstaller ignores PYTHONUTF8 for its isolated interpreter. Windows pipes
    # otherwise inherit a legacy code page, breaking Chinese progress and OCR IPC.
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='strict')

if __name__=='__main__':
    configure_stdio()
    if '--ocr-worker' in sys.argv:
        from portable_ocr_worker import main
        main(sys.argv[sys.argv.index('--ocr-worker')+1:])
    elif '--preview-worker' in sys.argv:
        from preview_worker import main
        raise SystemExit(main(sys.argv[sys.argv.index('--preview-worker')+1:]))
    elif '--batch-worker' in sys.argv:
        from batch_worker import main
        raise SystemExit(main())
    elif '--worker' in sys.argv:
        from subtitle_ocr import main
        raise SystemExit(main(sys.argv[sys.argv.index('--worker')+1:]))
    else:
        from ella_app import main
        raise SystemExit(main())
