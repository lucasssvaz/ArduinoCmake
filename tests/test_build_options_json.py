"""build.options.json (arduino-cli parity)."""

import json
from pathlib import Path

from acmake.build_options_json import (
    _additional_files_relative,
    write_build_options_json,
)
from acmake.config import ArduinoPaths
from acmake.fqbn import FQBN


def test_additional_files_under_examples(tmp_path: Path) -> None:
    lib = tmp_path / "libs" / "WiFi"
    examples = lib / "examples"
    sk = examples / "WiFiClient"
    sk.mkdir(parents=True)
    bd = sk / "build"
    bd.mkdir()
    # Like arduino-cli: …/examples/Sketch/build → ``../..`` is the ``examples`` folder.
    assert _additional_files_relative(bd, sk) == os_norm_relpath(examples, bd)


def os_norm_relpath(a: Path, b: Path) -> str:
    import os

    return os.path.relpath(a.resolve(), b.resolve())


def test_write_build_options_json_minimal(tmp_path: Path) -> None:
    data = tmp_path / "data"
    user = tmp_path / "user"
    (data / "packages").mkdir(parents=True)
    (user / "libraries").mkdir(parents=True)
    paths = ArduinoPaths(data_dir=data, user_dir=user)
    sk = tmp_path / "MySketch"
    sk.mkdir()
    bd = sk / "build"
    bd.mkdir()
    fqbn = FQBN.parse("esp8266:esp8266:generic")
    expanded = {"compiler.optimization_flags": "-Os"}
    out = write_build_options_json(
        build_dir=bd,
        sketch_dir=sk,
        paths=paths,
        fqbn=fqbn,
        expanded=expanded,
        build_properties=None,
        compiler_warnings=None,
    )
    assert out == bd / "build.options.json"
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["fqbn"] == fqbn.to_string()
    assert obj["sketchLocation"] == str(sk.resolve())
    assert "packages" in obj["hardwareFolders"]
    assert obj["otherLibrariesFolders"] == str((user / "libraries").resolve())
    assert obj["compiler.optimization_flags"] == "-Os"
    assert "additionalFiles" not in obj
    assert "customBuildProperties" not in obj


def test_warning_flags_not_duplicated_when_already_in_build_properties(
    tmp_path: Path,
) -> None:
    """``--build-property compiler.warning_flags.all=…`` must not repeat from ``--warnings``."""
    data = tmp_path / "data"
    user = tmp_path / "user"
    (data / "packages").mkdir(parents=True)
    (user / "libraries").mkdir(parents=True)
    paths = ArduinoPaths(data_dir=data, user_dir=user)
    sk = tmp_path / "Sk"
    sk.mkdir()
    bd = sk / "build"
    bd.mkdir()
    fqbn = FQBN.parse("arduino:avr:uno")
    flags = "-Wall -Werror=all -Wextra"
    expanded = {
        "compiler.warning_flags": flags,
        "compiler.optimization_flags": "",
    }
    write_build_options_json(
        build_dir=bd,
        sketch_dir=sk,
        paths=paths,
        fqbn=fqbn,
        expanded=expanded,
        build_properties=[f"compiler.warning_flags.all={flags}"],
        compiler_warnings="all",
    )
    obj = json.loads((bd / "build.options.json").read_text(encoding="utf-8"))
    assert obj["customBuildProperties"] == f"compiler.warning_flags.all={flags}"


def test_write_build_options_json_custom_and_warnings(tmp_path: Path) -> None:
    data = tmp_path / "data"
    user = tmp_path / "user"
    (data / "packages").mkdir(parents=True)
    (user / "libraries").mkdir(parents=True)
    paths = ArduinoPaths(data_dir=data, user_dir=user)
    sk = tmp_path / "Sk"
    sk.mkdir()
    bd = sk / "build"
    bd.mkdir()
    fqbn = FQBN.parse("arduino:avr:uno")
    expanded = {
        "compiler.warning_flags": "-Wall -Wextra",
        "compiler.optimization_flags": "",
    }
    write_build_options_json(
        build_dir=bd,
        sketch_dir=sk,
        paths=paths,
        fqbn=fqbn,
        expanded=expanded,
        build_properties=["upload.speed=115200", "build.extra_flags=-DFOO"],
        compiler_warnings="all",
    )
    obj = json.loads((bd / "build.options.json").read_text(encoding="utf-8"))
    cb = obj["customBuildProperties"]
    assert "upload.speed=115200" in cb
    assert "build.extra_flags=-DFOO" in cb
    assert "compiler.warning_flags.all=-Wall -Wextra" in cb
