"""Concurrency-safe archive wrapper for shared ``core.a`` artifacts."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

if not __package__:  # Direct script: prefer this bundle over installed acmake.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acmake.cache_fs import (
    artifact_lock,
    atomic_replace,
    atomic_write_text,
    paths_refer_to_same_location,
    same_directory_temp_path,
)


def archive_stamp_path(archive: Path) -> Path:
    return archive.with_name(f".{archive.name}.inputs")


def _input_identity(inputs: list[Path]) -> str:
    """Cheap identity for immutable object paths; never reads object bytes."""
    h = hashlib.sha256()
    for path in inputs:
        resolved = path.resolve()
        h.update(str(resolved).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _is_current(archive: Path) -> bool:
    # The generation path already identifies commands and immutable object inputs.
    # Atomic publication means an existing archive is complete and never replaced.
    return archive.is_file()


def _redirect_archive_argument(
    argv: list[str], archive: Path, temporary_archive: Path
) -> list[str] | None:
    out = list(argv)
    found = False
    for i, token in enumerate(out):
        if paths_refer_to_same_location(token, archive):
            out[i] = str(temporary_archive)
            found = True
    return out if found else None


def _remove_abandoned_temporaries(archive: Path) -> None:
    for path in archive.parent.glob(f".{archive.name}.tmp-*"):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    """``python cache_archive.py <archive> <object>... -- <ar> rcs <archive> ...``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 5 or "--" not in args:
        print(
            "usage: python -m acmake.cache_archive <archive> <object>... "
            "-- <archiver> [args...]",
            file=sys.stderr,
        )
        return 2
    sep = args.index("--")
    archive = Path(args[0])
    inputs = [Path(value) for value in args[1:sep]]
    archive_argv = args[sep + 1 :]
    if not inputs or not archive_argv:
        print("acmake.cache_archive: missing input or archiver argv", file=sys.stderr)
        return 2

    stamp = archive_stamp_path(archive)
    if _is_current(archive):
        return 0

    with artifact_lock(archive):
        if _is_current(archive):
            return 0
        missing = [path for path in inputs if not path.is_file()]
        if missing:
            print(
                f"acmake.cache_archive: missing archive input: {missing[0]}",
                file=sys.stderr,
            )
            return 1

        _remove_abandoned_temporaries(archive)
        temporary_archive = same_directory_temp_path(archive)
        redirected = _redirect_archive_argument(
            archive_argv, archive, temporary_archive
        )
        if redirected is None:
            print(
                f"acmake.cache_archive: archiver argv does not name {archive}",
                file=sys.stderr,
            )
            return 2
        try:
            result = subprocess.run(redirected)
            rc = int(result.returncode) if result.returncode is not None else 1
            if rc != 0:
                return rc
            if not temporary_archive.is_file():
                print(
                    "acmake.cache_archive: archiver produced no output: "
                    f"{temporary_archive}",
                    file=sys.stderr,
                )
                return 1
            fingerprint = _input_identity(inputs)
            atomic_replace(temporary_archive, archive)
            atomic_write_text(stamp, fingerprint + "\n", encoding="ascii")
            return 0
        finally:
            temporary_archive.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
