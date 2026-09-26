"""Remove only known control signals after a worker has stopped using them."""
from pathlib import Path


def clean_finished_controls(root, finished_ids, protected_ids=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        return 0
    finished = set(finished_ids)
    protected = set(protected_ids)
    removed = 0
    for directory in root.iterdir():
        if directory.name in protected or directory.is_symlink() or not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
            # Unknown directories can only be removed if already empty. Never
            # recurse or remove unknown files, cache DBs, or live task signals.
            if entries and directory.name not in finished:
                continue
            if any(p.is_symlink() or not p.is_file() or p.name not in {'pause', 'stop'} for p in entries):
                continue
            for path in entries:
                path.unlink()
            directory.rmdir()
            removed += 1
        except OSError:
            continue
    return removed
