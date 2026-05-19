import pytest

from acmake.properties import (
    collapse_duplicate_path_slashes,
    default_menu_options_for_board,
    escape_cpp_string_in_d_define,
    escape_dquoted_defines_in_properties,
    expand_properties,
    expand_string_placeholders,
    expand_template,
    merge_board_properties,
    merged_with_build_properties,
    normalize_cpp_d_string_macros_in_text,
    parse_build_property,
    quote_brace_placeholder_values_in_d_defines,
)


def test_collapse_duplicate_path_slashes():
    assert (
        collapse_duplicate_path_slashes(
            "@/Users/x/hardware/esp32//tools/esp32-arduino-libs/esp32s3/flags/includes"
        )
        == "@/Users/x/hardware/esp32/tools/esp32-arduino-libs/esp32s3/flags/includes"
    )


def test_collapse_slashes_preserves_url_scheme():
    assert collapse_duplicate_path_slashes("fetch http://a.com//b") == "fetch http://a.com/b"


def test_expand_template_nested():
    assert expand_template("X{a}Y", {"a": "1", "b": "2"}) == "X1Y"


def test_nested_placeholder_in_token_name():
    """ESP32-style ``{tools.{build.tarch}-esp-elf-gcc.path}/bin/gcc``."""
    ctx = {
        "build.tarch": "xtensa",
        "tools.xtensa-esp-elf-gcc.path": "/opt/xtensa/",
    }
    s = "{tools.{build.tarch}-esp-elf-gcc.path}/bin/xtensa-esp32s3-elf-gcc"
    assert expand_string_placeholders(s, ctx) == "/opt/xtensa//bin/xtensa-esp32s3-elf-gcc"


def test_expand_properties_recursive():
    p = {"a": "{b}", "b": "ok"}
    out = expand_properties(p)
    assert out["a"] == "ok"


def test_quote_brace_placeholder_in_d_define():
    s = "-O2 -DARDUINO_FQBN={build.fqbn} -MMD"
    assert quote_brace_placeholder_values_in_d_defines(s) == '-O2 -DARDUINO_FQBN="{build.fqbn}" -MMD'


def test_expand_properties_brace_define_becomes_quoted_value():
    p = {
        "build.extra_flags": "-O2 -DARDUINO_FQBN={build.fqbn} -MMD",
        "build.fqbn": "espressif:esp32:esp32s3",
    }
    out = expand_properties(p)
    assert (
        out["build.extra_flags"]
        == '-O2 -DARDUINO_FQBN="espressif:esp32:esp32s3" -MMD'
    )


def test_expand_string_placeholders_quotes_define_after_indirect_expansion():
    """``{flags}`` may expand to a ``-D...={key}`` fragment; quote before next ``{`` pass."""
    data = {
        "flags": "-DARDUINO_FQBN={build.fqbn}",
        "build.fqbn": "v:a:b",
        "recipe": "{flags}",
    }
    assert expand_string_placeholders("{recipe}", data) == '-DARDUINO_FQBN="v:a:b"'


def test_inject_build_paths_sets_fqbn():
    from acmake.properties import inject_build_paths

    base = {"build.extra_flags": '-DARDUINO_FQBN="{build.fqbn}"'}
    out = inject_build_paths(
        base,
        runtime_platform_path="/plat/",
        build_path="/b/",
        build_project_name="sk",
        sketch_path="/s/",
        fqbn_string="espressif:esp32:esp32s3",
        fqbn_arch="esp32",
    )
    assert "espressif:esp32:esp32s3" in out["build.extra_flags"]
    assert "{build.fqbn}" not in out["build.extra_flags"]


def test_inject_build_paths_arch_is_uppercase():
    """build.arch must be uppercase per the Arduino platform spec."""
    from acmake.properties import inject_build_paths

    base = {"recipe": "-DARDUINO_ARCH_{build.arch}"}
    out = inject_build_paths(
        base,
        runtime_platform_path="/plat/",
        build_path="/b/",
        build_project_name="sk",
        sketch_path="/s/",
        fqbn_arch="esp32",
    )
    assert out["build.arch"] == "ESP32"
    assert out["recipe"] == "-DARDUINO_ARCH_ESP32"


def test_inject_build_paths_sketch_path_expands(tmp_path):
    """``{sketch_path}`` is a platform-spec alias for the sketch directory (no trailing slash)."""
    from acmake.properties import inject_build_paths

    sk = tmp_path / "MySketch"
    sk.mkdir()
    sk_resolved = str(sk.resolve())
    out = inject_build_paths(
        {"hook": "X={sketch_path}Y"},
        runtime_platform_path=str(tmp_path / "plat"),
        build_path=str(tmp_path / "build") + "/",
        build_project_name="MySketch",
        sketch_path=str(sk) + "/",
        fqbn_string="v:a:b",
        fqbn_arch="esp32",
    )
    assert out["hook"] == f"X={sk_resolved}Y"


