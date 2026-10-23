"""Size recipe resolution and regex helpers."""

import re
from pathlib import Path
from unittest import mock

from acmake.build import BuildPlan
from acmake.fqbn import FQBN
from acmake.size_report import (
    _basic_overflow_errors,
    _basic_summary_lines,
    _sum_regex_matches,
    _try_print_advanced_json,
    print_size_report,
    resolve_size_command,
)

_ESP_LIKE = {
    "recipe.size.regex": r"^(?:\.flash\.text|\.dram0\.data)\s+([0-9]+).*",
    "recipe.size.regex.data": r"^(?:\.dram0\.data|\.dram0\.bss)\s+([0-9]+).*",
    "upload.maximum_size": "1310720",
    "upload.maximum_data_size": "327680",
}


def test_resolve_size_prefers_advanced():
    e = {
        "recipe.advanced_size.pattern": "echo advanced",
        "recipe.size.pattern": "echo basic",
    }
    cmd, kind = resolve_size_command(e)
    assert kind == "advanced"
    assert cmd == "echo advanced"


def test_resolve_size_basic_when_no_advanced():
    e = {
        "recipe.size.pattern": "avr-size -A {build.path}/{build.project_name}.elf",
        "build.path": "/tmp/b/",
        "build.project_name": "sk",
    }
    cmd, kind = resolve_size_command(e)
    assert kind == "basic"
    assert "sk.elf" in cmd


def test_resolve_size_os_specific_advanced():
    e = {
        "runtime.os": "linux",
        "recipe.advanced_size.pattern.linux": "echo linux",
        "recipe.advanced_size.pattern": "echo generic",
    }
    cmd, kind = resolve_size_command(e)
    assert kind == "advanced"
    assert cmd == "echo linux"


def test_sum_regex_matches_sums_lines():
    text = ".text           1000   0\n.data              50   0\n"
    rx = r"^(?:\.text|\.data)\s+([0-9]+)"
    assert _sum_regex_matches(rx, text) == 1050


def test_basic_summary_lines_avr_style():
    stdout = """AVR Memory Usage
----------------
Device: Unknown

Program:    1234 bytes
"""
    expanded = {
        "recipe.size.regex": r"^Program:\s+([0-9]+)",
        "recipe.size.regex.data": r"^Data:\s+([0-9]+)",
        "upload.maximum_size": "32256",
        "upload.maximum_data_size": "2048",
    }
    stdout2 = stdout + "Data:          99 bytes\n"
    lines = _basic_summary_lines(expanded, stdout2)
    assert any("1234" in ln and "32256" in ln for ln in lines)
    assert any("99" in ln and "2048" in ln for ln in lines)
    # Percentages are whole numbers (no ``3.8%``-style fraction).
    assert not any(re.search(r"\(\d+\.\d+%\)", ln) for ln in lines)
    assert any("(4%)" in ln for ln in lines)  # round(100 * 1234 / 32256) == 4
    assert any("(5%)" in ln for ln in lines)  # round(100 * 99 / 2048) == 5


def test_basic_overflow_none_when_fits():
    stdout = (
        ".flash.text   1000000   0\n.dram0.data   1000   0\n.dram0.bss   2000   0\n"
    )
    assert _basic_overflow_errors(_ESP_LIKE, stdout) == []


def test_basic_overflow_program_too_big():
    # Matches the esp32c6 OTA sketch that overflowed the default partition by 813 bytes.
    stdout = ".flash.text   1310533   0\n.dram0.data   1000   0\n"
    errors = _basic_overflow_errors(_ESP_LIKE, stdout)
    assert len(errors) == 1
    assert "Sketch too big" in errors[0] and "1311533" in errors[0]


def test_basic_overflow_data_too_big():
    stdout = ".flash.text   1000   0\n.dram0.data   1000   0\n.dram0.bss   400000   0\n"
    errors = _basic_overflow_errors(_ESP_LIKE, stdout)
    assert len(errors) == 1
    assert "Not enough memory" in errors[0]


def test_basic_overflow_ignored_without_limits():
    e = {k: v for k, v in _ESP_LIKE.items() if not k.startswith("upload.")}
    assert _basic_overflow_errors(e, ".flash.text   99999999   0\n") == []


def test_advanced_json_severity_error_does_not_fit(capsys):
    handled, fits = _try_print_advanced_json(
        '{"output": "Sketch too big", "severity": "error"}'
    )
    assert handled and not fits
    handled, fits = _try_print_advanced_json('{"output": "ok", "severity": "info"}')
    assert handled and fits


def _size_plan(tmp_path: Path, size_pattern: str) -> BuildPlan:
    build = tmp_path / "build"
    build.mkdir()
    elf = build / "Sketch.ino.elf"
    elf.write_bytes(b"\x7fELF")
    return BuildPlan(
        fqbn=FQBN.parse("espressif:esp32:esp32"),
        platform_root=tmp_path,
        sketch_dir=tmp_path / "Sketch",
        build_dir=build,
        expanded={
            "recipe.size.pattern": size_pattern,
            **_ESP_LIKE,
        },
        elf_path=elf,
    )


def test_size_report_runs_split_argv_not_cmd(tmp_path: Path, monkeypatch) -> None:
    plan = _size_plan(
        tmp_path,
        '"C:/tools/xtensa-esp-elf-size" -A "{build.path}/{build.project_name}.elf"',
    )
    plan.expanded["build.path"] = str(plan.build_dir).replace("\\", "/")
    plan.expanded["build.project_name"] = "Sketch.ino"
    seen: list[list[str]] = []

    def fake_run(argv, **_kw):
        seen.append(list(argv))
        return mock.Mock(
            returncode=0,
            stdout=".flash.text   1000   0\n.dram0.data   20   0\n.dram0.bss   30   0\n",
            stderr="",
        )

    monkeypatch.setattr("acmake.size_report.subprocess.run", fake_run)
    assert print_size_report(plan) is True
    assert len(seen) == 1
    assert seen[0][0] == "C:/tools/xtensa-esp-elf-size"
    assert seen[0][1] == "-A"
    assert seen[0][0] != "cmd"
    assert "cmd" not in seen[0]


def test_failed_size_tool_prints_exit_status(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    plan = _size_plan(tmp_path, "size-tool -A sketch.elf")

    def fake_run(argv, **_kw):
        return mock.Mock(returncode=1, stdout="", stderr="size: no such file")

    monkeypatch.setattr("acmake.size_report.subprocess.run", fake_run)
    assert print_size_report(plan) is True
    captured = capsys.readouterr()
    assert "size tool exited 1" in captured.out
    assert "size: no such file" in captured.out
    assert "no summary lines" not in captured.out
