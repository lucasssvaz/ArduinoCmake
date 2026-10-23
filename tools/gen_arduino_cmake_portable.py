#!/usr/bin/env python3
"""Regenerate ``arduino_cmake.py`` in the repo root (zip of ``src/acmake`` + bootstrap)."""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "acmake"
OUT = ROOT / "arduino_cmake.py"


def _build_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PKG.rglob("*.py")):
            arc = Path("acmake") / path.relative_to(PKG)
            info = zipfile.ZipInfo(arc.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def _chunks_b64(data: bytes, width: int = 76) -> list[str]:
    b64 = base64.standard_b64encode(data).decode("ascii")
    return [b64[i : i + width] for i in range(0, len(b64), width)]


def _render_portable(raw: bytes) -> str:
    lines = _chunks_b64(raw)
    chunks_literal = "\n".join(f'    "{ln}",' for ln in lines)

    body = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable single-file Arduino CMake builder (bundled acmake package).
Generated from https://github.com/me-no-dev/ArduinoCmake

Copy ``arduino_cmake.py`` anywhere and run:
  python3 arduino_cmake.py compile --fqbn ... --sketch ...
  chmod +x arduino_cmake.py && ./arduino_cmake.py board

The embedded bundle is extracted once under ``~/.cache/arduino_cmake_portable/<id>/``.
Regenerate this file from the ArduinoCmake repository with:
  python3 tools/gen_arduino_cmake_portable.py
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# codespell:ignore-begin
_BUNDLE_CHUNKS = (
{chunks_literal}
)
# codespell:ignore-end


def _bundle_bytes() -> bytes:
    return base64.standard_b64decode("".join(_BUNDLE_CHUNKS))


def _extract_bundle(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(_bundle_bytes()), "r") as zf:
        zf.extractall(dest)
    (dest / ".ok").write_text("1", encoding="ascii")


def _bundle_root() -> Path:
    digest = hashlib.sha256(_bundle_bytes()).hexdigest()[:20]
    parent = Path.home() / ".cache" / "arduino_cmake_portable"
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / digest
    marker = root / ".ok"
    init = root / "acmake" / "__init__.py"
    if marker.is_file() and init.is_file():
        return root

    tmp = Path(tempfile.mkdtemp(prefix="." + digest + ".tmp-", dir=parent))
    try:
        _extract_bundle(tmp)
        try:
            os.rename(tmp, root)
            tmp = None
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            tmp = None
            if marker.is_file() and init.is_file():
                return root
            stale = parent / ("." + digest + ".stale-" + str(os.getpid()))
            try:
                os.rename(root, stale)
            except OSError:
                if marker.is_file() and init.is_file():
                    return root
                raise RuntimeError(
                    "portable acmake cache exists but is incomplete: " + str(root)
                ) from None
            shutil.rmtree(stale, ignore_errors=True)
            tmp = Path(tempfile.mkdtemp(prefix="." + digest + ".tmp-", dir=parent))
            _extract_bundle(tmp)
            os.rename(tmp, root)
            tmp = None
    except Exception:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    if not (marker.is_file() and init.is_file()):
        raise RuntimeError("failed to extract portable acmake into " + str(root))
    return root


def _run() -> int:
    root = _bundle_root()
    sroot = str(root)
    if sroot not in sys.path:
        sys.path.insert(0, sroot)
    from acmake.cli import main

    return int(main())


if __name__ == "__main__":
    raise SystemExit(_run())
'''
    return body


def _generated_bytes() -> bytes:
    return _render_portable(_build_zip_bytes()).encode("utf-8")


def main() -> None:
    raw = _build_zip_bytes()
    blob = _render_portable(raw).encode("utf-8")
    OUT.write_bytes(blob)
    OUT.chmod(OUT.stat().st_mode | 0o111)
    lines = _chunks_b64(raw)
    print(f"Wrote {OUT} ({len(raw)} bytes zip, {len(lines)} base64 lines)")


if __name__ == "__main__":
    main()
