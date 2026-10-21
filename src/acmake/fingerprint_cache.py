"""Persistent, stat-validated content digests for cache preparation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from acmake.cache_fs import artifact_lock, atomic_write_text

_VERSION = 1
_IS_WINDOWS = os.name == "nt"


def _mtime_ns(stat: Any) -> int:
    value = getattr(stat, "st_mtime_ns", None)
    return int(value if value is not None else stat.st_mtime * 1_000_000_000)


def _ctime_ns(stat: Any) -> int:
    value = getattr(stat, "st_ctime_ns", None)
    return int(value if value is not None else stat.st_ctime * 1_000_000_000)


def _stat_identity(path: Path) -> tuple[int, int, int, int, int] | None:
    stat = path.stat()
    if (
        _IS_WINDOWS
        or not hasattr(stat, "st_mtime_ns")
        or not hasattr(stat, "st_ctime_ns")
        or int(getattr(stat, "st_ino", 0)) == 0
    ):
        return None
    mtime_ns = _mtime_ns(stat)
    ctime_ns = _ctime_ns(stat)
    if mtime_ns % 1_000_000_000 == 0 and ctime_ns % 1_000_000_000 == 0:
        return None
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        mtime_ns,
        ctime_ns,
    )


def _read_manifest(path: Path) -> dict[str, dict[str, object]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if raw.get("version") != _VERSION or not isinstance(raw.get("files"), dict):
        return {}
    return raw["files"]


class ContentFingerprintCache:
    """Per-invocation memo plus a concurrency-safe persistent manifest."""

    def __init__(
        self, manifest: Path, *, persistent_reuse: bool = True
    ) -> None:
        self.manifest = manifest
        self.persistent_reuse = persistent_reuse and not _IS_WINDOWS
        if self.persistent_reuse:
            with artifact_lock(manifest):
                self._entries = _read_manifest(manifest)
        else:
            self._entries = {}
        self._memo: dict[Path, tuple[tuple[int, int, int, int, int], str]] = {}
        self._pending: dict[str, dict[str, object]] = {}
        self._prune_keys: set[str] | None = None

    def digest(self, path: Path) -> str:
        resolved = path.resolve()
        identity = _stat_identity(resolved)
        reliable = self.persistent_reuse and identity is not None
        memo = self._memo.get(resolved) if reliable else None
        if memo is not None and memo[0] == identity:
            return memo[1]
        key = str(resolved)
        entry = self._entries.get(key) if reliable else None
        if entry is not None:
            stored_identity = entry.get("identity")
            digest = entry.get("sha256")
            if stored_identity == list(identity) and isinstance(digest, str):
                self._memo[resolved] = (identity, digest)
                return digest

        # A concurrent writer may modify the file while it is read. Retry until
        # the bytes are bracketed by an identical robust stat identity.
        if not reliable:
            return hashlib.sha256(resolved.read_bytes()).hexdigest()

        for _ in range(3):
            before = identity
            data = resolved.read_bytes()
            after = _stat_identity(resolved)
            if before == after:
                digest = hashlib.sha256(data).hexdigest()
                self._memo[resolved] = (after, digest)
                self._pending[key] = {
                    "identity": list(after),
                    "sha256": digest,
                }
                return digest
            identity = after
        raise OSError(f"file changed repeatedly while fingerprinting: {resolved}")

    def prune_to(self, paths: set[Path]) -> None:
        if self.persistent_reuse:
            self._prune_keys = {str(path.resolve()) for path in paths}

    def flush(self) -> None:
        if not self.persistent_reuse:
            return
        if not self._pending and self._prune_keys is None:
            return
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        with artifact_lock(self.manifest):
            entries = _read_manifest(self.manifest)
            if self._prune_keys is not None:
                entries = {
                    key: value
                    for key, value in entries.items()
                    if key in self._prune_keys
                }
            entries.update(self._pending)
            body = json.dumps(
                {"version": _VERSION, "files": entries},
                sort_keys=True,
                separators=(",", ":"),
            )
            atomic_write_text(self.manifest, body + "\n")
        self._entries = entries
        self._pending.clear()
        self._prune_keys = None


class ShardedFingerprintCache:
    """Route independent roots/scopes to separate lock and manifest files."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._caches: dict[tuple[str, Path], ContentFingerprintCache] = {}

    def manifest_for(self, root: Path, scope: str) -> Path:
        resolved = root.resolve()
        key = hashlib.sha256(
            f"{scope}\0{resolved}".encode("utf-8")
        ).hexdigest()[:24]
        return self.directory / f"{scope}-{key}.json"

    def _cache(self, root: Path, scope: str) -> ContentFingerprintCache:
        resolved = root.resolve()
        key = (scope, resolved)
        if key not in self._caches:
            self._caches[key] = ContentFingerprintCache(
                self.manifest_for(resolved, scope)
            )
        return self._caches[key]

    def digest(
        self,
        path: Path,
        *,
        root: Path | None = None,
        scope: str = "direct",
    ) -> str:
        shard_root = (root or path.parent).resolve()
        return self._cache(shard_root, scope).digest(path)

    def prune_to(self, root: Path, scope: str, paths: set[Path]) -> None:
        self._cache(root, scope).prune_to(paths)

    def flush(self) -> None:
        for cache in self._caches.values():
            cache.flush()
