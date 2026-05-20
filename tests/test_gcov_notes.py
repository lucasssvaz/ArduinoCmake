"""collect_gcov_notes: copy .gcno files from object cache into build dir."""

from pathlib import Path

from acmake.build import (
    BuildPlan,
    SourceObject,
    _has_coverage_flags,
    collect_gcov_notes,
)
from acmake.fqbn import FQBN


def _make_plan(
    tmp_path: Path,
    sources: list[SourceObject],
    *,
    extra_flags: str = "",
) -> BuildPlan:
    bd = tmp_path / "build"
    bd.mkdir(parents=True, exist_ok=True)
    expanded = {}
    if extra_flags:
        expanded["compiler.c.extra_flags"] = extra_flags
        expanded["compiler.cpp.extra_flags"] = extra_flags
    return BuildPlan(
        fqbn=FQBN.parse("espressif:esp32:esp32"),
        platform_root=tmp_path / "platform",
        sketch_dir=tmp_path / "sketch",
        build_dir=bd,
        expanded=expanded,
        sources=sources,
    )


def _so(tmp_path: Path, name: str, kind: str = "core") -> SourceObject:
    """Create a SourceObject.  *name* is the object filename (e.g. ``Esp.cpp.o``)."""
    obj = tmp_path / "cache" / name
    obj.parent.mkdir(parents=True, exist_ok=True)
    obj.write_bytes(b"\x00")
    return SourceObject(
        source=tmp_path / "src" / name,
        object_path=obj,
        dep_path=tmp_path / "deps" / f"{name}.d",
        kind=kind,
    )


def test_has_coverage_flags_detects_c_flags() -> None:
    assert _has_coverage_flags({"compiler.c.extra_flags": "--coverage -DCOVERAGE_ENABLED"})


def test_has_coverage_flags_detects_cpp_flags() -> None:
    assert _has_coverage_flags({"compiler.cpp.extra_flags": "--coverage"})


def test_has_coverage_flags_false_when_absent() -> None:
    assert not _has_coverage_flags({})
    assert not _has_coverage_flags({"compiler.c.extra_flags": "-Wall"})


def test_collect_gcov_notes_noop_without_coverage(tmp_path: Path) -> None:
    so = _so(tmp_path, "main.cpp.o", "sketch")
    gcno = so.object_path.with_name("main.cpp.gcno")
    gcno.write_bytes(b"gcno-data")
    plan = _make_plan(tmp_path, [so], extra_flags="")
    assert collect_gcov_notes(plan) == []
    assert not (plan.build_dir / "gcov").exists()


def test_collect_gcov_notes_copies_core_gcno(tmp_path: Path) -> None:
    so = _so(tmp_path, "HardwareSerial.cpp.o", "core")
    gcno = so.object_path.with_name("HardwareSerial.cpp.gcno")
    gcno.write_bytes(b"gcno-core-data")
    plan = _make_plan(tmp_path, [so], extra_flags="--coverage -DCOVERAGE_ENABLED")

    copied = collect_gcov_notes(plan)

    assert len(copied) == 1
    dest = plan.build_dir / "gcov" / "core" / "HardwareSerial.cpp.gcno"
    assert dest in copied
    assert dest.read_bytes() == b"gcno-core-data"


def test_collect_gcov_notes_copies_multiple_kinds(tmp_path: Path) -> None:
    core_so = _so(tmp_path, "Esp.cpp.o", "core")
    core_so.object_path.with_name("Esp.cpp.gcno").write_bytes(b"core")

    sketch_so = _so(tmp_path, "sketch.cpp.o", "sketch")
    sketch_so.object_path.with_name("sketch.cpp.gcno").write_bytes(b"sketch")

    lib_so = _so(tmp_path, "WiFi.cpp.o", "lib")
    lib_so.object_path.with_name("WiFi.cpp.gcno").write_bytes(b"lib")

    plan = _make_plan(
        tmp_path, [core_so, sketch_so, lib_so], extra_flags="--coverage"
    )
    copied = collect_gcov_notes(plan)

    assert len(copied) == 3
    gcov_dir = plan.build_dir / "gcov"
    assert (gcov_dir / "core" / "Esp.cpp.gcno").read_bytes() == b"core"
    assert (gcov_dir / "sketch" / "sketch.cpp.gcno").read_bytes() == b"sketch"
    assert (gcov_dir / "lib" / "WiFi.cpp.gcno").read_bytes() == b"lib"


