"""Parse Arduino platform.txt / boards.txt key=value files."""

from __future__ import annotations

import re
from pathlib import Path


def load_properties_file(path: Path) -> dict[str, str]:
    """Load a .properties style file (platform.txt, boards.txt, library.properties).

    - Strips BOM
    - Supports line continuation with trailing backslash
    - Skips comments (# or ;) and empty lines
    """
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    lines: list[str] = []
    buf = ""
    for line in raw.splitlines():
        if buf:
            buf = buf[:-1] + line  # remove trailing \ from previous
        else:
            buf = line
        if buf.rstrip().endswith("\\"):
            continue
        lines.append(buf)
        buf = ""
    if buf:
        lines.append(buf)

    out: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        val = v.strip()
        if key:
            out[key] = val
    return out


def merge_local(base: dict[str, str], local_path: Path) -> dict[str, str]:
    merged = dict(base)
    merged.update(load_properties_file(local_path))
    return merged


def semver_key(s: str) -> tuple:
    """Sort key for version folder names (best-effort semver)."""
    parts = re.findall(r"\d+|\D+", s)
    nums: list[int | str] = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            nums.append(p)
    return tuple(nums)
