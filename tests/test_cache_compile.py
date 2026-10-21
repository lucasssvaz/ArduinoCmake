"""Shared-cache compile wrapper (source vs object mtime)."""

import os
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from acmake.cache_compile import main as cache_compile_main


def test_skips_compile_when_object_newer_than_source(tmp_path: Path) -> None:
    src = tmp_path / "a.cpp"
    obj = tmp_path / "a.o"
    src.write_text("//\n", encoding="utf-8")
    obj.write_bytes(b"x")
    t_old = 1_700_000_000
    t_new = t_old + 100
    os.utime(src, (t_old, t_old))
    os.utime(obj, (t_new, t_new))
    argv = [
        str(obj),
        str(src),
        "--",
        sys.executable,
        "-c",
        "import sys; sys.exit(42)",
    ]
    assert cache_compile_main(argv) == 0


def test_source_mtime_change_does_not_rewrite_immutable_object(tmp_path: Path) -> None:
    src = tmp_path / "a.cpp"
    obj = tmp_path / "a.o"
    obj.write_bytes(b"x")
    src.write_text("//\n", encoding="utf-8")
    t_old = 1_700_000_000
    t_new = t_old + 100
    os.utime(obj, (t_old, t_old))
    os.utime(src, (t_new, t_new))
    before = obj.stat()
    argv = [
        str(obj),
        str(src),
        "--",
        sys.executable,
        "-c",
        "import sys; sys.exit(43)",
        "-o",
        str(obj),
    ]
    assert cache_compile_main(argv) == 0
    assert obj.read_bytes() == b"x"
    assert obj.stat().st_ino == before.st_ino
    assert obj.stat().st_mtime_ns == before.st_mtime_ns


def test_runs_compile_when_object_missing(tmp_path: Path) -> None:
    src = tmp_path / "a.cpp"
    obj = tmp_path / "missing.o"
    src.write_text("//\n", encoding="utf-8")
    argv = [
        str(obj),
        str(src),
        "--",
        sys.executable,
        "-c",
        "import sys; sys.exit(44)",
        "-o",
        str(obj),
    ]
    assert cache_compile_main(argv) == 44