def test_apply_runtime_os_property_overrides_windows_hooks() -> None:
    from acmake.properties import apply_runtime_os_property_overrides

    props = {
        "runtime.os": "windows",
        "recipe.hooks.prebuild.3.pattern": "/usr/bin/env bash -c \"echo unix\"",
        "recipe.hooks.prebuild.3.pattern.windows": "cmd /c echo win",
        "recipe.hooks.prebuild.3.pattern.linux": "echo linux",
    }
    out = apply_runtime_os_property_overrides(props)
    assert out["recipe.hooks.prebuild.3.pattern"] == "cmd /c echo win"
    assert "recipe.hooks.prebuild.3.pattern.windows" not in out
    assert "recipe.hooks.prebuild.3.pattern.linux" not in out


def test_inject_build_paths_windows_no_slash_before_hook_quote(tmp_path):
    """ESP32-style ``"{build.source.path}"/file`` must not get ``.../"/file`` (Windows / CI)."""
    from acmake.properties import inject_build_paths

    sk = tmp_path / "WiFiClientSecure"
    sk.mkdir()
    plat = tmp_path / "plat"
    plat.mkdir()
    bd = tmp_path / "build"
    bd.mkdir()
    out = inject_build_paths(
        {
            "hook": '[ ! -f "{build.source.path}"/partitions.csv ] || '
            'cp -f "{build.source.path}"/partitions.csv "{build.path}"/partitions.csv'
        },
        runtime_platform_path=str(plat),
        build_path=str(bd),
        build_project_name="ex",
        sketch_path=str(sk),
        runtime_os="windows",
    )
    cmd = out["hook"]
    assert '/"/partitions' not in cmd
    assert str(sk.resolve()) in cmd
    assert str(bd.resolve()) in cmd


def test_inject_build_paths_brace_only_fqbn_define_is_quoted():
    from acmake.properties import inject_build_paths

    base = {"build.extra_flags": "-DARDUINO_FQBN={build.fqbn}"}
    out = inject_build_paths(
        base,
        runtime_platform_path="/plat/",
        build_path="/b/",
        build_project_name="sk",
        sketch_path="/s/",
        fqbn_string="espressif:esp32:esp32s3",
        fqbn_arch="esp32",
    )
    assert out["build.extra_flags"] == '-DARDUINO_FQBN="espressif:esp32:esp32s3"'


def test_escape_cpp_string_in_d_define_plain_fqbn():
    s = '-DARDUINO_FQBN="espressif:esp32:esp32s3"'
    assert escape_cpp_string_in_d_define(s) == s


def test_normalize_unquoted_arduino_fqbn_becomes_quoted_string():
    s = "-O2 -DARDUINO_FQBN=espressif:esp32:esp32s3 -MMD"
    assert (
        normalize_cpp_d_string_macros_in_text(s)
        == '-O2 -DARDUINO_FQBN="espressif:esp32:esp32s3" -MMD'
    )


def test_normalize_does_not_double_quote_already_quoted_fqbn():
    s = '-DARDUINO_FQBN="espressif:esp32:esp32s3"'
    assert normalize_cpp_d_string_macros_in_text(s) == s


def test_normalize_unquotes_integral_quoted_defines():
    s = '-DARDUINO_USB_DFU_ON_BOOT="0" -DARDUINO_USB_CDC_ON_BOOT="1"'
    assert (
        normalize_cpp_d_string_macros_in_text(s)
        == "-DARDUINO_USB_DFU_ON_BOOT=0 -DARDUINO_USB_CDC_ON_BOOT=1"
    )


def test_normalize_unquotes_hex_vid_style_defines():
    s = '-DARDUINO_USB_VID="0x2341" -DARDUINO_USB_PID="0x0001"'
    assert normalize_cpp_d_string_macros_in_text(s) == (
        "-DARDUINO_USB_VID=0x2341 -DARDUINO_USB_PID=0x0001"
    )


def test_normalize_unquotes_integer_with_c_suffix():
    s = '-DF_CPU="240000000L"'
    assert normalize_cpp_d_string_macros_in_text(s) == "-DF_CPU=240000000L"


def test_normalize_unquotes_hex_with_suffix():
    s = '-DADDR="0x40000UL"'
    assert normalize_cpp_d_string_macros_in_text(s) == "-DADDR=0x40000UL"


