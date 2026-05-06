"""Simple verbosity-controlled logging."""

from __future__ import annotations

import logging
import sys


def setup_logging(verbose: int = 0) -> logging.Logger:
    level = logging.DEBUG if verbose >= 2 else (logging.INFO if verbose >= 1 else logging.WARNING)
    log = logging.getLogger("acmake")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    h = logging.StreamHandler(sys.stderr)
    h.setLevel(level)
    h.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    log.addHandler(h)
    return log
