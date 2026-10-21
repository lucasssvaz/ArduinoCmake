"""Concurrency-safe shared core archive publication."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from acmake.cache_archive import archive_stamp_path, main as cache_archive_main


def _args(archive: Path, objects: list[Path]) -> list[str]:
    return [
        str(archive),
        *[str(path) for path in objects],
        "--",
        "ar",
        "rcs",
        str(archive),
        *[str(path) for path in objects],
    ]


def _fake_archiver(payload: bytes, *, returncode: int = 0, delay: float = 0):
    def run(argv: list[str], **_kw):
        if delay:
            time.sleep(delay)
        Path(argv[2]).write_bytes(payload)
        return mock.Mock(returncode=returncode)

    return run


def test_archive_publishes_and_warm_call_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "cache with spaces" / "core.a"
    archive.parent.mkdir()
    objects = [tmp_path / "one.o", tmp_path / "two.o"]
    for index, path in enumerate(objects):
        path.write_bytes(f"object-{index}".encode())
    run = mock.Mock(side_effect=_fake_archiver(b"!<arch>\nvalid"))
    monkeypatch.setattr("acmake.cache_archive.subprocess.run", run)

    assert cache_archive_main(_args(archive, objects)) == 0
    assert archive.read_bytes() == b"!<arch>\nvalid"
    assert archive_stamp_path(archive).is_file()
    assert cache_archive_main(_args(archive, objects)) == 0
    assert run.call_count == 1


def test_archive_mtime_only_change_keeps_generation_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "core.a"
    obj = tmp_path / "one.o"
    obj.write_bytes(b"same")
    run = mock.Mock(side_effect=_fake_archiver(b"archive"))
    monkeypatch.setattr("acmake.cache_archive.subprocess.run", run)
    assert cache_archive_main(_args(archive, [obj])) == 0
    before = archive.stat()
    stat = obj.stat()
    os.utime(obj, (stat.st_atime + 100, stat.st_mtime + 100))
    assert cache_archive_main(_args(archive, [obj])) == 0
    assert run.call_count == 1
    assert archive.stat().st_ino == before.st_ino
    assert archive.stat().st_mtime_ns == before.st_mtime_ns


def test_existing_archive_skips_without_reading_immutable_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "core.a"
    obj = tmp_path / "one.o"
    obj.write_bytes(b"before")
    run = mock.Mock(side_effect=_fake_archiver(b"archive"))
    monkeypatch.setattr("acmake.cache_archive.subprocess.run", run)
    assert cache_archive_main(_args(archive, [obj])) == 0
    obj.write_bytes(b"after")
    monkeypatch.setattr(
        Path,
        "read_bytes",
        mock.Mock(side_effect=AssertionError("warm hit read object bytes")),
    )
    assert cache_archive_main(_args(archive, [obj])) == 0
    assert run.call_count == 1


def test_archive_failure_leaves_generation_unpublished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "core.a"
    obj = tmp_path / "one.o"
    obj.write_bytes(b"one")
    monkeypatch.setattr(
        "acmake.cache_archive.subprocess.run",
        _fake_archiver(b"partial", returncode=7),
    )
    assert cache_archive_main(_args(archive, [obj])) == 7
    assert not archive.exists()
    assert not archive_stamp_path(archive).exists()
    assert not list(tmp_path.glob(".core.a.tmp-*"))


def test_archive_check_after_lock_runs_archiver_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "core.a"
    obj = tmp_path / "one.o"
    obj.write_bytes(b"one")
    run = mock.Mock(side_effect=_fake_archiver(b"archive", delay=0.05))
    monkeypatch.setattr("acmake.cache_archive.subprocess.run", run)
    args = _args(archive, [obj])
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(cache_archive_main(args)))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert results == [0] * 8
    assert run.call_count == 1


def test_archive_missing_input_fails_without_touching_prior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "core.a"
    run = mock.Mock()
    monkeypatch.setattr("acmake.cache_archive.subprocess.run", run)
    assert cache_archive_main(_args(archive, [tmp_path / "missing.o"])) == 1
    assert not archive.exists()
    run.assert_not_called()


def test_archive_replace_exception_leaves_generation_unpublished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "core.a"
    obj = tmp_path / "one.o"
    obj.write_bytes(b"object")
    monkeypatch.setattr(
        "acmake.cache_archive.subprocess.run", _fake_archiver(b"new-archive")
    )
    monkeypatch.setattr(
        "acmake.cache_archive.atomic_replace",
        mock.Mock(side_effect=PermissionError("injected")),
    )
    with pytest.raises(PermissionError):
        cache_archive_main(_args(archive, [obj]))
    assert not archive.exists()
    assert not list(tmp_path.glob(".core.a.tmp-*"))
