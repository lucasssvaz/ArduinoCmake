"""Optional conformance checks against arduino-cli (skipped if not installed)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from acmake.build import prepare_build
from acmake.config import ArduinoPaths
from acmake.fqbn import FQBN


def _normalize_verbose(text: str) -> str:
    """Strip volatile paths/timestamps from compiler -v style logs."""
    t = text.replace("\\", "/")
    t = re.sub(r"/[^\s]+/Arduino15", "<DATA>", t)
    t = re.sub(r"/var/folders/[^\s]+", "<TMP>", t)
    t = re.sub(r"/tmp/[^\s]+", "<TMP>", t)
    return t


@pytest.mark.skipif(shutil.which("arduino-cli") is None, reason="arduino-cli not on PATH")
def test_prepare_build_does_not_raise_for_uno(tmp_path: Path):
    """Smoke: if AVR core is installed, prepare_build completes."""
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    (sketch / "Blink.ino").write_text(
        "void setup(){}\nvoid loop(){}\n", encoding="utf-8"
    )
    build = tmp_path / "out"
    paths = ArduinoPaths.from_env()
    fqbn = FQBN.parse("arduino:avr:uno")
    try:
        plan = prepare_build(
            fqbn,
            sketch,
            build,
            paths,
            use_preprocessor=False,
        )
    except FileNotFoundError:
        pytest.skip("arduino:avr platform not installed")
    assert plan.expanded.get("recipe.c.combine.pattern", "").strip()
    assert plan.elf_path is not None


@pytest.mark.skipif(shutil.which("arduino-cli") is None, reason="arduino-cli not on PATH")
def test_verbose_compile_contains_compiler_invocation(tmp_path: Path):
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    (sketch / "Blink.ino").write_text(
        "void setup(){}\nvoid loop(){}\n", encoding="utf-8"
    )
    build = tmp_path / "b"
    r = subprocess.run(
        [
            "arduino-cli",
            "compile",
            "-v",
            "--fqbn",
            "arduino:avr:uno",
            "--output-dir",
            str(build),
            str(sketch),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        pytest.skip("arduino:avr:uno compile failed (missing core?)")
    out = _normalize_verbose(r.stdout + r.stderr)
    assert "avr-gcc" in out or "avr-g++" in out
