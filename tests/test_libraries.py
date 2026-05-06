from pathlib import Path

from acmake.libraries import (
    Library,
    LibraryResolveNote,
    ancestor_library_container_dirs,
    discover_libraries,
    ensure_build_libraries_stub_dirs,
    includes_from_source,
    platform_header_scan_roots,
    resolve_libraries_for_sketch,
)


def test_includes_from_source_preserves_file_order() -> None:
    txt = '#include "Zed.h"\n#include "Abe.h"\n'
    assert includes_from_source(txt) == ["Zed", "Abe"]


def test_includes_from_source_dedupes() -> None:
    txt = '#include "WiFi.h"\n#include "WiFi.h"\n'
    assert includes_from_source(txt) == ["WiFi"]


def test_includes_from_source_skips_toolchain_std_headers() -> None:
    txt = (
        '#include <string.h>\n'
        '#include "stdio.h"\n'
        '#include <WiFi.h>\n'
        '#include "Zed.h"\n'
    )
    assert includes_from_source(txt) == ["WiFi", "Zed"]


def test_includes_from_source_skips_multi_segment_sdk_paths() -> None:
    txt = (
        '#include <freertos/task.h>\n'
        '#include "Wire.h"\n'
        '#include <esp_wifi.h>\n'
    )
    assert includes_from_source(txt) == ["Wire", "esp_wifi"]


def test_freertos_task_h_does_not_resolve_basename_task_library(
    tmp_path: Path,
) -> None:
    """``#include <freertos/task.h>`` is SDK/core — not token ``task`` for a library."""
    libroot = tmp_path / "libraries"
    decoy = libroot / "Task"
    decoy.mkdir(parents=True)
    (decoy / "library.properties").write_text(
        "name=Task\narchitectures=*\n", encoding="utf-8"
    )
    (decoy / "src").mkdir()
    (decoy / "src" / "task.h").write_text("#pragma once\n", encoding="utf-8")
    (decoy / "src" / "Task.cpp").write_text("//\n", encoding="utf-8")

    consumer = libroot / "Consumer"
    consumer.mkdir(parents=True)
    (consumer / "library.properties").write_text(
        "name=Consumer\narchitectures=*\n", encoding="utf-8"
    )
    (consumer / "src").mkdir()
    (consumer / "src" / "Consumer.h").write_text("#pragma once\n", encoding="utf-8")
    (consumer / "src" / "Consumer.cpp").write_text(
        '#include <freertos/task.h>\n#include "Consumer.h"\n',
        encoding="utf-8",
    )

    sketch = tmp_path / "Sk" / "Sk.ino"
    sketch.parent.mkdir(parents=True)
    sketch.write_text(
        '#include "Consumer.h"\nvoid setup(){} void loop(){}\n', encoding="utf-8"
    )
    body = '#include "Consumer.h"\n'
    libs = resolve_libraries_for_sketch(sketch.parent, body, "esp32", [libroot])
    names = {x.name for x in libs}
    assert "Consumer" in names
    assert "Task" not in names


def test_std_string_h_in_library_does_not_link_decoy_string_header_lib(
    tmp_path: Path,
) -> None:
    """``#include <string.h>`` must not resolve a library that only ships ``string.h``."""
    libroot = tmp_path / "libraries"
    decoy = libroot / "Decoy"
    decoy.mkdir(parents=True)
    (decoy / "library.properties").write_text(
        "name=Decoy\narchitectures=*\n", encoding="utf-8"
    )
    (decoy / "src").mkdir()
    (decoy / "src" / "string.h").write_text("#pragma once\n", encoding="utf-8")
    (decoy / "src" / "Decoy.cpp").write_text("//\n", encoding="utf-8")

    ble = libroot / "BLE"
    ble.mkdir(parents=True)
    (ble / "library.properties").write_text(
        "name=BLE\narchitectures=*\n", encoding="utf-8"
    )
    (ble / "src").mkdir()
    (ble / "src" / "BLE.h").write_text("#pragma once\n", encoding="utf-8")
    (ble / "src" / "BLE.cpp").write_text(
        '#include <string.h>\n#include "BLE.h"\n',
        encoding="utf-8",
    )

    sketch = tmp_path / "Sk" / "Sk.ino"
    sketch.parent.mkdir(parents=True)
    sketch.write_text(
        '#include "BLE.h"\nvoid setup(){} void loop(){}\n', encoding="utf-8"
    )
    body = '#include "BLE.h"\n'
    libs = resolve_libraries_for_sketch(sketch.parent, body, "esp32", [libroot])
    names = {x.name for x in libs}
    assert "BLE" in names
    assert "Decoy" not in names


