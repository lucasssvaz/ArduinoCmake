"""Locate installed platform packages and toolchains."""

from __future__ import annotations

import re
from pathlib import Path

from acmake.parse_txt import semver_key


def find_latest_platform_version_dir(hw_parent: Path) -> Path | None:
    """Pick the newest *installed core* under ``hw_parent``, not arbitrary siblings.

    Arduino hardware trees often place ``libraries/``, ``tools/``, etc. next to
    semver version folders (e.g. ``3.0.7``). Sorting all directory names would
    incorrectly pick ``libraries`` over ``3.0.7``. Only directories that contain
    ``platform.txt`` are considered valid platform roots.
    """
    if not hw_parent.is_dir():
        return None
    if (hw_parent / "platform.txt").is_file():
        return hw_parent.resolve()
    candidates: list[Path] = []
    for p in hw_parent.iterdir():
        if p.is_dir() and (p / "platform.txt").is_file():
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda p: semver_key(p.name), reverse=True)
    return candidates[0].resolve()


def resolve_platform_root(
    packages_dir: Path,
    vendor: str,
    arch: str,
    *,
    sketch_dir: Path | None = None,
    user_dir: Path | None = None,
) -> Path:
    """Resolve platform folder (version dir) for FQBN vendor:arch.

    Search order (Arduino-style local overrides):

    1. ``<sketch>/hardware/<vendor>/<arch>/<version>`` — portable / per-sketch cores
    2. ``<sketchbook>/hardware/<vendor>/<arch>/<version>`` — user-installed hardware
    3. ``<packages>/<vendor>/hardware/<arch>/<version>`` — Board Manager packages
    """
    tried: list[str] = []

    def try_base(hw_parent: Path, label: str) -> Path | None:
        """hw_parent is the directory that contains ``vendor/arch`` version children."""
        if not hw_parent.is_dir():
            return None
        tried.append(f"{label}:{hw_parent}")
        ver = find_latest_platform_version_dir(hw_parent)
        return ver if ver is not None else None

    if sketch_dir is not None:
        sk = sketch_dir.expanduser().resolve()
        p = try_base(sk / "hardware" / vendor / arch, "sketch/hardware")
        if p is not None:
            return p

    if user_dir is not None:
        ud = user_dir.expanduser().resolve()
        p = try_base(ud / "hardware" / vendor / arch, "user/hardware")
        if p is not None:
            return p

    pk = packages_dir.expanduser().resolve()
    p = try_base(pk / vendor / "hardware" / arch, "packages")
    if p is not None:
        return p

    msg = (
        f"no platform for {vendor}:{arch} (checked sketch/hardware, "
        f"user/hardware, packages). Tried: {tried!r}"
    )
    raise FileNotFoundError(msg)


def list_tool_installations(
    packages_dir: Path,
    tool_name: str,
    *,
    platform_root: Path | None = None,
) -> list[Path]:
    """Installed tool versions: packages/*/tools/<tool>/<ver> and optional platform ``tools/``."""
    found: list[Path] = []
    if packages_dir.is_dir():
        for vendor in packages_dir.iterdir():
            if not vendor.is_dir():
                continue
            tdir = vendor / "tools" / tool_name
            if not tdir.is_dir():
                continue
            for ver in tdir.iterdir():
                if ver.is_dir():
                    found.append(ver.resolve())
    if platform_root is not None:
        local = platform_root / "tools" / tool_name
        if local.is_dir():
            for ver in local.iterdir():
                if ver.is_dir():
                    found.append(ver.resolve())
    found.sort(key=lambda p: semver_key(p.name), reverse=True)
    return found


def resolve_tool_path(
    packages_dir: Path,
    tool_name: str,
    *,
    platform_root: Path | None = None,
) -> Path | None:
    """Newest installation path for tool_name."""
    inst = list_tool_installations(
        packages_dir, tool_name, platform_root=platform_root
    )
    return inst[0] if inst else None


_RUNTIME_TOOLS_RE = re.compile(r"runtime\.tools\.([A-Za-z0-9_.-]+)\.path")


def referenced_runtime_tools(text: str) -> set[str]:
    names: set[str] = set()
    for m in _RUNTIME_TOOLS_RE.finditer(text):
        names.add(m.group(1))
    return names


def resolve_all_runtime_tools(
    packages_dir: Path,
    merged_props: dict[str, str],
    *,
    platform_root: Path | None = None,
) -> dict[str, str]:
    """Build runtime.tools.<name>.path values from merged property strings."""
    names: set[str] = set()
    for v in merged_props.values():
        names |= referenced_runtime_tools(v)
    for k in merged_props:
        names |= referenced_runtime_tools(k)
    out: dict[str, str] = {}
    for name in names:
        p = resolve_tool_path(
            packages_dir, name, platform_root=platform_root
        )
        if p is not None:
            out[f"runtime.tools.{name}.path"] = str(p) + "/"
    return out


def find_arduino_preprocessor() -> Path | None:
    """Locate arduino-preprocessor on PATH or next to arduino-cli."""
    import shutil

    which = shutil.which("arduino-preprocessor")
    if which:
        return Path(which).resolve()
    cli = shutil.which("arduino-cli")
    if cli:
        cand = Path(cli).parent / "arduino-preprocessor"
        if cand.is_file():
            return cand.resolve()
    return None
