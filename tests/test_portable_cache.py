"""The generated single-file bundle carries working standalone cache wrappers."""

from __future__ import annotations

import base64
import io
import os
import runpy
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def test_portable_bundle_cache_compile_and_archive(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    generator = root / "tools" / "gen_arduino_cmake_portable.py"
    generated = root / "arduino_cmake.py"
    generator_namespace = runpy.run_path(str(generator))
    expected = generator_namespace["_generated_bytes"]()
    assert expected == generator_namespace["_generated_bytes"]()
    temporary_generated = tmp_path / "arduino_cmake.py"
    temporary_generated.write_bytes(expected)
    if generated.is_file():
        assert generated.read_bytes() == expected
        portable_to_smoke = generated
    else:
        portable_to_smoke = temporary_generated
    namespace = runpy.run_path(str(temporary_generated))
    bundle = base64.standard_b64decode("".join(namespace["_BUNDLE_CHUNKS"]))
    extracted = tmp_path / "portable"
    with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
        names = set(archive.namelist())
        assert "acmake/cache_fs.py" in names
        assert "acmake/cache_compile.py" in names
        assert "acmake/cache_archive.py" in names
        assert "acmake/cache_prune.py" in names
        archive.extractall(extracted)

    compiler = tmp_path / "compiler.py"
    compiler.write_text(
        """
import pathlib
import sys

args = sys.argv[1:]
pathlib.Path(args[args.index("-o") + 1]).write_bytes(b"portable-object")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.cpp"
    source.write_text("// source\n", encoding="utf-8")
    obj = tmp_path / "object.o"
    env = dict(os.environ)
    fake_old = tmp_path / "fake-old"
    fake_package = fake_old / "acmake"
    fake_package.mkdir(parents=True)
    (fake_package / "__init__.py").write_text("", encoding="utf-8")
    (fake_package / "cache_fs.py").write_text(
        'raise RuntimeError("poisoned by old acmake")\n', encoding="utf-8"
    )
    env["PYTHONPATH"] = str(fake_old)
    compile_result = subprocess.run(
        [
            sys.executable,
            str(extracted / "acmake" / "cache_compile.py"),
            str(obj),
            str(source),
            "--",
            sys.executable,
            str(compiler),
            "-o",
            str(obj),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    assert obj.read_bytes() == b"portable-object"

    archiver = tmp_path / "archiver.py"
    archiver.write_text(
        """
import pathlib
import sys

pathlib.Path(sys.argv[2]).write_bytes(b"portable-archive")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    core_archive = tmp_path / "core.a"
    archive_result = subprocess.run(
        [
            sys.executable,
            str(extracted / "acmake" / "cache_archive.py"),
            str(core_archive),
            str(obj),
            "--",
            sys.executable,
            str(archiver),
            "rcs",
            str(core_archive),
            str(obj),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert archive_result.returncode == 0, archive_result.stderr
    assert core_archive.read_bytes() == b"portable-archive"

    smoke_env = dict(env)
    smoke_env["HOME"] = str(tmp_path / "home")
    smoke = subprocess.run(
        [sys.executable, str(portable_to_smoke), "--help"],
        cwd=tmp_path,
        env=smoke_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode == 0, smoke.stderr
    assert "compile" in smoke.stdout
    assert "cache-prune" in smoke.stdout


def test_concurrent_first_extract_does_not_see_partial_bundle(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    generator_namespace = runpy.run_path(
        str(root / "tools" / "gen_arduino_cmake_portable.py")
    )
    script = tmp_path / "arduino_cmake.py"
    script.write_bytes(generator_namespace["_generated_bytes"]())
    home = tmp_path / "home"
    workers = 12
    env = os.environ.copy()
    env["HOME"] = str(home)

    def run_help() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_help) for _ in range(workers)]
        results = [future.result() for future in futures]
    assert [result.returncode for result in results] == [0] * workers, [
        result.stderr for result in results
    ]
    cache = home / ".cache" / "arduino_cmake_portable"
    published = [path for path in cache.iterdir() if not path.name.startswith(".")]
    assert len(published) == 1
    assert (published[0] / ".ok").is_file()
    assert (published[0] / "acmake" / "board_list.py").is_file()
    leftovers = [path for path in cache.iterdir() if path.name.startswith(".")]
    assert leftovers == []
