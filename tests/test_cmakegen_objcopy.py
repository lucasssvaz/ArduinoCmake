"""``recipe.objcopy.*.pattern`` discovery (ESP32 ``partitions.bin``, ``bin``, AVR ``hex``/``eep``)."""

from pathlib import Path

from acmake.cmakegen import (
    infer_objcopy_output_path,
    ordered_objcopy_recipe_keys,
    stem_from_objcopy_recipe_key,
)
from acmake.build import BuildPlan
from acmake.fqbn import FQBN


def _minimal_plan(expanded: dict, build_dir: Path) -> BuildPlan:
    return BuildPlan(
        fqbn=FQBN.parse("vendor:arch:board"),
        platform_root=build_dir,
        sketch_dir=build_dir / "sk",
        build_dir=build_dir,
        expanded=expanded,
        sources=[],
        elf_path=build_dir / "Sketch.elf",
        hex_path=build_dir / "Sketch.hex",
        eep_path=build_dir / "Sketch.eep",
        bin_path=build_dir / "Sketch.bin",
    )


def test_os_specific_objcopy_wins(tmp_path: Path) -> None:
    e = {
        "runtime.os": "linux",
        "build.project_name": "Sketch",
        "recipe.objcopy.bin.pattern": "generic",
        "recipe.objcopy.bin.pattern.linux": "python-linux",
    }
    keys = ordered_objcopy_recipe_keys(e)
    assert keys == ["recipe.objcopy.bin.pattern.linux"]


def test_partitions_bin_before_bin(tmp_path: Path) -> None:
    e = {
        "runtime.os": "linux",
        "build.project_name": "Sketch",
        "recipe.objcopy.bin.pattern": "b",
        "recipe.objcopy.partitions.bin.pattern": "p",
    }
    assert ordered_objcopy_recipe_keys(e) == [
        "recipe.objcopy.partitions.bin.pattern",
        "recipe.objcopy.bin.pattern",
    ]


def test_hex_before_eep(tmp_path: Path) -> None:
    e = {
        "runtime.os": "linux",
        "recipe.objcopy.eep.pattern": "e",
        "recipe.objcopy.hex.pattern": "h",
    }
    assert ordered_objcopy_recipe_keys(e) == [
        "recipe.objcopy.hex.pattern",
        "recipe.objcopy.eep.pattern",
    ]


def test_pattern_args_not_collected(tmp_path: Path) -> None:
    e = {
        "runtime.os": "linux",
        "recipe.objcopy.bin.pattern_args": "--chip x",
        "recipe.objcopy.bin.pattern": "esptool {recipe.objcopy.bin.pattern_args}",
    }
    assert ordered_objcopy_recipe_keys(e) == ["recipe.objcopy.bin.pattern"]


def test_infer_partitions_output(tmp_path: Path) -> None:
    bd = tmp_path / "b"
    bd.mkdir()
    e = {"build.project_name": "MySketch", "runtime.os": "linux"}
    plan = _minimal_plan(e, bd)
    argv = ["tool", "-q", str(bd / "partitions.csv"), str(bd / "MySketch.partitions.bin")]
    p = infer_objcopy_output_path(plan, "partitions.bin", argv)
    assert p == bd / "MySketch.partitions.bin"


def test_stem_from_os_key() -> None:
    assert stem_from_objcopy_recipe_key("recipe.objcopy.bin.pattern.linux") == "bin"
