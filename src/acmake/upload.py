"""Expand and run platform upload recipes."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from acmake.build import BuildPlan
from acmake.command import split_recipe
from acmake.properties import collapse_duplicate_path_slashes, expand_template

log = logging.getLogger("acmake")


def _os_prop(expanded: dict[str, str], key: str) -> str:
    """Return the OS-specific variant of ``key``, falling back to the base key.

    On Windows, ``key + ".windows"`` is tried first; for all other platforms
    (and when the ``.windows`` key is absent) the base ``key`` is returned.
    This mirrors the ``tools.<tool>.cmd`` / ``tools.<tool>.cmd.windows`` lookup
    that Arduino IDE and arduino-cli perform when reading platform.txt.
    """
    if (expanded.get("runtime.os") or "").lower() == "windows":
        w = expanded.get(f"{key}.windows", "").strip()
        if w:
            return w
    return expanded.get(key, "").strip()


def _tool_upload_placeholder_aliases(expanded: dict[str, str], tool: str) -> dict[str, str]:
    """Arduino-style short tokens used inside ``tools.<tool>.upload.pattern``.

    Injects the tool-scoped shorthands that Arduino IDE / arduino-cli make
    available inside upload patterns:
      {path}             → tools.<tool>.path
      {cmd}              → tools.<tool>.cmd  (OS-specific .windows variant wins)
      {upload.pattern_args} → tools.<tool>.upload.pattern_args
      {upload.flash_prefix} → tools.<tool>.upload.flash_prefix (OS-specific variant wins)
    """
    out: dict[str, str] = {}
    p = _os_prop(expanded, f"tools.{tool}.path").rstrip("/")
    if p:
        out["path"] = p
    c = _os_prop(expanded, f"tools.{tool}.cmd")
    if c:
        out["cmd"] = c
    args_key = f"tools.{tool}.upload.pattern_args"
    if args_key in expanded:
        out["upload.pattern_args"] = expanded[args_key]
    fp = _os_prop(expanded, f"tools.{tool}.upload.flash_prefix")
    if fp:
        out["upload.flash_prefix"] = fp
    return out


def _upload_pattern_property_key(expanded: dict[str, str], tool: str) -> str:
    """Prefer OS-specific ``tools.<tool>.upload.pattern.<os>`` when the platform defines it."""
    ro = (expanded.get("runtime.os") or "").lower()
    base = f"tools.{tool}.upload.pattern"
    if ro == "windows":
        wk = f"{base}.windows"
        if expanded.get(wk, "").strip():
            return wk
    if ro == "linux":
        lk = f"{base}.linux"
        if expanded.get(lk, "").strip():
            return lk
    if ro == "macosx":
        mk = f"{base}.macosx"
        if expanded.get(mk, "").strip():
            return mk
    return base


def expand_upload_pattern(expanded: dict[str, str], serial_port: str) -> str:
    """Return expanded upload.pattern for the board's upload.tool."""
    tool = expanded.get("upload.tool", "").strip()
    if not tool:
        tool = expanded.get("program.tool", "avrdude").strip()
    key = _upload_pattern_property_key(expanded, tool)
    tmpl = expanded.get(key, "")
    if not tmpl.strip():
        raise ValueError(
            f"missing upload recipe {key!r}; install core or check board upload.tool"
        )
    ctx = dict(expanded)
    ctx.update(_tool_upload_placeholder_aliases(expanded, tool))
    ctx["serial.port"] = serial_port
    # Placeholders like {runtime.platform.path}/tools/... can yield // after expansion;
    # same normalization as collapse_duplicate_path_slashes_in_properties on build recipes.
    return collapse_duplicate_path_slashes(expand_template(tmpl, ctx))


def run_upload(plan: BuildPlan, serial_port: str, *, dry_run: bool = False) -> None:
    cmd = expand_upload_pattern(plan.expanded, serial_port)
    argv = split_recipe(cmd)
    if not argv:
        raise ValueError("upload pattern expanded to empty command")
    log.info("upload: %s", " ".join(argv))
    if dry_run:
        return
    subprocess.run(argv, check=True, cwd=str(plan.build_dir.resolve()))
