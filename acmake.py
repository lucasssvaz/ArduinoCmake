#!/usr/bin/env python3
"""
Run acmake from the repository root without pip install or venv activation.

Usage:
  python3 acmake.py compile --fqbn arduino:avr:uno --sketch /path/to/Blink
  ./acmake.py board   # if executable (chmod +x acmake.py)

Note: This file is named acmake.py, so Python would normally put its directory
first on sys.path and resolve `import acmake` to this script. We drop that entry
and prepend src/ so the real package loads.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_SRC = _THIS_DIR / "src"

if sys.path:
    try:
        head = Path(sys.path[0]).resolve() if sys.path[0] else Path.cwd().resolve()
    except OSError:
        head = None
    if head == _THIS_DIR:
        sys.path.pop(0)

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from acmake.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
