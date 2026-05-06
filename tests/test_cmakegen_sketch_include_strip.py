"""Strip sketch ``-I`` from cached TU recipes (ESP32 ``compiler.cpreprocessor.flags``)."""

from pathlib import Path

from acmake.build import BuildPlan
from acmake.cmakegen import _strip_sketch_source_path_from_compile_recipe
from acmake.fqbn import FQBN


def test_strip_removes_quoted_sketch_minus_i(tmp_path: Path) -> None:
    sketch = tmp_path / "ExampleB"
    sketch.mkdir()
    sp = str(sketch.resolve()).replace("\\", "/")
    fqbn = FQBN("espressif", "esp32", "devkit")
    plan = BuildPlan(
        fqbn=fqbn,
        platform_root=tmp_path / "p",
        sketch_dir=sketch,
        build_dir=tmp_path / "build",
        expanded={"build.source.path": sp + "/"},
        object_cache_dir=tmp_path / "cache",
    )
    cmd = (
        f'g++ -MMD -c "@/sdk/defines" -I"{sp}/" -I/other '
        f'"{sp}/sketch.cpp" -o out.o'
    )
    out = _strip_sketch_source_path_from_compile_recipe(plan, cmd)
    assert f'-I"{sp}/"' not in out and f'-I"{sp}"' not in out
    assert "-I/other" in out
    assert "sketch.cpp" in out


def test_strip_handles_build_source_path_key(tmp_path: Path) -> None:
    sketch = tmp_path / "Sk"
    sketch.mkdir()
    alt = "/tmp/other/alias"
    fqbn = FQBN("espressif", "esp32", "devkit")
    plan = BuildPlan(
        fqbn=fqbn,
        platform_root=tmp_path / "p",
        sketch_dir=sketch,
        build_dir=tmp_path / "build",
        expanded={"build.source.path": alt},
        object_cache_dir=tmp_path / "cache",
    )
    cmd = f'g++ -c -I"{alt}" -I/x'
    out = _strip_sketch_source_path_from_compile_recipe(plan, cmd)
    assert alt not in out
    assert "-I/x" in out