def test_collect_gcov_notes_skips_missing_gcno(tmp_path: Path) -> None:
    so = _so(tmp_path, "missing.cpp.o", "core")
    plan = _make_plan(tmp_path, [so], extra_flags="--coverage")

    copied = collect_gcov_notes(plan)
    assert copied == []


def test_collect_gcov_notes_creates_gcov_dir(tmp_path: Path) -> None:
    so = _so(tmp_path, "main.cpp.o", "core")
    so.object_path.with_name("main.cpp.gcno").write_bytes(b"data")
    plan = _make_plan(tmp_path, [so], extra_flags="--coverage")

    gcov_dir = plan.build_dir / "gcov"
    assert not gcov_dir.exists()
    collect_gcov_notes(plan)
    assert gcov_dir.is_dir()


def test_collect_gcov_notes_overwrites_stale(tmp_path: Path) -> None:
    """A second call overwrites .gcno files from a previous build."""
    so = _so(tmp_path, "main.cpp.o", "core")
    gcno = so.object_path.with_name("main.cpp.gcno")
    plan = _make_plan(tmp_path, [so], extra_flags="--coverage")

    gcno.write_bytes(b"v1")
    collect_gcov_notes(plan)
    dest = plan.build_dir / "gcov" / "core" / "main.cpp.gcno"
    assert dest.read_bytes() == b"v1"

    gcno.write_bytes(b"v2")
    collect_gcov_notes(plan)
    assert dest.read_bytes() == b"v2"


def test_collect_gcov_notes_removes_stale_files(tmp_path: Path) -> None:
    """Files from a previous build that are no longer in the plan are removed."""
    old_so = _so(tmp_path, "old_module.cpp.o", "core")
    old_so.object_path.with_name("old_module.cpp.gcno").write_bytes(b"old")
    plan_old = _make_plan(tmp_path, [old_so], extra_flags="--coverage")
    collect_gcov_notes(plan_old)
    stale = plan_old.build_dir / "gcov" / "core" / "old_module.cpp.gcno"
    assert stale.exists()

    new_so = _so(tmp_path, "new_module.cpp.o", "core")
    new_so.object_path.with_name("new_module.cpp.gcno").write_bytes(b"new")
    plan_new = _make_plan(tmp_path, [new_so], extra_flags="--coverage")
    collect_gcov_notes(plan_new)

    assert not stale.exists(), "stale .gcno should have been removed"
    fresh = plan_new.build_dir / "gcov" / "core" / "new_module.cpp.gcno"
    assert fresh.read_bytes() == b"new"


def test_collect_gcov_notes_no_name_collision(tmp_path: Path) -> None:
    """Files with the same basename in different kinds are kept separate."""
    core_so = _so(tmp_path, "IPAddress.cpp.o", "core")
    core_so.object_path.with_name("IPAddress.cpp.gcno").write_bytes(b"core-ver")

    lib_so = SourceObject(
        source=tmp_path / "lib_src" / "IPAddress.cpp",
        object_path=tmp_path / "lib_cache" / "IPAddress.cpp.o",
        dep_path=tmp_path / "deps" / "IPAddress.cpp.o.d",
        kind="lib",
    )
    lib_so.object_path.parent.mkdir(parents=True, exist_ok=True)
    lib_so.object_path.write_bytes(b"\x00")
    lib_so.object_path.with_name("IPAddress.cpp.gcno").write_bytes(b"lib-ver")

    plan = _make_plan(
        tmp_path, [core_so, lib_so], extra_flags="--coverage"
    )
    copied = collect_gcov_notes(plan)

    assert len(copied) == 2
    gcov_dir = plan.build_dir / "gcov"
    assert (gcov_dir / "core" / "IPAddress.cpp.gcno").read_bytes() == b"core-ver"
    assert (gcov_dir / "lib" / "IPAddress.cpp.gcno").read_bytes() == b"lib-ver"
