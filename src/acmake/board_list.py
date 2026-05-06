"""Enumerate installed boards (FQBN-style strings)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from acmake.config import ArduinoPaths
from acmake.parse_txt import load_properties_file


def _board_ids_from_keys(raw: dict[str, str]) -> set[str]:
    """Board IDs are prefixes of keys that define a `.name` property."""
    ids: set[str] = set()
    for k in raw:
        if k.endswith(".name") and ".menu." not in k:
            ids.add(k[: -len(".name")])
    return ids


def _boards_from_packages(packages_dir: Path) -> list[str]:
    out: list[str] = []
    if not packages_dir.is_dir():
        return out
    for vendor_dir in sorted(packages_dir.iterdir()):
        if not vendor_dir.is_dir():
            continue
        hw = vendor_dir / "hardware"
        if not hw.is_dir():
            continue
        for arch_dir in sorted(hw.iterdir()):
            if not arch_dir.is_dir():
                continue
            for ver_dir in sorted(arch_dir.iterdir()):
                if not ver_dir.is_dir():
                    continue
                if not (ver_dir / "platform.txt").is_file():
                    continue
                boards = ver_dir / "boards.txt"
                if not boards.is_file():
                    continue
                raw = load_properties_file(boards)
                for bid in sorted(_board_ids_from_keys(raw)):
                    out.append(f"{vendor_dir.name}:{arch_dir.name}:{bid}")
    return out


def _boards_from_hardware_root(hw_root: Path) -> list[str]:
    """boards under ``.../hardware/<vendor>/<arch>/<version>/`` (sketchbook or sketch)."""
    out: list[str] = []
    if not hw_root.is_dir():
        return out
    for vendor_dir in sorted(hw_root.iterdir()):
        if not vendor_dir.is_dir():
            continue
        for arch_dir in sorted(vendor_dir.iterdir()):
            if not arch_dir.is_dir():
                continue
            for ver_dir in sorted(arch_dir.iterdir()):
                if not ver_dir.is_dir():
                    continue
                if not (ver_dir / "platform.txt").is_file():
                    continue
                boards = ver_dir / "boards.txt"
                if not boards.is_file():
                    continue
                raw = load_properties_file(boards)
                for bid in sorted(_board_ids_from_keys(raw)):
                    out.append(f"{vendor_dir.name}:{arch_dir.name}:{bid}")
    return out


def list_installed_boards(
    paths: ArduinoPaths,
    sketch_dirs: Sequence[Path] | None = None,
) -> list[str]:
    """Return FQBN strings for boards in sketch hardware, user hardware, then packages.

    Order: each ``--sketch`` …/hardware, then sketchbook ``user/hardware``, then packages.
    Duplicates (same FQBN string) are listed once; first occurrence wins.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def add_many(rows: list[str]) -> None:
        for row in rows:
            if row not in seen:
                seen.add(row)
                ordered.append(row)

    if sketch_dirs:
        for sk in sketch_dirs:
            sk = sk.expanduser().resolve()
            add_many(_boards_from_hardware_root(sk / "hardware"))

    add_many(_boards_from_hardware_root(paths.user_dir / "hardware"))
    add_many(_boards_from_packages(paths.packages_dir))
    return ordered
