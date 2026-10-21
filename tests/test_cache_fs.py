"""Filesystem primitives used by the concurrent shared cache."""

from __future__ import annotations

import errno
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import acmake.cache_fs as cache_fs
from acmake.cache_fs import (
    artifact_lock,
    atomic_write_text,
    lock_path_for,
    same_directory_temp_path,
)


def test_artifact_lock_serializes_same_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "cache" / "one.o"
    entered: list[int] = []
    release = threading.Event()

    def owner() -> None:
        with artifact_lock(artifact):
            entered.append(1)
            release.wait(2)

    def waiter() -> None:
        with artifact_lock(artifact):
            entered.append(2)

    first = threading.Thread(target=owner)
    second = threading.Thread(target=waiter)
    first.start()
    while not entered:
        time.sleep(0.005)
    second.start()
    time.sleep(0.05)
    assert entered == [1]
    release.set()
    first.join(2)
    second.join(2)
    assert entered == [1, 2]
    assert lock_path_for(artifact).is_file()


def test_artifact_lock_releases_after_exception(tmp_path: Path) -> None:
    artifact = tmp_path / "one.o"
    with pytest.raises(RuntimeError):
        with artifact_lock(artifact):
            raise RuntimeError("injected")
    with artifact_lock(artifact):
        pass


def test_different_artifacts_do_not_share_a_lock(tmp_path: Path) -> None:
    entered: list[str] = []
    release = threading.Event()

    def hold(name: str) -> None:
        with artifact_lock(tmp_path / name):
            entered.append(name)
            release.wait(2)

    threads = [
        threading.Thread(target=hold, args=("a.o",)),
        threading.Thread(target=hold, args=("b.o",)),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 2
    while len(entered) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    release.set()
    for thread in threads:
        thread.join(2)
    assert sorted(entered) == ["a.o", "b.o"]


def test_same_directory_temp_is_unique_and_unpublished(tmp_path: Path) -> None:
    target = tmp_path / "dir with spaces" / "artifact.o"
    one = same_directory_temp_path(target)
    two = same_directory_temp_path(target)
    assert one != two
    assert one.parent == target.parent == two.parent
    assert one.suffix == target.suffix == two.suffix
    assert not one.exists()
    assert not two.exists()


def test_atomic_write_replaces_complete_text(tmp_path: Path) -> None:
    target = tmp_path / "stamp"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert not list(tmp_path.glob(".stamp.tmp-*"))


def test_mocked_windows_lock_retries_contention_and_unlocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    attempts = 0

    def locking(_fd: int, mode: int, _size: int) -> None:
        nonlocal attempts
        calls.append(mode)
        if mode == 1 and attempts == 0:
            attempts += 1
            raise OSError(errno.EACCES, "busy")

    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(cache_fs, "_IS_WINDOWS", True)
    monkeypatch.setattr(cache_fs.time, "sleep", lambda _seconds: None)
    with (tmp_path / "lock").open("a+b") as file:
        cache_fs._lock_file(file)
        cache_fs._unlock_file(file)
    assert calls == [1, 1, 2]
