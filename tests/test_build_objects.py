"""Object filenames mirror sources; helpers stay deterministic."""

from pathlib import Path

from acmake.build import _object_basename_for_translation_unit
from acmake.libraries import Library


def test_object_basename_core_matches_source_name(tmp_path: Path) -> None:
    core = tmp_path / "cores" / "esp32"
    core.mkdir(parents=True)
    src = core / "HardwareSerial.cpp"
    src.write_text("//\n", encoding="utf-8")
    v = tmp_path / "variant"
    v.mkdir()
    sk = tmp_path / "Sketch"
    sk.mkdir()
    sb = tmp_path / "build" / "sketch"
    sb.mkdir(parents=True)
    assert (
        _object_basename_for_translation_unit(
            src,
            "core",
            core_path=core,
            variant_path=v,
            sketch_dir=sk,
            sketch_build=sb,
            lib=None,
        )
        == "HardwareSerial.cpp.o"
    )


def test_object_basename_core_nested_path(tmp_path: Path) -> None:
    core = tmp_path / "c"
    core.mkdir()
    src = core / "driver" / "gpio.c"
    src.parent.mkdir(parents=True)
    src.write_text("//\n", encoding="utf-8")
    v = tmp_path / "v"
    v.mkdir()
    sk = tmp_path / "sk"
    sk.mkdir()
    sb = tmp_path / "b" / "sketch"
    sb.mkdir(parents=True)
    assert (
        _object_basename_for_translation_unit(
            src,
            "core",
            core_path=core,
            variant_path=v,
            sketch_dir=sk,
            sketch_build=sb,
            lib=None,
        )
        == "driver__gpio.c.o"
    )


def test_object_basename_lib_relative_to_library_root(tmp_path: Path) -> None:
    lib_root = tmp_path / "Wire"
    lib_root.mkdir()
    src = lib_root / "src" / "Wire.cpp"
    src.parent.mkdir(parents=True)
    src.write_text("//\n", encoding="utf-8")
    core = tmp_path / "core"
    core.mkdir()
    v = tmp_path / "v"
    v.mkdir()
    sk = tmp_path / "sk"
    sk.mkdir()
    sb = tmp_path / "b" / "sketch"
    sb.mkdir(parents=True)
    lib = Library(
        root=lib_root.resolve(),
        name="Wire",
        architectures="*",
        depends=(),
        includes_override=None,
    )
    assert (
        _object_basename_for_translation_unit(
            src,
            "lib",
            core_path=core,
            variant_path=v,
            sketch_dir=sk,
            sketch_build=sb,
            lib=lib,
        )
        == "src__Wire.cpp.o"
    )


def test_object_basename_sketch_build_sketch_cpp(tmp_path: Path) -> None:
    sk = tmp_path / "Sketch"
    sk.mkdir()
    sb = tmp_path / "out" / "sketch"
    sb.mkdir(parents=True)
    sc = sb / "sketch.cpp"
    sc.write_text("//\n", encoding="utf-8")
    core = tmp_path / "core"
    core.mkdir()
    v = tmp_path / "v"
    v.mkdir()
    assert (
        _object_basename_for_translation_unit(
            sc,
            "sketch",
            core_path=core,
            variant_path=v,
            sketch_dir=sk,
            sketch_build=sb,
            lib=None,
        )
        == "sketch.cpp.o"
    )
