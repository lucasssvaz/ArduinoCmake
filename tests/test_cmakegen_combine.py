"""Link recipe resolution (OS-specific / numbered / fallbacks)."""

from acmake.cmakegen import _link_combine_template


def test_default_combine():
    e = {
        "runtime.os": "macosx",
        "recipe.c.combine.pattern": 'gcc -o "{build.path}/x.elf" {object_files}',
    }
    assert "gcc" in _link_combine_template(e)


def test_os_specific_wins():
    e = {
        "runtime.os": "macosx",
        "recipe.c.combine.pattern": "generic",
        "recipe.c.combine.pattern.macosx": "macos-link",
    }
    assert _link_combine_template(e) == "macos-link"


def test_numbered_fragments():
    e = {
        "runtime.os": "linux",
        "recipe.c.combine.pattern.1": "gcc start",
        "recipe.c.combine.pattern.2": "end",
    }
    assert _link_combine_template(e) == "gcc start end"


def test_cpp_combine_fallback():
    e = {"runtime.os": "linux", "recipe.cpp.combine.pattern": "g++ link"}
    assert _link_combine_template(e) == "g++ link"


def test_heuristic_combine_key():
    e = {
        "runtime.os": "linux",
        "recipe.mycombine.pattern": "ld -o out {object_files}",
    }
    assert "ld" in _link_combine_template(e)
