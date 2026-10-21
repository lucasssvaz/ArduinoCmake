"""Persistent content fingerprint manifest correctness and concurrency."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

import acmake.fingerprint_cache as fingerprint_cache
from acmake.fingerprint_cache import (
    ContentFingerprintCache,
    ShardedFingerprintCache,
)


def test_interleaved_writers_merge_manifest_entries(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    one = tmp_path / "one.inc"
    two = tmp_path / "two.inc"
    one.write_bytes(b"one")
    two.write_bytes(b"two")

    first = ContentFingerprintCache(manifest)
    second = ContentFingerprintCache(manifest)
    first.digest(one)
    second.digest(two)
    first.flush()
    second.flush()

    body = json.loads(manifest.read_text(encoding="utf-8"))
    assert str(one.resolve()) in body["files"]
    assert str(two.resolve()) in body["files"]


def test_corrupt_manifest_recovers_atomically(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")
    source = tmp_path / "source"
    source.write_bytes(b"content")
    cache = ContentFingerprintCache(manifest)
    expected = cache.digest(source)
    cache.flush()
    loaded = ContentFingerprintCache(manifest)
    assert loaded.digest(source) == expected


def test_mocked_windows_never_reuses_persistent_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fingerprint_cache, "_IS_WINDOWS", True)
    manifest = tmp_path / "manifest.json"
    source = tmp_path / "source"
    source.write_bytes(b"one")
    stat = source.stat()
    first = ContentFingerprintCache(manifest).digest(source)
    source.write_bytes(b"two")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second_cache = ContentFingerprintCache(manifest)
    second = second_cache.digest(source)
    second_cache.flush()
    assert second != first
    assert not manifest.exists()


def test_unreliable_coarse_identity_falls_back_to_content_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fingerprint_cache, "_stat_identity", lambda _path: None)
    manifest = tmp_path / "manifest.json"
    source = tmp_path / "source"
    source.write_bytes(b"aaaa")
    first_cache = ContentFingerprintCache(manifest)
    first = first_cache.digest(source)
    first_cache.flush()
    source.write_bytes(b"bbbb")
    second_cache = ContentFingerprintCache(manifest)
    second = second_cache.digest(source)
    assert second != first


def test_shards_use_independent_manifests_and_locks(tmp_path: Path) -> None:
    store = ShardedFingerprintCache(tmp_path / "shards")
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    file_a = root_a / "a.inc"
    file_b = root_b / "b.inc"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")
    barrier = threading.Barrier(2)

    def scan(root: Path, path: Path) -> None:
        barrier.wait()
        store.digest(path, root=root, scope="tree")
        store.prune_to(root, "tree", {path})

    threads = [
        threading.Thread(target=scan, args=(root_a, file_a)),
        threading.Thread(target=scan, args=(root_b, file_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    store.flush()
    manifest_a = store.manifest_for(root_a, "tree")
    manifest_b = store.manifest_for(root_b, "tree")
    assert manifest_a != manifest_b
    assert manifest_a.is_file()
    assert manifest_b.is_file()


def test_successful_shard_scan_prunes_removed_entries(tmp_path: Path) -> None:
    directory = tmp_path / "shards"
    root = tmp_path / "include"
    root.mkdir()
    one = root / "one.inc"
    two = root / "two.inc"
    one.write_bytes(b"one")
    two.write_bytes(b"two")
    first = ShardedFingerprintCache(directory)
    first.digest(one, root=root, scope="tree")
    first.digest(two, root=root, scope="tree")
    first.prune_to(root, "tree", {one, two})
    first.flush()

    two.unlink()
    second = ShardedFingerprintCache(directory)
    second.digest(one, root=root, scope="tree")
    second.prune_to(root, "tree", {one})
    second.flush()
    body = json.loads(
        second.manifest_for(root, "tree").read_text(encoding="utf-8")
    )
    assert str(one.resolve()) in body["files"]
    assert str(two.resolve()) not in body["files"]
