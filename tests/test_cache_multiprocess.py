"""Repeated multiprocess contention tests for shared cache artifacts."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import acmake.cache_archive
import acmake.cache_compile

COMPILE_WRAPPER = Path(acmake.cache_compile.__file__).resolve()
ARCHIVE_WRAPPER = Path(acmake.cache_archive.__file__).resolve()


def _compiler_script(tmp_path: Path) -> Path:
    script = tmp_path / "fake compiler.py"
    script.write_text(
        """
import pathlib
import sys
import time

args = sys.argv[1:]
if "-o" in args:
    output = pathlib.Path(args[args.index("-o") + 1])
else:
    output = pathlib.Path(next(a[2:] for a in args if a.startswith("-o")))
log = pathlib.Path(args[args.index("--log") + 1])
with log.open("a", encoding="ascii") as stream:
    stream.write("compile\\n")
delay = float(args[args.index("--delay") + 1]) if "--delay" in args else 0.03
time.sleep(delay)
output.write_bytes(b"OBJ\\x00complete\\n")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return script


def _archiver_script(tmp_path: Path) -> Path:
    script = tmp_path / "fake archiver.py"
    script.write_text(
        """
import pathlib
import sys
import time

args = sys.argv[1:]
archive = pathlib.Path(args[1])
log = pathlib.Path(args[args.index("--log") + 1])
with log.open("a", encoding="ascii") as stream:
    stream.write("archive\\n")
time.sleep(0.03)
archive.write_bytes(b"!<arch>\\ncomplete\\n")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return script


def _run_all(commands: list[list[str]]) -> list[subprocess.CompletedProcess[str]]:
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for command in commands
    ]
    results: list[subprocess.CompletedProcess[str]] = []
    for process, command in zip(processes, commands):
        stdout, stderr = process.communicate(timeout=20)
        results.append(
            subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        )
    return results


@pytest.mark.parametrize("contenders", [1, 2, 4, 8, 16, 32])
def test_same_object_multiprocess_contention_compiles_once(
    tmp_path: Path, contenders: int
) -> None:
    compiler = _compiler_script(tmp_path)
    src = tmp_path / "source.cpp"
    obj = tmp_path / "shared output.o"
    log = tmp_path / "compile.log"
    src.write_text("// source\n", encoding="utf-8")
    command = [
        sys.executable,
        str(COMPILE_WRAPPER),
        str(obj),
        str(src),
        "--",
        sys.executable,
        str(compiler),
        "-o",
        str(obj),
        "--log",
        str(log),
    ]
    results = _run_all([command] * contenders)
    assert [result.returncode for result in results] == [0] * contenders
    assert obj.read_bytes() == b"OBJ\0complete\n"
    assert log.read_text(encoding="ascii").splitlines() == ["compile"]
    # A fully warm second wave remains a pure cache hit.
    warm = _run_all([command] * contenders)
    assert [result.returncode for result in warm] == [0] * contenders
    assert log.read_text(encoding="ascii").splitlines() == ["compile"]


@pytest.mark.parametrize("contenders", [1, 2, 4, 8, 16, 32])
def test_same_archive_multiprocess_contention_archives_once(
    tmp_path: Path, contenders: int
) -> None:
    archiver = _archiver_script(tmp_path)
    archive = tmp_path / "shared core.a"
    obj = tmp_path / "core object.o"
    log = tmp_path / "archive.log"
    obj.write_bytes(b"OBJ\0complete\n")
    command = [
        sys.executable,
        str(ARCHIVE_WRAPPER),
        str(archive),
        str(obj),
        "--",
        sys.executable,
        str(archiver),
        "rcs",
        str(archive),
        str(obj),
        "--log",
        str(log),
    ]
    results = _run_all([command] * contenders)
    assert [result.returncode for result in results] == [0] * contenders
    assert archive.read_bytes() == b"!<arch>\ncomplete\n"
    assert log.read_text(encoding="ascii").splitlines() == ["archive"]
    warm = _run_all([command] * contenders)
    assert [result.returncode for result in warm] == [0] * contenders
    assert log.read_text(encoding="ascii").splitlines() == ["archive"]


def test_different_objects_are_not_globally_serialized(tmp_path: Path) -> None:
    compiler = _compiler_script(tmp_path)
    commands: list[list[str]] = []
    for index in range(8):
        src = tmp_path / f"{index}.cpp"
        obj = tmp_path / f"{index}.o"
        log = tmp_path / f"{index}.log"
        src.write_text(f"// {index}\n", encoding="utf-8")
        commands.append(
            [
                sys.executable,
                str(COMPILE_WRAPPER),
                str(obj),
                str(src),
                "--",
                sys.executable,
                str(compiler),
                "-o",
                str(obj),
                "--log",
                str(log),
                "--delay",
                "0.12",
            ]
        )
    started = time.monotonic()
    results = _run_all(commands)
    elapsed = time.monotonic() - started
    assert [result.returncode for result in results] == [0] * len(commands)
    # Eight 120ms compiles would take at least 960ms under a global lock.
    assert elapsed < 0.65


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal semantics")
def test_killed_owner_releases_lock_and_next_writer_recovers(tmp_path: Path) -> None:
    compiler = tmp_path / "interruptible compiler.py"
    marker = tmp_path / "first-started"
    compiler.write_text(
        """
import pathlib
import sys
import time

args = sys.argv[1:]
output = pathlib.Path(args[args.index("-o") + 1])
marker = pathlib.Path(args[args.index("--marker") + 1])
if not marker.exists():
    marker.write_text("started", encoding="ascii")
    time.sleep(30)
else:
    output.write_bytes(b"recovered")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "source.cpp"
    obj = tmp_path / "shared.o"
    src.write_text("// source\n", encoding="utf-8")
    command = [
        sys.executable,
        str(COMPILE_WRAPPER),
        str(obj),
        str(src),
        "--",
        sys.executable,
        str(compiler),
        "-o",
        str(obj),
        "--marker",
        str(marker),
    ]
    owner = subprocess.Popen(command)
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    waiter = subprocess.Popen(command)
    owner.kill()
    owner.wait(timeout=5)
    assert waiter.wait(timeout=10) == 0
    assert obj.read_bytes() == b"recovered"
    assert not list(tmp_path.glob(".shared.o.tmp-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal semantics")
def test_killed_waiter_does_not_disturb_owner_or_future_hits(tmp_path: Path) -> None:
    compiler = tmp_path / "slow compiler.py"
    marker = tmp_path / "owner-started"
    compiler.write_text(
        """
import pathlib
import sys
import time

args = sys.argv[1:]
output = pathlib.Path(args[args.index("-o") + 1])
marker = pathlib.Path(args[args.index("--marker") + 1])
marker.write_text("started", encoding="ascii")
time.sleep(0.3)
output.write_bytes(b"owner-complete")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "source.cpp"
    obj = tmp_path / "shared.o"
    src.write_text("// source\n", encoding="utf-8")
    command = [
        sys.executable,
        str(COMPILE_WRAPPER),
        str(obj),
        str(src),
        "--",
        sys.executable,
        str(compiler),
        "-o",
        str(obj),
        "--marker",
        str(marker),
    ]
    owner = subprocess.Popen(command)
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    waiter = subprocess.Popen(command)
    time.sleep(0.05)
    waiter.kill()
    waiter.wait(timeout=5)
    assert owner.wait(timeout=5) == 0
    assert subprocess.run(command, check=False).returncode == 0
    assert obj.read_bytes() == b"owner-complete"
