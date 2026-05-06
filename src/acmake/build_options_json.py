"""Write ``build.options.json`` in the sketch build dir (``arduino-cli`` / IDE parity)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from acmake.config import ArduinoPaths
from acmake.fqbn import FQBN
from acmake.properties import normalize_compiler_warning_level


def _hardware_folders_list(paths: ArduinoPaths, sketch_dir: Path) -> list[str]:
    """``packages`` dir, sketchbook ``hardware``, and sketch-local ``hardware`` when present."""
    out: list[str] = [str(paths.packages_dir.resolve())]
    uh = (paths.user_dir / "hardware").resolve()
    if uh.is_dir():
        out.append(str(uh))
    sh = (sketch_dir / "hardware").resolve()
    if sh.is_dir():
        out.append(str(sh))
    return out


def _additional_files_relative(build_dir: Path, sketch_dir: Path) -> str | None:
    """Relative path from *build_dir* to the ``examples`` dir (parent of the sketch folder).

    Matches ``arduino-cli``: e.g. ``…/libraries/Lib/examples/Sketch/build`` → ``../..`` (the
    ``examples`` folder), not the library bundle root.
    """
    sk = sketch_dir.resolve()
    examples_dir = sk.parent
    if examples_dir.name != "examples" or not examples_dir.is_dir():
        return None
    try:
        return os.path.relpath(examples_dir, build_dir.resolve())
    except ValueError:
        return None


def write_build_options_json(
    *,
    build_dir: Path,
    sketch_dir: Path,
    paths: ArduinoPaths,
    fqbn: FQBN,
    expanded: dict[str, str],
    build_properties: list[str] | None,
    compiler_warnings: str | None,
) -> Path:
    """Write ``<build_dir>/build.options.json``. Returns the file path."""
    build_dir = build_dir.resolve()
    sketch_dir = sketch_dir.resolve()
    opts: dict[str, str] = {
        "fqbn": fqbn.to_string(),
        "sketchLocation": str(sketch_dir),
        "hardwareFolders": ",".join(_hardware_folders_list(paths, sketch_dir)),
        "otherLibrariesFolders": str(paths.user_libraries_dir.resolve()),
    }
    af = _additional_files_relative(build_dir, sketch_dir)
    if af:
        opts["additionalFiles"] = af
    cof = (expanded.get("compiler.optimization_flags") or "").strip()
    if cof:
        opts["compiler.optimization_flags"] = cof
    custom_parts: list[str] = []
    prop_keys: set[str] = set()
    if build_properties:
        for p in build_properties:
            ps = str(p).strip()
            if not ps:
                continue
            custom_parts.append(ps)
            if "=" in ps:
                prop_keys.add(ps.split("=", 1)[0].strip())
    if compiler_warnings:
        lv = normalize_compiler_warning_level(compiler_warnings)
        wkey = f"compiler.warning_flags.{lv}"
        wv = (expanded.get("compiler.warning_flags") or "").strip()
        if wv and wkey not in prop_keys:
            custom_parts.append(f"{wkey}={wv}")
    if custom_parts:
        opts["customBuildProperties"] = ",".join(custom_parts)
    dest = build_dir / "build.options.json"
    dest.write_text(json.dumps(opts, indent=2) + "\n", encoding="utf-8")
    return dest
