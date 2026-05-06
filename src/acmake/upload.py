"""Expand and run platform upload recipes."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from acmake.build import BuildPlan
from acmake.command import split_recipe
from acmake.properties import expand_template

log = logging.getLogger("acmake")


def _tool_cmd_for_runtime(expanded: dict[str, str], tool: str) -> str:
    ro = (expanded.get("runtime.os") or "").lower()
    if ro == "windows":
        w = expanded.get(f"tools.{tool}.cmd.windows", "").strip()
        if w:
            return w
    return expanded.get(f"tools.{tool}.cmd", "").strip()


def _tool_upload_placeholder_aliases(expanded: dict[str, str], tool: str) -> dict[str, str]:
    """Arduino-style short tokens used inside ``tools.<tool>.upload.pattern``.

    Many cores (e.g. ESP32) use ``"{path}/{cmd}" {upload.pattern_args}`` where
    ``path`` / ``cmd`` are ``tools.<tool>.path`` / ``tools.<tool>.cmd``, and
    ``upload.pattern_args`` is shorthand for ``tools.<tool>.upload.pattern_args``.
    """
    out: dict[str, str] = {}
    p = expanded.get(f"tools.{tool}.path", "").strip().rstrip("/")
    if p:
        out["path"] = p
    c = _tool_cmd_for_runtime(expanded, tool)
    if c:
        out["cmd"] = c
    args_key = f"tools.{tool}.upload.pattern_args"
    if args_key in expanded:
        out["upload.pattern_args"] = expanded.get(args_key, "")
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
    return expand_template(tmpl, ctx)


def run_upload(plan: BuildPlan, serial_port: str, *, dry_run: bool = False) -> None:
    cmd = expand_upload_pattern(plan.expanded, serial_port)
    argv = split_recipe(cmd)
    if not argv:
        raise ValueError("upload pattern expanded to empty command")
    log.info("upload: %s", " ".join(argv))
    if dry_run:
        return
    subprocess.run(argv, check=True, cwd=str(plan.build_dir.resolve()))