def test_strips_cmd_exe_wrapped_argv_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``cmd.exe``-spawned Python can receive ``"@rsp"`` / ``"-I..."``; strip for GCC."""

    captured: list[list[str]] = []

    def fake_run(cargv: list[str], **_kw):
        captured.append(list(cargv))
        Path(cargv[cargv.index("-o") + 1]).write_bytes(b"new")
        return mock.Mock(returncode=0)

    monkeypatch.setattr("acmake.cache_compile.subprocess.run", fake_run)
    src = tmp_path / "a.cpp"
    obj = tmp_path / "a.o"
    src.write_text("//\n", encoding="utf-8")
    argv = [
        str(obj),
        str(src),
        "--",
        "fake-compiler",
        '"@C:/flags/cpp_flags"',
        '"-IC:/include/here"',
        '"C:/src/a.cpp"',
        "-o",
        f'"{obj}"',
    ]
    assert cache_compile_main(argv) == 0
    assert captured[0][:4] == [
        "fake-compiler",
        "@C:/flags/cpp_flags",
        "-IC:/include/here",
        "C:/src/a.cpp",
    ]
    assert captured[0][4] == "-o"
    assert Path(captured[0][5]).parent == tmp_path
    assert Path(captured[0][5]) != obj


@pytest.mark.parametrize("form", ["separate", "combined", "long", "long-equals"])
def test_publishes_all_supported_output_argument_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    src = tmp_path / "source with spaces.cpp"
    obj = tmp_path / "output with spaces.o"
    src.write_text("// source\n", encoding="utf-8")
    seen: list[Path] = []

    def fake_run(argv: list[str], **_kw):
        if "-o" in argv:
            output = Path(argv[argv.index("-o") + 1])
        elif "--output" in argv:
            output = Path(argv[argv.index("--output") + 1])
        else:
            token = next(a for a in argv if a.startswith("-o") or a.startswith("--output="))
            output = Path(token.split("=", 1)[1] if token.startswith("--output=") else token[2:])
        seen.append(output)
        output.write_bytes(b"complete-object")
        return mock.Mock(returncode=0)

    monkeypatch.setattr("acmake.cache_compile.subprocess.run", fake_run)
    output_args = {
        "separate": ["-o", str(obj)],
        "combined": ["-o" + str(obj)],
        "long": ["--output", str(obj)],
        "long-equals": ["--output=" + str(obj)],
    }[form]
    argv = [str(obj), str(src), "--", "compiler", *output_args]
    assert cache_compile_main(argv) == 0
    assert obj.read_bytes() == b"complete-object"
    assert seen[0] != obj
    assert seen[0].parent == obj.parent


def test_compile_failure_leaves_generation_unpublished_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.cpp"
    obj = tmp_path / "a.o"
    src.write_text("// new\n", encoding="utf-8")

    def fake_run(argv: list[str], **_kw):
        Path(argv[argv.index("-o") + 1]).write_bytes(b"partial")
        return mock.Mock(returncode=9)

    monkeypatch.setattr("acmake.cache_compile.subprocess.run", fake_run)
    assert cache_compile_main([str(obj), str(src), "--", "cc", "-o", str(obj)]) == 9
    assert not obj.exists()
    assert not list(tmp_path.glob(".a.o.tmp-*"))


def test_publish_exception_leaves_generation_unpublished_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.cpp"
    obj = tmp_path / "a.o"
    src.write_text("// new\n", encoding="utf-8")

    def fake_run(argv: list[str], **_kw):
        Path(argv[argv.index("-o") + 1]).write_bytes(b"complete")
        return mock.Mock(returncode=0)

    monkeypatch.setattr("acmake.cache_compile.subprocess.run", fake_run)
    monkeypatch.setattr(
        "acmake.cache_compile.atomic_replace",
        mock.Mock(side_effect=PermissionError("injected")),
    )
    with pytest.raises(PermissionError):
        cache_compile_main([str(obj), str(src), "--", "cc", "-o", str(obj)])
    assert not obj.exists()
    assert not list(tmp_path.glob(".a.o.tmp-*"))


def test_check_after_lock_compiles_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "shared.cpp"
    obj = tmp_path / "shared.o"
    src.write_text("// shared\n", encoding="utf-8")
    calls = 0
    calls_lock = threading.Lock()

    def fake_run(argv: list[str], **_kw):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"one-writer")
        return mock.Mock(returncode=0)

    monkeypatch.setattr("acmake.cache_compile.subprocess.run", fake_run)
    args = [str(obj), str(src), "--", "cc", "-o", str(obj)]
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(cache_compile_main(args)))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert results == [0] * 8
    assert calls == 1
    assert obj.read_bytes() == b"one-writer"


def test_partial_temporary_output_is_never_visible_at_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.cpp"
    obj = tmp_path / "a.o"
    src.write_text("// new\n", encoding="utf-8")
    halfway = threading.Event()
    finish = threading.Event()

    def fake_run(argv: list[str], **_kw):
        output = Path(argv[argv.index("-o") + 1])
        output.write_bytes(b"partial")
        halfway.set()
        finish.wait(2)
        output.write_bytes(b"new-complete")
        return mock.Mock(returncode=0)

    monkeypatch.setattr("acmake.cache_compile.subprocess.run", fake_run)
    args = [str(obj), str(src), "--", "cc", "-o", str(obj)]
    result: list[int] = []
    worker = threading.Thread(
        target=lambda: result.append(cache_compile_main(args))
    )
    worker.start()
    assert halfway.wait(2)
    assert not obj.exists()
    finish.set()
    worker.join(2)
    assert result == [0]
    assert obj.read_bytes() == b"new-complete"


def test_missing_output_argument_is_rejected_without_running_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.cpp"
    obj = tmp_path / "a.o"
    src.write_text("// source\n", encoding="utf-8")
    run = mock.Mock()
    monkeypatch.setattr("acmake.cache_compile.subprocess.run", run)
    assert cache_compile_main([str(obj), str(src), "--", "cc", "-c", str(src)]) == 2
    assert not obj.exists()
    run.assert_not_called()
