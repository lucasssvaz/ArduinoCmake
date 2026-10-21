"""Explicit retention for immutable object-cache generations."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import acmake.cli as cli
from acmake.cache_prune import (
    mark_cache_path_used,
    prune_object_cache,
)
from acmake.cache_invalidate import maybe_refresh_object_cache
from acmake.libraries import Library

DAY_NS = 24 * 60 * 60 * 1_000_000_000


def _set_used(path: Path, timestamp_ns: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    marker = path / ".acmake_last_used"
    marker.touch()
    os.utime(marker, ns=(timestamp_ns, timestamp_ns))


def _generation(
    parent: Path,
    character: str,
    timestamp_ns: int,
    payload: bytes = b"x",
) -> Path:
    path = parent / (character * 64)
    path.mkdir(parents=True)
    (path / "artifact.o").write_bytes(payload)
    _set_used(path, timestamp_ns)
    return path


def _bucket(root: Path, character: str, timestamp_ns: int) -> Path:
    path = root / (character * 32)
    _set_used(path, timestamp_ns)
    return path


def test_mark_cache_path_used_is_throttled(tmp_path: Path) -> None:
    cache = tmp_path / "generation"
    cache.mkdir()
    initial = 100 * DAY_NS
    mark_cache_path_used(cache, now_ns=initial)
    marker = cache / ".acmake_last_used"
    assert marker.stat().st_mtime_ns == initial

    mark_cache_path_used(cache, now_ns=initial + DAY_NS // 2)
    assert marker.stat().st_mtime_ns == initial

    refreshed = initial + 2 * DAY_NS
    mark_cache_path_used(cache, now_ns=refreshed)
    assert marker.stat().st_mtime_ns == refreshed


def test_generation_selection_marks_bucket_and_selected_paths_used(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "acmake_objcache" / ("a" * 32)
    build = tmp_path / "build"
    core = tmp_path / "core"
    variant = tmp_path / "variant"
    library_root = tmp_path / "Example"
    for path in (build, core, variant, library_root):
        path.mkdir(parents=True)
    (library_root / "library.properties").write_text(
        "name=Example\narchitectures=*\n",
        encoding="utf-8",
    )
    source = library_root / "src"
    source.mkdir()
    (source / "Example.h").write_text("// header\n", encoding="utf-8")
    library = Library(
        root=library_root,
        name="Example",
        architectures="*",
        depends=(),
        includes_override=None,
    )

    selected = maybe_refresh_object_cache(
        cache,
        build_dir=build,
        core_path=core,
        variant_path=variant,
        libraries=[library],
    )

    library_platform = (
        cache / "library_generations" / selected.library_platform_fingerprint
    )
    assert (cache / ".acmake_last_used").is_file()
    assert (selected.platform_dir / ".acmake_last_used").is_file()
    assert (library_platform / ".acmake_last_used").is_file()
    assert (selected.library_dir(library) / ".acmake_last_used").is_file()


def test_prune_removes_whole_expired_bucket_and_preserves_unknown_paths(
    tmp_path: Path,
) -> None:
    now = 100 * DAY_NS
    root = tmp_path / "acmake_objcache"
    expired = _bucket(root, "a", now - 40 * DAY_NS)
    (expired / "artifact.o").write_bytes(b"old")
    unknown = root / "not-a-cache-bucket"
    unknown.mkdir()
    (unknown / "keep").write_bytes(b"safe")

    result = prune_object_cache(root, now_ns=now)

    assert result.directories == 1
    assert result.bytes >= 3
    assert not expired.exists()
    assert (unknown / "keep").read_bytes() == b"safe"


def test_prune_active_bucket_keeps_newest_core_generations(tmp_path: Path) -> None:
    now = 100 * DAY_NS
    root = tmp_path / "acmake_objcache"
    bucket = _bucket(root, "a", now)
    parent = bucket / "core_generations"
    oldest = _generation(parent, "1", now - 20 * DAY_NS)
    old = _generation(parent, "2", now - 15 * DAY_NS)
    protected_old = _generation(parent, "3", now - 10 * DAY_NS)
    newest = _generation(parent, "4", now - DAY_NS)

    result = prune_object_cache(
        root,
        max_age_days=7,
        keep=2,
        now_ns=now,
    )

    assert result.directories == 2
    assert not oldest.exists()
    assert not old.exists()
    assert protected_old.exists()
    assert newest.exists()


def test_prune_dry_run_does_not_double_count_expired_platform_tree(
    tmp_path: Path,
) -> None:
    now = 100 * DAY_NS
    root = tmp_path / "acmake_objcache"
    bucket = _bucket(root, "a", now)
    platforms = bucket / "library_generations"
    expired = _generation(platforms, "1", now - 20 * DAY_NS, b"")
    nested = _generation(
        expired / "lib" / "Example_123" / "generations",
        "2",
        now - 20 * DAY_NS,
        b"payload",
    )
    current = _generation(platforms, "3", now - DAY_NS)

    dry_run = prune_object_cache(
        root,
        max_age_days=7,
        keep=1,
        dry_run=True,
        now_ns=now,
    )

    assert dry_run.directories == 1
    assert dry_run.bytes >= len(b"payload")
    assert nested.exists()
    assert current.exists()

    removed = prune_object_cache(
        root,
        max_age_days=7,
        keep=1,
        now_ns=now,
    )
    assert removed == dry_run
    assert not expired.exists()
    assert current.exists()


def test_prune_library_generations_inside_retained_platform(tmp_path: Path) -> None:
    now = 100 * DAY_NS
    root = tmp_path / "acmake_objcache"
    bucket = _bucket(root, "a", now)
    platform = _generation(
        bucket / "library_generations",
        "1",
        now,
        b"",
    )
    generations = platform / "lib" / "Wire_123" / "generations"
    oldest = _generation(generations, "2", now - 20 * DAY_NS)
    old = _generation(generations, "3", now - 10 * DAY_NS)
    newest = _generation(generations, "4", now - DAY_NS)

    result = prune_object_cache(
        root,
        max_age_days=7,
        keep=1,
        now_ns=now,
    )

    assert result.directories == 2
    assert not oldest.exists()
    assert not old.exists()
    assert newest.exists()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_age_days": -1}, "max_age_days"),
        ({"max_age_days": float("nan")}, "max_age_days"),
        ({"max_age_days": float("inf")}, "max_age_days"),
        ({"keep": -1}, "keep"),
    ],
)
def test_prune_rejects_negative_limits(
    tmp_path: Path,
    kwargs: dict[str, float],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        prune_object_cache(tmp_path, **kwargs)


def test_cache_prune_cli_defaults_and_options() -> None:
    parser = cli.build_parser()
    defaults = parser.parse_args(["cache-prune"])
    assert defaults.max_age_days == 30
    assert defaults.keep == 2
    assert defaults.dry_run is False

    configured = parser.parse_args(
        [
            "cache-prune",
            "--max-age-days",
            "7.5",
            "--keep",
            "1",
            "--dry-run",
        ]
    )
    assert configured.max_age_days == 7.5
    assert configured.keep == 1
    assert configured.dry_run is True


def test_cache_prune_cli_dry_run_then_remove(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = time.time_ns()
    root = tmp_path / "acmake_objcache"
    expired = _bucket(root, "a", now - 40 * DAY_NS)
    (expired / "artifact.o").write_bytes(b"old")
    monkeypatch.setattr(cli.tempfile, "gettempdir", lambda: str(tmp_path))
    parser = cli.build_parser()

    dry_run = parser.parse_args(["cache-prune", "--dry-run"])
    assert dry_run.func(dry_run) == 0
    assert "Would remove 1 cache directories" in capsys.readouterr().out
    assert expired.exists()

    prune = parser.parse_args(["cache-prune"])
    assert prune.func(prune) == 0
    assert "Removed 1 cache directories" in capsys.readouterr().out
    assert not expired.exists()