def test_resolve_libraries_stable_across_calls(tmp_path: Path) -> None:
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    (sketch / "Blink.ino").write_text(
        '#include "Wire.h"\nvoid setup(){} void loop(){}\n', encoding="utf-8"
    )
    libroot = tmp_path / "libraries"
    w = libroot / "Wire"
    w.mkdir(parents=True)
    (w / "library.properties").write_text(
        "name=Wire\narchitectures=*\n", encoding="utf-8"
    )
    (w / "src").mkdir()
    (w / "src" / "Wire.cpp").write_text("//\n", encoding="utf-8")
    body = '#include "Wire.h"\n'
    a = resolve_libraries_for_sketch(sketch, body, "avr", [libroot])
    b = resolve_libraries_for_sketch(sketch, body, "avr", [libroot])
    assert [x.name for x in a] == [x.name for x in b]


def test_discover_reads_version(tmp_path: Path) -> None:
    lib = tmp_path / "libraries" / "Foo"
    lib.mkdir(parents=True)
    (lib / "library.properties").write_text(
        "name=Foo\nversion=1.2.3\narchitectures=*\n", encoding="utf-8"
    )
    (lib / "src").mkdir()
    found = discover_libraries([tmp_path / "libraries"])
    assert found["foo"].version == "1.2.3"


def test_discover_by_name_and_folder(tmp_path: Path):
    lib = tmp_path / "libraries" / "Wire"
    lib.mkdir(parents=True)
    (lib / "library.properties").write_text(
        "name=Wire\narchitectures=*\n", encoding="utf-8"
    )
    (lib / "src").mkdir()
    (lib / "src" / "Wire.cpp").write_text("//x\n", encoding="utf-8")

    found = discover_libraries([tmp_path / "libraries"])
    assert "wire" in found
    assert found["wire"].root.name == "Wire"


def test_resolve_from_include(tmp_path: Path):
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    (sketch / "Blink.ino").write_text('#include "Wire.h"\nvoid setup(){} void loop(){}\n')
    libroot = tmp_path / "libraries"
    w = libroot / "Wire"
    w.mkdir(parents=True)
    (w / "library.properties").write_text("name=Wire\narchitectures=*\n", encoding="utf-8")
    (w / "src").mkdir()
    (w / "src" / "Wire.cpp").write_text("//\n", encoding="utf-8")

    body = '#include "Wire.h"\n'
    libs = resolve_libraries_for_sketch(sketch, body, "avr", [libroot])
    assert len(libs) == 1
    assert libs[0].name == "Wire"


def test_platform_header_scan_roots_only_variants_subdir(tmp_path: Path) -> None:
    plat = tmp_path / "pkg"
    core = plat / "cores" / "esp32"
    core.mkdir(parents=True)
    bogus_variant = plat
    roots = platform_header_scan_roots(core, bogus_variant, plat)
    assert roots == [core.resolve()]


def test_platform_header_scan_roots_includes_variant_under_variants(
    tmp_path: Path,
) -> None:
    plat = tmp_path / "pkg"
    core = plat / "cores" / "esp32"
    core.mkdir(parents=True)
    var = plat / "variants" / "denky32"
    var.mkdir(parents=True)
    roots = platform_header_scan_roots(core, var, plat)
    assert core.resolve() in roots
    assert var.resolve() in roots


def test_core_header_shadows_same_stem_in_user_library(tmp_path: Path) -> None:
    """``#include "Display.h"`` must not link a library when the core already provides it."""
    libroot = tmp_path / "libraries"
    dup = libroot / "ODROID-GO"
    dup.mkdir(parents=True)
    (dup / "library.properties").write_text(
        "name=ODROID-GO\narchitectures=*\n", encoding="utf-8"
    )
    (dup / "src").mkdir()
    (dup / "src" / "Display.h").write_text("#pragma once\n", encoding="utf-8")
    (dup / "src" / "ODROID-GO.cpp").write_text("//\n", encoding="utf-8")

    fake_core = tmp_path / "cores" / "esp32"
    fake_core.mkdir(parents=True)
    (fake_core / "Display.h").write_text("#pragma once\n", encoding="utf-8")

    sketch = tmp_path / "Sketch"
    sketch.mkdir()
    (sketch / "Sketch.ino").write_text(
        '#include "Display.h"\nvoid setup() {}\nvoid loop() {}\n',
        encoding="utf-8",
    )
    body = '#include "Display.h"\n'
    libs = resolve_libraries_for_sketch(
        sketch,
        body,
        "esp32",
        [libroot],
        platform_include_roots=[fake_core],
    )
    assert libs == []


def test_resolve_library_by_public_header_stem_not_only_properties_name(
    tmp_path: Path,
) -> None:
    """``#include "BLEDevice.h"`` must pull in ``name=BLE`` (ESP32-style API headers)."""
    libroot = tmp_path / "libraries"
    ble = libroot / "BLE"
    ble.mkdir(parents=True)
    (ble / "library.properties").write_text(
        "name=BLE\narchitectures=*\n", encoding="utf-8"
    )
    (ble / "src").mkdir()
    (ble / "src" / "BLEDevice.h").write_text("#pragma once\n", encoding="utf-8")
    (ble / "src" / "BLE.cpp").write_text("//\n", encoding="utf-8")

    sketch = tmp_path / "hardware" / "vendor" / "arch" / "libraries" / "BLE" / "examples" / "Server"
    sketch.mkdir(parents=True)
    (sketch / "Server.ino").write_text(
        '#include "BLEDevice.h"\nvoid setup() {}\nvoid loop() {}\n',
        encoding="utf-8",
    )
    body = '#include "BLEDevice.h"\n'
    libs = resolve_libraries_for_sketch(sketch, body, "esp32", [libroot])
    assert len(libs) == 1
    assert libs[0].name == "BLE"


