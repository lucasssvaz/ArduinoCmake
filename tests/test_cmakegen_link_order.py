"""``{object_files}`` order matches arduino-cli (sketch → libraries → variant)."""

from pathlib import Path

from acmake.build import BuildPlan, SourceObject
from acmake.cmakegen import link_combine_object_paths, _expand_combine
from acmake.fqbn import FQBN


def _so(kind: str, name: str, base: Path) -> SourceObject:
    return SourceObject(
        source=base / f"{name}.cpp",
        object_path=base / f"{name}.o",
        dep_path=base / f"{name}.d",
        kind=kind,
        lib=None,
    )


def test_link_combine_object_paths_sketch_before_libs_before_variant(
    tmp_path: Path,
) -> None:
    bd = tmp_path / "b"
    sk = bd / "sk"
    plan = BuildPlan(
        fqbn=FQBN.parse("esp32:esp32:esp32"),
        platform_root=bd,
        sketch_dir=sk,
        build_dir=bd,
        expanded={},
        sources=[
            _so("variant", "pins", bd),
            _so("lib", "Wire", bd),
            _so("sketch", "sketch", bd),
            _so("core", "wiring", bd),
        ],
    )
    ordered = link_combine_object_paths(plan)
    assert [p.name for p in ordered] == ["sketch.o", "Wire.o", "pins.o"]


def test_expand_combine_emits_sketch_paths_before_library_paths(
    tmp_path: Path,
) -> None:
    bd = tmp_path / "b"
    plan = BuildPlan(
        fqbn=FQBN.parse("esp32:esp32:esp32"),
        platform_root=bd,
        sketch_dir=bd / "sk",
        build_dir=bd,
        expanded={
            "recipe.c.combine.pattern": "ld -o out.elf {object_files}",
        },
        sources=[
            _so("lib", "LibA", bd),
            _so("sketch", "main", bd),
        ],
    )
    cmd = _expand_combine(plan, link_combine_object_paths(plan))
    assert "main.o" in cmd
    assert "LibA.o" in cmd
    assert cmd.index("main.o") < cmd.index("LibA.o")
