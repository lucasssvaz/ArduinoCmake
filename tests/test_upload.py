"""Upload recipe expansion (tool-scoped ``path`` / ``cmd`` / ``upload.pattern_args``)."""

from acmake.upload import expand_upload_pattern


def test_expand_upload_esp32_injects_tool_shorthands() -> None:
    """ESP32 uses ``"{path}/{cmd}" {upload.pattern_args}`` (not ``tools.esptool_py.upload.pattern_args``)."""
    exp: dict[str, str] = {
        "runtime.os": "linux",
        "upload.tool": "esptool_py",
        "upload.speed": "921600",
        "upload.flags": "",
        "upload.erase_cmd": "",
        "upload.extra_flags": "",
        "build.mcu": "esp32s3",
        "build.bootloader_addr": "0x0",
        "build.path": "/tmp/build/",
        "build.project_name": "Sk",
        "runtime.platform.path": "/plat/",
        "tools.esptool_py.path": "/plat/tools/esptool",
        "tools.esptool_py.cmd": "esptool",
        "tools.esptool_py.upload.pattern": '"{path}/{cmd}" {upload.pattern_args}',
        "tools.esptool_py.upload.pattern_args": (
            '--chip {build.mcu} --port "{serial.port}" --baud {upload.speed} end'
        ),
    }
    s = expand_upload_pattern(exp, "/dev/cuUSB0")
    assert "{path}" not in s
    assert "{cmd}" not in s
    assert "{upload.pattern_args}" not in s
    assert "/plat/tools/esptool/esptool" in s
    assert '--chip esp32s3 --port "/dev/cuUSB0"' in s


def test_expand_upload_windows_uses_cmd_windows() -> None:
    exp: dict[str, str] = {
        "runtime.os": "windows",
        "upload.tool": "esptool_py",
        "upload.speed": "115200",
        "upload.flags": "",
        "upload.erase_cmd": "",
        "upload.extra_flags": "",
        "build.mcu": "esp32",
        "build.bootloader_addr": "0x1000",
        "build.path": "C:/b/",
        "build.project_name": "X",
        "runtime.platform.path": "C:/p/",
        "tools.esptool_py.path": "C:/p/tools/esptool",
        "tools.esptool_py.cmd": "esptool",
        "tools.esptool_py.cmd.windows": "esptool.exe",
        "tools.esptool_py.upload.pattern": "{path}/{cmd} {upload.pattern_args}",
        "tools.esptool_py.upload.pattern_args": "--chip {build.mcu} --baud {upload.speed} z",
    }
    s = expand_upload_pattern(exp, "COM3").replace("\\", "/")
    assert "C:/p/tools/esptool/esptool.exe" in s