def test_library_resolution_notes_show_transitive_source_file(tmp_path: Path) -> None:
    libroot = tmp_path / "libraries"
    eth = libroot / "Ethernet"
    eth.mkdir(parents=True)
    (eth / "library.properties").write_text(
        "name=Ethernet\narchitectures=*\n", encoding="utf-8"
    )
    (eth / "src").mkdir()
    (eth / "src" / "Ethernet.h").write_text("#pragma once\n", encoding="utf-8")

    wifi = libroot / "WiFi"
    wifi.mkdir(parents=True)
    (wifi / "library.properties").write_text(
        "name=WiFi\narchitectures=*\n", encoding="utf-8"
    )
    (wifi / "src").mkdir()
    (wifi / "src" / "WiFi.h").write_text(
        '#pragma once\n#include "Ethernet.h"\n', encoding="utf-8"
    )
    (wifi / "src" / "WiFi.cpp").write_text("// impl\n", encoding="utf-8")

    sketch = tmp_path / "Sk" / "Sk.ino"
    sketch.parent.mkdir(parents=True)
    sketch.write_text(
        '#include "WiFi.h"\nvoid setup(){} void loop(){}\n', encoding="utf-8"
    )
    body = '#include "WiFi.h"\n'
    notes: list[LibraryResolveNote] = []
    resolve_libraries_for_sketch(
        sketch.parent, body, "esp32", [libroot], resolution_notes=notes
    )
    eth_notes = [n for n in notes if n.library_name == "Ethernet"]
    assert len(eth_notes) == 1
    assert "WiFi.h" in eth_notes[0].via
    assert "Ethernet.h" in eth_notes[0].via


def test_resolve_transitive_includes_from_library_sources(tmp_path: Path):
    libroot = tmp_path / "libraries"
    eth = libroot / "Ethernet"
    eth.mkdir(parents=True)
    (eth / "library.properties").write_text(
        "name=Ethernet\narchitectures=*\n", encoding="utf-8"
    )
    (eth / "src").mkdir()
    (eth / "src" / "Ethernet.h").write_text("#pragma once\n", encoding="utf-8")

    wifi = libroot / "WiFi"
    wifi.mkdir(parents=True)
    (wifi / "library.properties").write_text("name=WiFi\narchitectures=*\n", encoding="utf-8")
    (wifi / "src").mkdir()
    (wifi / "src" / "WiFi.h").write_text(
        '#pragma once\n#include "Ethernet.h"\n', encoding="utf-8"
    )
    (wifi / "src" / "WiFi.cpp").write_text("// impl\n", encoding="utf-8")

    sketch = tmp_path / "Sk" / "Sk.ino"
    sketch.parent.mkdir(parents=True)
    sketch.write_text(
        '#include "WiFi.h"\nvoid setup(){} void loop(){}\n', encoding="utf-8"
    )
    body = '#include "WiFi.h"\n'
    libs = resolve_libraries_for_sketch(sketch.parent, body, "esp32", [libroot])
    names = {x.name.lower() for x in libs}
    assert "wifi" in names
    assert "ethernet" in names


def test_ancestor_library_dir_for_examples_under_libraries(tmp_path: Path):
    hw = tmp_path / "hardware" / "esp32" / "esp32" / "libraries"
    wifi = hw / "WiFi"
    wifi.mkdir(parents=True)
    (wifi / "library.properties").write_text(
        "name=WiFi\narchitectures=*\n", encoding="utf-8"
    )
    (wifi / "src").mkdir()
    (wifi / "src" / "WiFi.h").write_text("//\n", encoding="utf-8")
    ex = wifi / "examples" / "Client"
    ex.mkdir(parents=True)
    (ex / "Client.ino").write_text(
        '#include "WiFi.h"\nvoid setup(){} void loop(){}\n', encoding="utf-8"
    )

    rel = ancestor_library_container_dirs(ex)
    assert hw.resolve() in rel
    found = discover_libraries(rel)
    assert "wifi" in found


def test_ensure_build_libraries_stub_dirs_uses_root_folder_name(tmp_path: Path) -> None:
    """ESP32 objcopy hooks look for ``{build.path}/libraries/ESP_SR`` (folder name)."""
    ext = tmp_path / "from_pkg" / "ESP_SR"
    ext.mkdir(parents=True)
    lib = Library(
        root=ext,
        name="ESP Speech Recognition",
        architectures="esp32",
        depends=(),
        includes_override=None,
    )
    build = tmp_path / "out"
    ensure_build_libraries_stub_dirs(build, [lib])
    assert (build / "libraries" / "ESP_SR").is_dir()
