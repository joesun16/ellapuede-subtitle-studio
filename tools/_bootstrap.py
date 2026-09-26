"""Shared path anchors for the build scripts in this directory.

ROOT is the project root (holds assets/, models/, packaging/, EllaPuede.spec).
SRC holds the runtime Python sources and is put on sys.path so build scripts can
import project modules such as `version` the same way the app does.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'src'
TOOLS = ROOT / 'tools'

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
