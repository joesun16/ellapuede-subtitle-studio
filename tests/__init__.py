"""Regression suite. Run from the project root:

    python -m unittest discover -s tests -t . -p "test_*.py"

Runtime modules live in src/ (put on sys.path exactly like launch.py does) and a
few build/benchmark helpers under tests live in tools/.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _dir in (_ROOT / 'src', _ROOT / 'tools'):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
