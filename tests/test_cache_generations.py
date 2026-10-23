"""Immutable platform and library cache generation selection."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from acmake.cache_invalidate import maybe_refresh_object_cache
from acmake.libraries import Library


def _library(root: Path, name: str) -> Library:
    root.mkdir(parents=True)
    (root / "library.properties").write_text(
        f"name={name}\narchitectures=*\n", encoding="utf-8"
    )
    src = root / "src"
    src.mkdir()
    (src / f"{name}.h").write_text("// header\n", encoding="utf-8")
    (src / f"{name}.cpp").write_text("// source\n", encoding="utf-8")
    return Library(
        root=root.resolve(),
        name=name,
        architectures="*",
        depends=(),
        includes_override=None,
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    cache = tmp_path / "cache"
    build = tmp_path / "build"
    core = tmp_path / "core"
    variant = tmp_path / "variant"
    build.mkdir()
    core.mkdir()
    variant.mkdir()
    (build / "build_opt.h").write_bytes(b"")
    (core / "main.cpp").write_text("// core\n", encoding="utf-8")
    (core / "main.h").write_text("// header\n", encoding="utf-8")
    (variant / "pins.c").write_text("// pins\n", encoding="utf-8")
    return cache, build, core, variant


def _expanded(compiler: Path, *, define: str = "-DFEATURE=1") -> dict[str, str]:
    recipe = (
        f'"{compiler}" {define} {{includes}} -c "{{source_file}}" -o "{{object_file}}"'
    )
    return {
        "recipe.c.o.pattern": recipe,
        "recipe.cpp.o.pattern": recipe,
        "recipe.S.o.pattern": recipe,
    }


def test_unchanged_inputs_reuse_identical_generation(tmp_path: Path) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "Lib", "Lib")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    assert first.platform_dir == second.platform_dir
    assert first.library_dir(lib) == second.library_dir(lib)
    assert first.bucket_dir == cache


def test_platform_mtime_only_change_reuses_generation(tmp_path: Path) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    source = core / "main.cpp"
    stat = source.stat()
    os.utime(source, (stat.st_atime + 500, stat.st_mtime + 500))
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    assert second.platform_dir == first.platform_dir


def test_platform_content_change_selects_new_generation_without_deletion(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    artifact = first.platform_dir / "core" / "o" / "main.cpp.o"
    artifact.write_bytes(b"live-old-object")
    (core / "main.h").write_text("// changed header\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    assert second.platform_dir != first.platform_dir
    assert artifact.read_bytes() == b"live-old-object"


def test_platform_source_change_also_selects_new_generation(tmp_path: Path) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    (core / "main.cpp").write_text("// changed source\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    assert second.platform_dir != first.platform_dir


def test_core_source_change_does_not_invalidate_library_generation(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "Lib", "Lib")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    (core / "main.cpp").write_text(
        "// unrelated core source change\n", encoding="utf-8"
    )
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    assert second.platform_dir != first.platform_dir
    assert second.library_platform_fingerprint == first.library_platform_fingerprint
    assert second.library_dir(lib) == first.library_dir(lib)


def test_only_changed_library_selects_new_library_generation(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    one = _library(tmp_path / "One", "One")
    two = _library(tmp_path / "Two", "Two")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[one, two],
    )
    old_object = first.library_dir(one) / "o" / "One.cpp.o"
    old_object.write_bytes(b"live")
    (one.root / "src" / "One.h").write_text("// changed\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[one, two],
    )
    assert second.platform_dir == first.platform_dir
    assert second.library_dir(one) != first.library_dir(one)
    assert second.library_dir(two) == first.library_dir(two)
    assert old_object.read_bytes() == b"live"


def test_library_mtime_and_set_order_do_not_change_generation(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    one = _library(tmp_path / "One", "One")
    two = _library(tmp_path / "Two", "Two")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[one, two],
    )
    header = one.root / "src" / "One.h"
    stat = header.stat()
    os.utime(header, (stat.st_atime + 100, stat.st_mtime + 100))
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[two, one],
    )
    assert second.library_dir(one) == first.library_dir(one)
    assert second.library_dir(two) == first.library_dir(two)


def test_build_opt_bytes_select_library_generation_but_never_delete_old(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "Lib", "Lib")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    old_object = first.library_dir(lib) / "o" / "Lib.cpp.o"
    old_object.write_bytes(b"live")
    (build / "build_opt.h").write_bytes(b"-DFEATURE=1\n")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    assert second.library_dir(lib) != first.library_dir(lib)
    assert old_object.is_file()


def test_missing_platform_directories_select_stable_empty_generation(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    build = tmp_path / "build"
    build.mkdir()
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=tmp_path / "missing-core",
        variant_path=tmp_path / "missing-variant",
        libraries=[],
    )
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=tmp_path / "missing-core",
        variant_path=tmp_path / "missing-variant",
        libraries=[],
    )
    assert first.platform_dir == second.platform_dir


def test_different_effective_compile_command_selects_new_generations(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"toolchain-v1")
    lib = _library(tmp_path / "Lib", "Lib")
    common = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
        platform_root=tmp_path,
        platform_includes="-I/platform",
        library_includes={lib.root: "-I/platform -I/lib"},
        library_dependencies={lib.root: [lib]},
    )
    first = maybe_refresh_object_cache(
        expanded=_expanded(compiler, define="-DVALUE=1"), **common
    )
    second = maybe_refresh_object_cache(
        expanded=_expanded(compiler, define="-DVALUE=2"), **common
    )
    assert second.platform_dir != first.platform_dir
    assert second.library_dir(lib) != first.library_dir(lib)


def test_platform_and_board_config_bytes_select_new_generation(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"toolchain")
    platform = tmp_path / "platform"
    platform.mkdir()
    config = platform / "boards.txt"
    config.write_text("board.build.flag=one\n", encoding="utf-8")
    lib = _library(tmp_path / "Lib", "Lib")
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
        expanded=_expanded(compiler),
        platform_root=platform,
        library_includes={lib.root: "-I/lib"},
        library_dependencies={lib.root: [lib]},
    )
    first = maybe_refresh_object_cache(**args)
    config.write_text("board.build.flag=two\n", encoding="utf-8")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir
    assert second.library_dir(lib) != first.library_dir(lib)


def test_compiler_binary_content_is_part_of_generation_identity(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"toolchain-v1")
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
        expanded=_expanded(compiler),
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(**args)
    compiler.write_bytes(b"toolchain-v2")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir


def test_archiver_identity_changes_core_archive_generation_only(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    archiver = tmp_path / "archiver"
    archiver.write_bytes(b"archiver-v1")
    lib = _library(tmp_path / "Lib", "Lib")
    expanded = _expanded(compiler)
    expanded.update(
        {
            "compiler.path": str(tmp_path) + os.sep,
            "compiler.ar.cmd": "archiver",
        }
    )
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
        expanded=expanded,
        platform_root=tmp_path,
        library_includes={lib.root: "-I/lib"},
        library_dependencies={lib.root: [lib]},
    )
    first = maybe_refresh_object_cache(**args)
    archiver.write_bytes(b"archiver-v2")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir
    assert second.library_dir(lib) == first.library_dir(lib)


def test_transitive_library_dependency_content_selects_new_generation(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"toolchain")
    root = _library(tmp_path / "Root", "Root")
    dependency = _library(tmp_path / "Dependency", "Dependency")
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[root, dependency],
        expanded=_expanded(compiler),
        platform_root=tmp_path,
        library_includes={
            root.root: "-I/root -I/dependency",
            dependency.root: "-I/dependency",
        },
        library_dependencies={
            root.root: [root, dependency],
            dependency.root: [dependency],
        },
    )
    first = maybe_refresh_object_cache(**args)
    (dependency.root / "src" / "Dependency.h").write_text(
        "// changed dependency\n", encoding="utf-8"
    )
    second = maybe_refresh_object_cache(**args)
    assert second.library_dir(root) != first.library_dir(root)
    assert second.library_dir(dependency) != first.library_dir(dependency)


def test_unrelated_library_set_preserves_existing_library_generation(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"toolchain")
    root = _library(tmp_path / "Root", "Root")
    unrelated = _library(tmp_path / "Unrelated", "Unrelated")
    common = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        expanded=_expanded(compiler),
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(
        libraries=[root],
        library_includes={root.root: "-I/root"},
        library_dependencies={root.root: [root]},
        **common,
    )
    second = maybe_refresh_object_cache(
        libraries=[root, unrelated],
        library_includes={
            root.root: "-I/root",
            unrelated.root: "-I/unrelated",
        },
        library_dependencies={
            root.root: [root],
            unrelated.root: [unrelated],
        },
        **common,
    )
    assert second.library_dir(root) == first.library_dir(root)


def test_build_path_is_normalized_but_response_file_content_is_not(
    tmp_path: Path,
) -> None:
    cache, _build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"toolchain")
    build_a = tmp_path / "build-a"
    build_b = tmp_path / "build-b"
    build_a.mkdir()
    build_b.mkdir()
    for build in (build_a, build_b):
        (build / "build_opt.h").write_bytes(b"")
        (build / "flags.rsp").write_text("-DSAME=1\n", encoding="utf-8")

    def expanded(build: Path) -> dict[str, str]:
        response = build / "flags.rsp"
        recipe = f'"{compiler}" "@{response}" -c "{{source_file}}" -o "{{object_file}}"'
        return {"recipe.c.o.pattern": recipe}

    common = dict(
        cache_root=cache,
        core_path=core,
        variant_path=variant,
        libraries=[],
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(
        build_dir=build_a, expanded=expanded(build_a), **common
    )
    second = maybe_refresh_object_cache(
        build_dir=build_b, expanded=expanded(build_b), **common
    )
    assert second.platform_dir == first.platform_dir

    (build_b / "flags.rsp").write_text("-DSAME=2\n", encoding="utf-8")
    changed = maybe_refresh_object_cache(
        build_dir=build_b, expanded=expanded(build_b), **common
    )
    assert changed.platform_dir != first.platform_dir


def test_sketch_include_path_does_not_select_a_new_core_generation(
    tmp_path: Path,
) -> None:
    """ESP32 ``compiler.cpreprocessor.flags`` adds ``-I{build.source.path}``.

    That path is unique per example. Hashing it into the core generation forced
    every CI sketch to rebuild core instead of reusing master's shared ``core/o``.
    """
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"toolchain")
    sketch_a = tmp_path / "examples" / "Fan"
    sketch_b = tmp_path / "examples" / "OnOff"
    sketch_a.mkdir(parents=True)
    sketch_b.mkdir(parents=True)
    (sketch_a / "Fan.ino").write_text("void setup() {}\n", encoding="utf-8")
    (sketch_b / "OnOff.ino").write_text("void setup() {}\n", encoding="utf-8")
    lib = _library(tmp_path / "Matter", "Matter")

    def expanded(sketch: Path) -> dict[str, str]:
        recipe = (
            f'"{compiler}" -I"{sketch}" {{includes}} -c '
            '"{source_file}" -o "{object_file}"'
        )
        return {
            "recipe.c.o.pattern": recipe,
            "recipe.cpp.o.pattern": recipe,
        }

    common = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
        platform_root=tmp_path,
        platform_includes=f'-I"{core}" -I"{variant}"',
        library_includes={lib.root: f'-I"{lib.root / "src"}"'},
        library_dependencies={lib.root: [lib]},
    )
    first = maybe_refresh_object_cache(
        sketch_dir=sketch_a, expanded=expanded(sketch_a), **common
    )
    second = maybe_refresh_object_cache(
        sketch_dir=sketch_b, expanded=expanded(sketch_b), **common
    )
    assert first.platform_dir == second.platform_dir
    assert first.library_dir(lib) == second.library_dir(lib)


def test_unreadable_generation_input_fails_without_deleting_prior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    artifact = first.platform_dir / "core" / "o" / "live.o"
    artifact.write_bytes(b"prior")
    blocked = core / "main.h"
    stat = blocked.stat()
    os.utime(
        blocked,
        ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000),
    )
    original = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == blocked:
            raise PermissionError("injected")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(PermissionError):
        maybe_refresh_object_cache(
            cache,
            build_dir=build,
            core_path=core,
            variant_path=variant,
            libraries=[],
        )
    assert artifact.read_bytes() == b"prior"


@pytest.mark.parametrize(
    "name", ["macros.inc", "templates.ipp", "types.tcc", "Kconfig"]
)
def test_platform_auxiliary_compile_inputs_select_new_generation(
    tmp_path: Path, name: str
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    candidate = core / name
    candidate.write_text("before\n", encoding="utf-8")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    candidate.write_text("after\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    assert second.platform_dir != first.platform_dir


@pytest.mark.parametrize("name", ["detail.inc", "detail.ipp", "detail.tcc", "config"])
def test_library_auxiliary_compile_inputs_select_new_generation(
    tmp_path: Path, name: str
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "Lib", "Lib")
    candidate = lib.root / "src" / name
    candidate.write_text("before\n", encoding="utf-8")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    candidate.write_text("after\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    assert second.library_dir(lib) != first.library_dir(lib)


def test_library_examples_remain_excluded_from_generation(tmp_path: Path) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "Lib", "Lib")
    example = lib.root / "examples" / "Demo" / "data.inc"
    example.parent.mkdir(parents=True)
    example.write_text("before\n", encoding="utf-8")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    example.write_text("after\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    assert second.library_dir(lib) == first.library_dir(lib)


def test_absolute_tmp_component_does_not_exclude_library(tmp_path: Path) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "tmp" / "Installed" / "Lib", "Lib")
    candidate = lib.root / "src" / "config.inc"
    candidate.write_text("before\n", encoding="utf-8")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    candidate.write_text("after\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    assert second.library_dir(lib) != first.library_dir(lib)


def test_compiled_source_under_src_tests_is_fingerprinted(tmp_path: Path) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "Lib", "Lib")
    compiled = lib.root / "src" / "tests" / "compiled.cpp"
    compiled.parent.mkdir()
    compiled.write_text("int value = 1;\n", encoding="utf-8")
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    compiled.write_text("int value = 2;\n", encoding="utf-8")
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    assert second.library_dir(lib) != first.library_dir(lib)


def test_nested_response_file_content_selects_new_generation(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    outer = build / "outer.rsp"
    nested = build / "nested.rsp"
    outer.write_text("@nested.rsp\n", encoding="utf-8")
    nested.write_text("-DVALUE=1\n", encoding="utf-8")
    expanded = {
        "recipe.c.o.pattern": (
            f'"{compiler}" "@{outer}" -c "{{source_file}}" -o "{{object_file}}"'
        )
    }
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
        expanded=expanded,
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(**args)
    nested.write_text("-DVALUE=2\n", encoding="utf-8")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir


@pytest.mark.parametrize(
    "argument",
    [
        '-include "{file}"',
        '-imacros "{file}"',
        '-specs="{file}"',
        '-fplugin="{file}"',
        '"{file}"',
    ],
)
def test_direct_file_valued_compiler_inputs_are_fingerprinted(
    tmp_path: Path, argument: str
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "python-wrapper"
    compiler.write_bytes(b"wrapper")
    direct = tmp_path / "direct-input"
    direct.write_text("before\n", encoding="utf-8")
    expanded = {
        "recipe.c.o.pattern": (
            f'"{compiler}" {argument.format(file=direct)} '
            '-c "{source_file}" -o "{object_file}"'
        )
    }
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
        expanded=expanded,
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(**args)
    direct.write_text("after\n", encoding="utf-8")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir


def test_compiler_B_prefix_tree_is_fingerprinted(tmp_path: Path) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    prefix = tmp_path / "tool-prefix"
    prefix.mkdir()
    script = prefix / "cc1"
    script.write_text("before\n", encoding="utf-8")
    expanded = {
        "recipe.c.o.pattern": (
            f'"{compiler}" -B"{prefix}" -c "{{source_file}}" -o "{{object_file}}"'
        )
    }
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
        expanded=expanded,
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(**args)
    script.write_text("after\n", encoding="utf-8")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir


def test_output_affecting_environment_and_compiler_path_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    compiler_path = tmp_path / "compiler-path"
    compiler_path.mkdir()
    helper = compiler_path / "cc1"
    helper.write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("COMPILER_PATH", str(compiler_path))
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1")
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
        expanded=_expanded(compiler),
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(**args)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "2")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir
    helper.write_text("after\n", encoding="utf-8")
    third = maybe_refresh_object_cache(**args)
    assert third.platform_dir != second.platform_dir


def test_cpath_inside_unrelated_linked_library_affects_library_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    root = _library(tmp_path / "Root", "Root")
    unrelated = _library(tmp_path / "Unrelated", "Unrelated")
    cpath_file = unrelated.root / "src" / "forced.inc"
    cpath_file.write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("CPATH", str(unrelated.root / "src"))
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[root, unrelated],
        expanded=_expanded(compiler),
        platform_root=tmp_path,
        library_includes={
            root.root: "-I/root",
            unrelated.root: "-I/unrelated",
        },
        library_dependencies={
            root.root: [root],
            unrelated.root: [unrelated],
        },
    )
    first = maybe_refresh_object_cache(**args)
    cpath_file.write_text("after\n", encoding="utf-8")
    second = maybe_refresh_object_cache(**args)
    assert second.library_dir(root) != first.library_dir(root)


def test_new_and_deleted_tree_files_change_generation_and_prune_manifest(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    include = tmp_path / "include"
    include.mkdir()
    one = include / "one.inc"
    one.write_text("one\n", encoding="utf-8")
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    expanded = {
        "recipe.c.o.pattern": (
            f'"{compiler}" -I"{include}" -c "{{source_file}}" -o "{{object_file}}"'
        )
    }
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
        expanded=expanded,
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(**args)
    two = include / "two.inc"
    two.write_text("two\n", encoding="utf-8")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir
    one.unlink()
    third = maybe_refresh_object_cache(**args)
    assert third.platform_dir != second.platform_dir

    manifests = list((cache / ".acmake_fingerprints").glob("tree-*.json"))
    assert manifests
    bodies = [manifest.read_text(encoding="utf-8") for manifest in manifests]
    assert str(two.resolve()) in "\n".join(bodies)
    assert str(one.resolve()) not in "\n".join(bodies)


def test_explicit_and_environment_include_roots_are_fingerprinted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    explicit = tmp_path / "explicit-include"
    environment = tmp_path / "environment-include"
    explicit.mkdir()
    environment.mkdir()
    explicit_header = explicit / "detail.inc"
    environment_header = environment / "environment"
    explicit_header.write_text("one\n", encoding="utf-8")
    environment_header.write_text("one\n", encoding="utf-8")
    monkeypatch.setenv("CPATH", str(environment))
    expanded = {
        "recipe.c.o.pattern": (
            f'"{compiler}" -I"{explicit}" -c "{{source_file}}" -o "{{object_file}}"'
        )
    }
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
        expanded=expanded,
        platform_root=tmp_path,
    )
    first = maybe_refresh_object_cache(**args)
    explicit_header.write_text("two\n", encoding="utf-8")
    second = maybe_refresh_object_cache(**args)
    assert second.platform_dir != first.platform_dir
    environment_header.write_text("two\n", encoding="utf-8")
    third = maybe_refresh_object_cache(**args)
    assert third.platform_dir != second.platform_dir


def test_library_digest_reads_are_memoized_per_prepare_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    shared = _library(tmp_path / "Shared", "Shared")
    roots = [_library(tmp_path / f"Root{index}", f"Root{index}") for index in range(20)]
    libraries = [*roots, shared]
    counts: dict[Path, int] = {}
    original = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        resolved = path.resolve()
        counts[resolved] = counts.get(resolved, 0) + 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    started = time.perf_counter()
    maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=libraries,
        expanded=_expanded(compiler),
        platform_root=tmp_path,
        library_includes={
            **{lib.root: f"-I{lib.root / 'src'}" for lib in roots},
            shared.root: f"-I{shared.root / 'src'}",
        },
        library_dependencies={
            **{lib.root: [lib, shared] for lib in roots},
            shared.root: [shared],
        },
    )
    elapsed = time.perf_counter() - started
    compile_inputs = [
        path
        for path in counts
        if any(path.is_relative_to(lib.root) for lib in libraries)
    ]
    assert compile_inputs
    assert max(counts[path] for path in compile_inputs) == 1
    assert counts[compiler.resolve()] == 1
    assert elapsed < 2.0


def test_persistent_manifest_reuses_unchanged_content_across_invocations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    lib = _library(tmp_path / "Lib", "Lib")
    for index in range(64):
        (lib.root / "src" / f"generated-{index}.inc").write_bytes(bytes([index]) * 4096)
    args = dict(
        cache_root=cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[lib],
    )
    cold_started = time.perf_counter()
    first = maybe_refresh_object_cache(**args)
    cold_elapsed = time.perf_counter() - cold_started

    reads: list[Path] = []
    original = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        reads.append(path.resolve())
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    warm_started = time.perf_counter()
    second = maybe_refresh_object_cache(**args)
    warm_elapsed = time.perf_counter() - warm_started
    tracked_roots = (core.resolve(), variant.resolve(), lib.root.resolve())
    tracked_reads = [
        path
        for path in reads
        if any(path.is_relative_to(root) for root in tracked_roots)
    ]
    assert second.platform_dir == first.platform_dir
    assert second.library_dir(lib) == first.library_dir(lib)
    assert tracked_reads == []
    assert warm_elapsed < cold_elapsed


def test_persistent_manifest_content_change_invalidates_with_restored_mtime(
    tmp_path: Path,
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    candidate = core / "main.h"
    stat = candidate.stat()
    candidate.write_text("// changed bytes\n", encoding="utf-8")
    os.utime(candidate, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    assert second.platform_dir != first.platform_dir


def test_persistent_manifest_mtime_touch_recomputes_same_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, build, core, variant = _inputs(tmp_path)
    first = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    candidate = core / "main.h"
    stat = candidate.stat()
    os.utime(
        candidate,
        ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000),
    )
    reads = 0
    original = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        nonlocal reads
        if path.resolve() == candidate.resolve():
            reads += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    second = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[],
    )
    assert reads == 1
    assert second.platform_dir == first.platform_dir
