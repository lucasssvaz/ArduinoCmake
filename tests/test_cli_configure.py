"""CMake configure: only bootstrap an unconfigured build dir."""

from pathlib import Path

from acmake.cli import should_run_cmake_configure


def test_configure_needed_without_ninja(tmp_path: Path) -> None:
    b = tmp_path / "build"
    b.mkdir()
    (b / "CMakeLists.txt").write_text("x", encoding="utf-8")
    (b / "CMakeCache.txt").write_text("x", encoding="utf-8")
    assert should_run_cmake_configure(b) is True


def test_configure_needed_without_cmakecache(tmp_path: Path) -> None:
    b = tmp_path / "build"
    b.mkdir()
    (b / "CMakeLists.txt").write_text("x", encoding="utf-8")
    (b / "build.ninja").write_text("#\n", encoding="utf-8")
    assert should_run_cmake_configure(b) is True


def test_configure_skipped_when_already_configured(tmp_path: Path) -> None:
    b = tmp_path / "build"
    b.mkdir()
    (b / "CMakeLists.txt").write_text("x", encoding="utf-8")
    (b / "CMakeCache.txt").write_text("x", encoding="utf-8")
    (b / "build.ninja").write_text("#\n", encoding="utf-8")
    assert should_run_cmake_configure(b) is False
