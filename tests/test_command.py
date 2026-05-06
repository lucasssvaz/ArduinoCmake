"""Tests for recipe argv splitting."""

from acmake.cmakegen import _cmake_bracket_argument
from acmake.command import split_recipe


def test_split_recipe_preserves_quotes_in_d_string_macro():
    cmd = 'xtensa-g++ -DARDUINO_FQBN="espressif:esp32:esp32s3" -MMD -c x.cpp'
    argv = split_recipe(cmd)
    assert any(a == '-DARDUINO_FQBN="espressif:esp32:esp32s3"' for a in argv)


def test_cmake_bracket_argument_preserves_inner_quotes_for_verbatim_command():
    """``add_custom_command(... VERBATIM)`` COMMAND tokens must not use raw ``"`` (CMake 4.x)."""
    arg = '-DARDUINO_FQBN="espressif:esp32:esp32s3"'
    b = _cmake_bracket_argument(arg)
    assert arg in b or arg.replace("\\", "/") in b
    assert b.startswith("[[")
    assert b.endswith("]]")


def test_cmake_bracket_argument_longer_delimiter_when_body_has_close_brackets() -> None:
    s = "a]]b"
    b = _cmake_bracket_argument(s)
    assert s in b
    assert b.startswith("[=[")
    assert b.endswith("]=]")


def test_split_recipe_two_quoted_defines():
    cmd = 'g++ -DA="1:2" -DB="3" -O2'
    argv = split_recipe(cmd)
    assert '-DA="1:2"' in argv and '-DB="3"' in argv


def test_split_recipe_windows_shlex_leaves_quotes_strip_argv0_for_cmake4():
    """Quoted compiler path + POSIX ``-I`` must yield a clean argv0 (CMake 4)."""
    cmd = r'"C:/Users/runner/xtensa-esp32-elf-g++.exe" -c x.cpp'
    argv = split_recipe(cmd)
    assert argv[0] == "C:/Users/runner/xtensa-esp32-elf-g++.exe"
    assert argv[1:] == ["-c", "x.cpp"]


def test_split_recipe_quoted_include_paths_with_spaces_even_on_windows_host():
    """``posix=False`` would break ``-I"C:/My Documents/..."``; recipes are POSIX-quoted."""
    cmd = (
        r'"C:/tools/xtensa-g++.exe" -MMD -c '
        r'-I"C:/My Documents/Arduino/hardware/esp32/cores/esp32" '
        r'-I"C:/My Documents/Arduino/hardware/esp32/variants/esp32" '
        r'-DARDUINO_BOARD="ESP32_DEV" x.cpp'
    )
    argv = split_recipe(cmd)
    assert argv[0] == "C:/tools/xtensa-g++.exe"
    assert "-IC:/My Documents/Arduino/hardware/esp32/cores/esp32" in argv
    assert "-IC:/My Documents/Arduino/hardware/esp32/variants/esp32" in argv
    assert '-DARDUINO_BOARD="ESP32_DEV"' in argv
    assert argv[-1] == "x.cpp"
