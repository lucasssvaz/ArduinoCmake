"""Retention and explicit garbage collection for immutable cache generations."""

from __future__ import annotations

import math
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

_BUCKET_RE = re.compile(r"^[0-9a-f]{32}$")
_GENERATION_RE = re.compile(r"^[0-9a-f]{64}$")
_LAST_USED = ".acmake_last_used"
_TOUCH_INTERVAL_NS = 24 * 60 * 60 * 1_000_000_000


@dataclass(frozen=True)
class CachePruneResult:
    """Summary of cache directories removed or selected by a dry run."""

    directories: int = 0
    bytes: int = 0

    def __add__(self, other: CachePruneResult) -> CachePruneResult:
        return CachePruneResult(
            self.directories + other.directories,
            self.bytes + other.bytes,
        )


def mark_cache_path_used(path: Path, *, now_ns: int | None = None) -> None:
    """Record cache use at most once per day without changing cached artifacts."""
    path = Path(path)
    if not path.is_dir():
        return
    now_ns = time.time_ns() if now_ns is None else now_ns
    marker = path / _LAST_USED
    try:
        if marker.is_file() and now_ns - marker.stat().st_mtime_ns < _TOUCH_INTERVAL_NS:
            return
        marker.touch(exist_ok=True)
        os.utime(marker, ns=(now_ns, now_ns))
    except OSError:
        # Cache reuse must never fail just because retention metadata cannot be updated.
        return


def _last_used_ns(path: Path) -> int:
    marker = path / _LAST_USED
    try:
        if marker.is_file():
            return marker.stat().st_mtime_ns
        newest = path.stat().st_mtime_ns
    except OSError:
        return 0
    try:
        for child in path.rglob("*"):
            try:
                newest = max(newest, child.stat().st_mtime_ns)
            except OSError:
                continue
    except OSError:
        pass
    return newest


def _directory_size(path: Path) -> int:
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _remove(path: Path, *, dry_run: bool) -> CachePruneResult:
    size = _directory_size(path)
    if not dry_run:
        shutil.rmtree(path)
    return CachePruneResult(1, size)


def _generation_dirs(parent: Path) -> list[Path]:
    if not parent.is_dir():
        return []
    return [
        path
        for path in parent.iterdir()
        if path.is_dir() and _GENERATION_RE.fullmatch(path.name)
    ]


def _expired_generation_dirs(
    parent: Path,
    *,
    cutoff_ns: int,
    keep: int,
) -> list[Path]:
    entries = sorted(
        ((_last_used_ns(path), path) for path in _generation_dirs(parent)),
        key=lambda item: (item[0], item[1].name),
        reverse=True,
    )
    protected = {path for _, path in entries[:keep]}
    return [
        path
        for last_used, path in entries
        if path not in protected and last_used < cutoff_ns
    ]


def _prune_generation_group(
    parent: Path,
    *,
    cutoff_ns: int,
    keep: int,
    dry_run: bool,
) -> CachePruneResult:
    result = CachePruneResult()
    for path in _expired_generation_dirs(
        parent,
        cutoff_ns=cutoff_ns,
        keep=keep,
    ):
        result += _remove(path, dry_run=dry_run)
    return result


def prune_object_cache(
    root: Path,
    *,
    max_age_days: float = 30,
    keep: int = 2,
    dry_run: bool = False,
    now_ns: int | None = None,
) -> CachePruneResult:
    """Remove expired immutable generations.

    Buckets unused for ``max_age_days`` are removed in full. In active buckets,
    old generations are removed while the newest ``keep`` entries in each core,
    library-platform, and individual-library group are retained.

    This operation is intentionally explicit and must not run during builds.
    """
    if not math.isfinite(max_age_days) or max_age_days < 0:
        raise ValueError("max_age_days must be finite and non-negative")
    if keep < 0:
        raise ValueError("keep must be non-negative")
    root = Path(root)
    if not root.is_dir():
        return CachePruneResult()
    now_ns = time.time_ns() if now_ns is None else now_ns
    cutoff_ns = now_ns - int(max_age_days * 24 * 60 * 60 * 1_000_000_000)
    buckets = [
        path
        for path in root.iterdir()
        if path.is_dir() and _BUCKET_RE.fullmatch(path.name)
    ]
    result = CachePruneResult()
    for bucket in buckets:
        if _last_used_ns(bucket) < cutoff_ns:
            result += _remove(bucket, dry_run=dry_run)
            continue

        result += _prune_generation_group(
            bucket / "core_generations",
            cutoff_ns=cutoff_ns,
            keep=keep,
            dry_run=dry_run,
        )
        library_generations = bucket / "library_generations"
        expired_platforms = set(
            _expired_generation_dirs(
                library_generations,
                cutoff_ns=cutoff_ns,
                keep=keep,
            )
        )
        for path in expired_platforms:
            result += _remove(path, dry_run=dry_run)
        for platform_generation in _generation_dirs(library_generations):
            if platform_generation in expired_platforms:
                continue
            if not platform_generation.exists():
                continue
            library_root = platform_generation / "lib"
            if not library_root.is_dir():
                continue
            for bundle in library_root.iterdir():
                result += _prune_generation_group(
                    bundle / "generations",
                    cutoff_ns=cutoff_ns,
                    keep=keep,
                    dry_run=dry_run,
                )
    return result
