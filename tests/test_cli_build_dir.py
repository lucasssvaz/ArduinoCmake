"""Default and overridden sketch build directories."""

from pathlib import Path

from acmake.cli import resolve_sketch_build_dir


def test_default_build_dir_is_sketch_build(tmp_path: Path) -> None:
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    assert resolve_sketch_build_dir(sketch) == (sketch / "build").resolve()


def test_build_path_overrides_output_dir(tmp_path: Path) -> None:
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    a = tmp_path / "a"
    b = tmp_path / "b"
    assert resolve_sketch_build_dir(
        sketch,
        build_path=a,
        output_dir=b,
    ) == a.resolve()


def test_output_dir_when_no_build_path(tmp_path: Path) -> None:
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    custom = tmp_path / "out"
    assert resolve_sketch_build_dir(sketch, output_dir=custom) == custom.resolve()
