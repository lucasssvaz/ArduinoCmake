"""``--warnings`` / ``compiler.warning_flags.*`` (arduino-cli parity)."""

import hashlib

import pytest

from acmake.fqbn import FQBN
from acmake.properties import (
    apply_compiler_warning_level,
    normalize_compiler_warning_level,
)


def test_normalize_compiler_warning_level() -> None:
    assert normalize_compiler_warning_level("ALL") == "all"


def test_normalize_compiler_warning_level_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="invalid compiler warning level"):
        normalize_compiler_warning_level("banana")


def test_apply_compiler_warning_level_uses_suffixed_key() -> None:
    expanded = {
        "compiler.warning_flags": "-w",
        "compiler.warning_flags.none": "-w",
        "compiler.warning_flags.default": "",
        "compiler.warning_flags.more": "-Wall",
        "compiler.warning_flags.all": "-Wall -Wextra",
    }
    out = apply_compiler_warning_level(expanded, "all")
    assert out["compiler.warning_flags"] == "-Wall -Wextra"


def test_apply_compiler_warning_level_default_empty() -> None:
    expanded = {
        "compiler.warning_flags": "-w",
        "compiler.warning_flags.default": "",
    }
    out = apply_compiler_warning_level(expanded, "default")
    assert out["compiler.warning_flags"] == ""


def test_apply_compiler_warning_level_missing_suffix_falls_back() -> None:
    expanded = {"compiler.warning_flags": "-Wno-everything"}
    out = apply_compiler_warning_level(expanded, "more")
    assert out["compiler.warning_flags"] == "-Wno-everything"


def test_object_cache_key_includes_warnings_level() -> None:
    f = FQBN.parse("arduino:avr:uno")
    base = f.object_cache_key(core_version="1.0")
    with_warn = f.object_cache_key(core_version="1.0", compiler_warnings="all")
    assert base != with_warn
    blob = f"{f.to_string()}\0{'1.0'}\0warnings=all".encode("utf-8")
    want = hashlib.sha256(blob).hexdigest()[:32]
    assert with_warn == want


def test_object_cache_key_includes_build_property_tag() -> None:
    f = FQBN.parse("arduino:avr:uno")
    a = f.object_cache_key(core_version="1.0", build_property_tag="abc123")
    b = f.object_cache_key(core_version="1.0", build_property_tag="xyz789")
    assert a != b
    blob = f"{f.to_string()}\0{'1.0'}\0props=abc123".encode("utf-8")
    assert f.object_cache_key(core_version="1.0", build_property_tag="abc123") == (
        hashlib.sha256(blob).hexdigest()[:32]
    )
