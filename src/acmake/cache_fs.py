"""Small, stdlib-only filesystem primitives for the shared artifact cache."""

from __future__ import annotations

import errno
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

_IS_WINDOWS = os.name == "nt"


def normalized_path_token(value: str | Path) -> str:
    """Compare path tokens without requiring identical separators.

    CMake ``COMMAND`` + ``VERBATIM`` on Windows rewrites ``\\`` to ``/`` in argv,
    while ``pathlib.Path`` prints native backslashes. Exact string equality then
    fails even though both names refer to the same archive or object.
    """
    return os.path.normcase(str(value).replace("\\", "/").rstrip("/"))


def paths_refer_to_same_location(left: str | Path, right: str | Path) -> bool:
    return normalized_path_token(left) == normalized_path_token(right)


def lock_path_for(artifact: Path) -> Path:
    """Return the persistent advisory-lock file used for *artifact*."""
    return artifact.with_name(f".{artifact.name}.lock")


def _lock_file(file: BinaryIO) -> None:
    if _IS_WINDOWS:
        import msvcrt

        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.write(b"\0")
            file.flush()
        while True:
            try:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX)


def _unlock_file(file: BinaryIO) -> None:
    if _IS_WINDOWS:
        import msvcrt

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


@contextmanager
def artifact_lock(artifact: Path) -> Iterator[None]:
    """Hold a cross-process advisory lock scoped to one cache artifact.

    The lock file intentionally remains in place. Ownership is maintained by the
    operating system, so process exit (including termination) releases the lock
    without stale-owner recovery or unsafe lock-file deletion.
    """
    artifact = Path(artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    lock_path = lock_path_for(artifact)
    with lock_path.open("a+b") as file:
        _lock_file(file)
        try:
            yield
        finally:
            _unlock_file(file)


def same_directory_temp_path(target: Path) -> Path:
    """Reserve a unique temporary pathname beside *target* and return it unused."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(
        prefix=f".{target.name}.tmp-", suffix=target.suffix, dir=target.parent
    )
    os.close(fd)
    path = Path(raw)
    path.unlink()
    return path


def atomic_replace(source: Path, target: Path) -> None:
    """Publish *source* as *target* atomically on the target filesystem."""
    os.replace(source, target)


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Atomically replace a small cache metadata file."""
    temp = same_directory_temp_path(target)
    try:
        temp.write_bytes(data)
        atomic_replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write_text(target: Path, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(target, text.encode(encoding))
