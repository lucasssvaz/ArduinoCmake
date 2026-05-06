import hashlib

from acmake.fqbn import FQBN


def test_parse_basic():
    f = FQBN.parse("arduino:avr:uno")
    assert f.vendor == "arduino"
    assert f.arch == "avr"
    assert f.board_id == "uno"
    assert f.options == {}


def test_parse_options():
    f = FQBN.parse("esp32:esp32:esp32dev:PartitionScheme=default,CPUFreq=240")
    assert f.board_id == "esp32dev"
    assert f.options == {"CPUFreq": "240", "PartitionScheme": "default"}


def test_parse_options_fourth_segment_only_not_split_on_extra_colons():
    """Options live in the 4th colon segment; values may contain ':' (split max 3)."""
    f = FQBN.parse("a:b:c:K=v:with:colons,Other=1")
    assert f.options == {"K": "v:with:colons", "Other": "1"}


def test_parse_extended_esp32s3_style():
    f = FQBN.parse(
        "espressif:esp32:esp32s3:"
        "USBMode=default,PartitionScheme=esp_sr_16,FlashSize=16M,FlashMode=dio"
    )
    assert f.vendor == "espressif"
    assert f.arch == "esp32"
    assert f.board_id == "esp32s3"
    assert f.options == {
        "FlashMode": "dio",
        "FlashSize": "16M",
        "PartitionScheme": "esp_sr_16",
        "USBMode": "default",
    }


def test_object_cache_key_is_sha256_prefix_of_fqbn_and_core_version() -> None:
    f = FQBN.parse("arduino:avr:uno")
    want = hashlib.sha256(f"{f.to_string()}\0".encode("utf-8")).hexdigest()[:32]
    assert f.object_cache_key() == want
    want2 = hashlib.sha256(f"{f.to_string()}\0rel2".encode("utf-8")).hexdigest()[:32]
    assert f.object_cache_key(core_version="rel2") == want2


def test_build_path_segment_sanitizes_for_filesystem():
    f = FQBN.parse(
        "espressif:esp32:esp32s3:"
        "USBMode=default,PartitionScheme=esp_sr_16,FlashSize=16M,FlashMode=dio"
    )
    seg = f.build_path_segment()
    assert ":" not in seg and "," not in seg and "=" not in seg
    assert seg.startswith("espressif_esp32_esp32s3_")
    assert "FlashMode_dio" in seg
    assert "FlashSize_16M" in seg
