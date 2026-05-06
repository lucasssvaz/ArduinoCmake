"""Platform resolution prefers sketch-local hardware/."""

from pathlib import Path

from acmake.board_list import list_installed_boards
from acmake.config import ArduinoPaths
from acmake.discovery import resolve_platform_root


def _write_platform(root: Path, name: str) -> None:
    (root / "platform.txt").write_text(f"name={name}\n", encoding="utf-8")
    (root / "boards.txt").write_text("uno.name=Uno\n", encoding="utf-8")


def test_sketch_hardware_wins_over_packages(tmp_path: Path) -> None:
    sketch = tmp_path / "MySketch"
    sketch.mkdir()
    pkgs = tmp_path / "packages"
    user = tmp_path / "ArduinoUser"

    sketch_core = sketch / "hardware" / "acme" / "avr" / "1.0.0"
    sketch_core.mkdir(parents=True)
    _write_platform(sketch_core, "sketch-core")

    pkg_core = pkgs / "acme" / "hardware" / "avr" / "2.0.0"
    pkg_core.mkdir(parents=True)
    _write_platform(pkg_core, "pkg-core")

    chosen = resolve_platform_root(
        pkgs,
        "acme",
        "avr",
        sketch_dir=sketch,
        user_dir=user,
    )
    assert chosen.resolve() == sketch_core.resolve()
    assert (chosen / "platform.txt").read_text().startswith("name=sketch-core")


def test_user_hardware_before_packages(tmp_path: Path) -> None:
    sketch = tmp_path / "PlainSketch"
    sketch.mkdir()
    pkgs = tmp_path / "packages"
    user = tmp_path / "ArduinoUser"
    user_core = user / "hardware" / "acme" / "avr" / "1.5.0"
    user_core.mkdir(parents=True)
    _write_platform(user_core, "user-core")

    pkg_core = pkgs / "acme" / "hardware" / "avr" / "9.0.0"
    pkg_core.mkdir(parents=True)
    _write_platform(pkg_core, "pkg-core")

    chosen = resolve_platform_root(
        pkgs,
        "acme",
        "avr",
        sketch_dir=sketch,
        user_dir=user,
    )
    assert chosen.resolve() == user_core.resolve()


def test_board_list_includes_sketch_hardware(tmp_path: Path) -> None:
    sketch = tmp_path / "Portable"
    core = sketch / "hardware" / "myvendor" / "myarch" / "1.0.0"
    core.mkdir(parents=True)
    (core / "platform.txt").write_text("name=test\n", encoding="utf-8")
    (core / "boards.txt").write_text("custom.name=Custom\n", encoding="utf-8")

    paths = ArduinoPaths(data_dir=tmp_path / "data", user_dir=tmp_path / "user")
    lines = list_installed_boards(paths, sketch_dirs=[sketch])
    assert "myvendor:myarch:custom" in lines
