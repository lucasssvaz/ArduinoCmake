"""Size recipe resolution and regex helpers."""

import re

from acmake.size_report import (
    _basic_summary_lines,
    _sum_regex_matches,
    resolve_size_command,
)


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