def test_normalize_mixed_integral_and_fqbn():
    s = (
        '-DARDUINO_USB_DFU_ON_BOOT="0" '
        '-DARDUINO_FQBN="espressif:esp32:esp32s3"'
    )
    assert normalize_cpp_d_string_macros_in_text(s) == (
        '-DARDUINO_USB_DFU_ON_BOOT=0 '
        '-DARDUINO_FQBN="espressif:esp32:esp32s3"'
    )


def test_escape_cpp_string_in_d_define_backslashes():
    s = r'-DARDUINO_FQBN="vendor:arch:board\subdir"'
    assert escape_cpp_string_in_d_define(s) == r'-DARDUINO_FQBN="vendor:arch:board\\subdir"'


def test_escape_dquoted_defines_in_properties():
    props = {
        "build.extra_flags": r'-DARDUINO_FQBN="a\b" -O2',
        "other": "no-define-here",
    }
    out = escape_dquoted_defines_in_properties(props)
    assert out["build.extra_flags"] == r'-DARDUINO_FQBN="a\\b" -O2'
    assert out["other"] == "no-define-here"


def test_merge_board_menu():
    raw = {
        "uno.name": "Uno",
        "uno.build.mcu": "atmega328p",
        "uno.menu.cpu.atmega168.build.mcu": "atmega168",
        "uno.menu.cpu.atmega168.upload.maximum_size": "14336",
    }
    m = merge_board_properties("uno", raw, {"cpu": "atmega168"})
    assert m["build.mcu"] == "atmega168"
    assert m["name"] == "Uno"


def test_default_menu_options_first_in_file_per_group():
    """Arduino uses the first menu entry in boards.txt when FQBN omits that group."""
    raw = {
        "b.menu.UploadSpeed.921600": "921600",
        "b.menu.UploadSpeed.921600.upload.speed": "921600",
        "b.menu.UploadSpeed.115200": "115200",
        "b.menu.UploadSpeed.115200.upload.speed": "115200",
    }
    assert default_menu_options_for_board("b", raw) == {"UploadSpeed": "921600"}


def test_default_menu_os_only_label_row():
    raw = {
        "b.menu.UploadSpeed.460800.linux": "460800",
        "b.menu.UploadSpeed.460800.macosx": "460800",
        "b.menu.UploadSpeed.460800.upload.speed": "460800",
    }
    assert default_menu_options_for_board("b", raw)["UploadSpeed"] == "460800"


def test_merge_board_applies_default_upload_speed():
    raw = {
        "b.name": "B",
        "b.menu.UploadSpeed.921600": "921600",
        "b.menu.UploadSpeed.921600.upload.speed": "921600",
        "b.menu.UploadSpeed.115200": "115200",
        "b.menu.UploadSpeed.115200.upload.speed": "115200",
    }
    d = default_menu_options_for_board("b", raw)
    m = merge_board_properties("b", raw, {**d, **{}})
    assert m["upload.speed"] == "921600"
    m2 = merge_board_properties("b", raw, {**d, **{"UploadSpeed": "115200"}})
    assert m2["upload.speed"] == "115200"


def test_merge_board_menu_option_prefix_is_exact_not_substring():
    """FlashSize=16M must not pick keys for menu option 16MB (boards.txt prefix collision)."""
    raw = {
        "b.name": "B",
        "b.menu.FlashSize.16M.build.flash_size": "16MB",
        "b.menu.FlashSize.16MB.build.flash_size": "sixteen_mb_variant",
    }
    assert merge_board_properties("b", raw, {"FlashSize": "16M"})["build.flash_size"] == "16MB"
    assert (
        merge_board_properties("b", raw, {"FlashSize": "16MB"})["build.flash_size"]
        == "sixteen_mb_variant"
    )


def test_parse_build_property_splits_on_first_equals() -> None:
    k, v = parse_build_property("compiler.warning_flags.all=-Wall -Werror=all -Wextra")
    assert k == "compiler.warning_flags.all"
    assert v == "-Wall -Werror=all -Wextra"


def test_parse_build_property_rejects_missing_equals() -> None:
    with pytest.raises(ValueError, match="invalid --build-property"):
        parse_build_property("noequals")


def test_merged_with_build_properties_overrides_and_last_wins() -> None:
    base = {"a": "1", "b": "2"}
    out = merged_with_build_properties(
        base,
        ["b=3", "c=4", "c=5"],
    )
    assert out["a"] == "1" and out["b"] == "3" and out["c"] == "5"
    assert base["b"] == "2"
