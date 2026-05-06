"""Enumerate core, variant, library, and sketch source files."""

from __future__ import annotations

from pathlib import Path

_SOURCE_EXT = {".c", ".cc", ".cpp", ".S", ".s"}


def _iter_sources_under(root: Path, *, recursive: bool) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    if recursive:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in _SOURCE_EXT:
                out.append(p)
    else:
        for p in root.iterdir():
            if p.is_file() and p.suffix in _SOURCE_EXT:
                out.append(p)
    out.sort()
    return out


def collect_core_sources(core_path: Path) -> list[Path]:
    """All .c/.cpp/.S under cores/<core> (recursive)."""
    return _iter_sources_under(core_path, recursive=True)


def collect_variant_sources(variant_path: Path) -> list[Path]:
    """Non-recursive sources in variant folder (typical AVR layout)."""
    return _iter_sources_under(variant_path, recursive=False)


def collect_library_sources(lib_root: Path) -> list[Path]:
    """Library 1.5 src/ tree or legacy flat layout."""
    src = lib_root / "src"
    if src.is_dir():
        return _iter_sources_under(src, recursive=True)
    return _iter_sources_under(lib_root, recursive=False)


def collect_sketch_extra_sources(sketch_dir: Path) -> list[Path]:
    """Sketch .c/.cpp/.S at sketch root (not .ino)."""
    return _iter_sources_under(sketch_dir, recursive=False)
