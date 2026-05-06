"""Platform root must not treat ``libraries/`` as a core version folder."""

from pathlib import Path

from acmake.discovery import find_latest_platform_version_dir, resolve_platform_root


def test_find_latest_platform_skips_libraries_sibling(tmp_path: Path) -> None:
    hw = tmp_path / "hardware" / "espressif" / "esp32"
    hw.mkdir(parents=True)
    lib = hw / "libraries"
    lib.mkdir()
    (lib / "ESP32").mkdir()
    ver = hw / "3.0.7"
    ver.mkdir()
    (ver / "platform.txt").write_text("name=esp32\n", encoding="utf-8")
    (ver / "boards.txt").write_text("uno.name=Uno\n", encoding="utf-8")

    chosen = find_latest_platform_version_dir(hw)
    assert chosen is not None
    assert chosen.name == "3.0.7"
    assert (chosen / "platform.txt").is_file()


def test_resolve_user_hardware_prefers_semver_over_libraries(tmp_path: Path) -> None:
    user = tmp_path / "Arduino"
    hw = user / "hardware" / "espressif" / "esp32"
    hw.mkdir(parents=True)
    (hw / "libraries").mkdir()
    (hw / "2.0.0").mkdir()
    (hw / "2.0.0" / "platform.txt").write_text("x=1\n", encoding="utf-8")
    (hw / "2.0.0" / "boards.txt").write_text("b.name=B\n", encoding="utf-8")

    sketch = tmp_path / "GetMacAddress"
    sketch.mkdir()

    root = resolve_platform_root(
        tmp_path / "empty_packages",
        "espressif",
        "esp32",
        sketch_dir=sketch,
        user_dir=user,
    )
    assert root.name == "2.0.0"
