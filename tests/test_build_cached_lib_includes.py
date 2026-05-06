"""Per-library ``-I`` strings for shared-cache compiles stay stable across sketch link sets."""

from pathlib import Path

from acmake.build import (
    _build_includes,
    _lib_transitive_include_roots,
    includes_string_for_cached_lib_compile,
)
from acmake.libraries import Library


def _lib(
    tmp: Path, name: str, *, depends: tuple[str, ...] = (), extra_h: str | None = None
) -> Library:
    root = tmp / name
    src = root / "src"
    src.mkdir(parents=True)
    (root / "library.properties").write_text(
        f"name={name}\narchitectures=*\n", encoding="utf-8"
    )
    (src / f"{name}.h").write_text("//\n", encoding="utf-8")
    if extra_h:
        (src / extra_h).write_text("//\n", encoding="utf-8")
    return Library(
        root=root.resolve(),
        name=name,
        architectures="*",
        depends=depends,
        includes_override=None,
    )


def test_wifi_closure_adds_network_via_include_token(tmp_path: Path) -> None:
    """ESP32 WiFi pulls ``Network.h`` without ``depends=``; closure must still add Network ``-I``."""
    net = _lib(tmp_path, "Network")
    wifi = tmp_path / "WiFi"
    wsrc = wifi / "src"
    wsrc.mkdir(parents=True)
    (wifi / "library.properties").write_text(
        "name=WiFi\narchitectures=*\n", encoding="utf-8"
    )
    (wsrc / "WiFi.h").write_text("//\n", encoding="utf-8")
    (wsrc / "WiFi.cpp").write_text('#include "Network.h"\n', encoding="utf-8")
    wifi_lib = Library(
        root=wifi.resolve(),
        name="WiFi",
        architectures="*",
        depends=(),
        includes_override=None,
    )
    libs = [wifi_lib, net]
    stems: frozenset[str] = frozenset()
    roots = _lib_transitive_include_roots(libs, wifi_lib, stems)
    assert net.include_roots[0] in roots


def test_cached_wifi_includes_identical_with_extra_unrelated_lib(tmp_path: Path) -> None:
    """WiFi ``-I`` line must not change when an unrelated third library is also linked."""
    core = tmp_path / "core"
    core.mkdir()
    var = tmp_path / "var"
    var.mkdir()
    expanded = {
        "build.core.path": str(core),
        "build.variant.path": str(var),
    }
    zed = _lib(tmp_path, "ZedOnly")
    wifi = tmp_path / "WiFi"
    wsrc = wifi / "src"
    wsrc.mkdir(parents=True)
    (wifi / "library.properties").write_text(
        "name=WiFi\narchitectures=*\n", encoding="utf-8"
    )
    (wsrc / "WiFi.h").write_text("//\n", encoding="utf-8")
    (wsrc / "WiFi.cpp").write_text("// no other lib includes\n", encoding="utf-8")
    wifi_lib = Library(
        root=wifi.resolve(),
        name="WiFi",
        architectures="*",
        depends=(),
        includes_override=None,
    )
    stems: frozenset[str] = frozenset()
    inc_wifi_only = includes_string_for_cached_lib_compile(
        expanded, [wifi_lib], wifi_lib, stems
    )
    inc_wifi_plus_zed = includes_string_for_cached_lib_compile(
        expanded, [wifi_lib, zed], wifi_lib, stems
    )
    assert inc_wifi_only == inc_wifi_plus_zed

    full_roots = []
    for L in (wifi_lib, zed):
        full_roots.extend(L.include_roots)
    full_includes = _build_includes(expanded, full_roots)
    assert full_includes != inc_wifi_only
