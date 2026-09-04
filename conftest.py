"""Root conftest.py — adds project root to sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
for _path in (_SRC, _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
