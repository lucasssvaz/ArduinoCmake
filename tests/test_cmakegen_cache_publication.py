"""CMake generation for concurrency-safe cache wrappers."""

from pathlib import Path

from acmake.build import BuildPlan, SourceObject
from acmake.cmakegen import write_cmake
from acmake.fqbn import FQBN


def _plan(tmp_path: Path, *, cached: bool) -> BuildPlan:
    build = tmp_path / ("cached build" if cached else "serial build")
    build.mkdir()
    sketch = tmp_path / "Sketch"
    sketch.mkdir(exist_ok=True)
    source = tmp_path / "core source.c"
    source.write_text("int core(void) { return 1; }\n", encoding="utf-8")
    if cached:
        cache = tmp_path / "shared cache" / "generation"
        obj = cache / "core" / "o" / "core source.c.o"
        archive = cache / "core" / "core.a"
    else:
        cache = None
        obj = build / "objects" / "core source.c.o"
        archive = build / "core.a"
    obj.parent.mkdir(parents=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    dep = build / ".acmake_deps" / "core.d"
    dep.parent.mkdir()
    elf = build / "Sketch.ino.elf"
    return BuildPlan(
        fqbn=FQBN.parse("arduino:avr:uno"),
        platform_root=tmp_path,
        sketch_dir=sketch,
        build_dir=build,
        expanded={
            "recipe.c.o.pattern": 'cc -c "{source_file}" -o "{object_file}"',
            "recipe.c.combine.pattern": f'ld -o "{elf}" "{{archive_file_path}}"',
            "compiler.path": "",
            "compiler.ar.cmd": "ar",
        },
        sources=[
            SourceObject(
                source=source,
                object_path=obj,
                dep_path=dep,
                kind="core",
            )
        ],
        archive_path=archive,
        elf_path=elf,
        object_cache_dir=cache,
    )


def test_cached_cmake_uses_compile_and_archive_wrappers(tmp_path: Path) -> None:
    plan = _plan(tmp_path, cached=True)
    text = write_cmake(plan).read_text(encoding="utf-8")
    assert "cache_compile.py" in text
    assert "cache_archive.py" in text
    assert str(plan.archive_path).replace("\\", "/") in text
    assert "--" in text


def test_cache_disabled_cmake_keeps_direct_serial_commands(tmp_path: Path) -> None:
    plan = _plan(tmp_path, cached=False)
    text = write_cmake(plan).read_text(encoding="utf-8")
    assert "cache_compile.py" not in text
    assert "cache_archive.py" not in text
    assert "ar" in text
    assert "rcs" in text


def test_cached_core_command_excludes_unrelated_library_includes(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, cached=True)
    core = tmp_path / "core"
    variant = tmp_path / "variant"
    core.mkdir()
    variant.mkdir()
    plan.expanded.update(
        {
            "build.core.path": str(core),
            "build.variant.path": str(variant),
            "includes": (
                f'-I"{core}" -I"{variant}" -I"/unrelated/library/include"'
            ),
            "recipe.c.o.pattern": (
                'cc {includes} -c "{source_file}" -o "{object_file}"'
            ),
        }
    )
    text = write_cmake(plan).read_text(encoding="utf-8")
    assert str(core).replace("\\", "/") in text
    assert str(variant).replace("\\", "/") in text
    assert "/unrelated/library/include" not in text


