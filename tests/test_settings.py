"""Tests for the Settings persistence class."""

import json
import os

import pytest

from src.hexlauncher.utils.settings import DEFAULTS, Settings


@pytest.fixture
def tmp_settings_path(tmp_path):
    """Return a path inside tmp_path for settings.json."""
    return os.path.join(str(tmp_path), "settings.json")


def test_defaults_when_file_missing(tmp_settings_path):
    s = Settings(os.path.dirname(tmp_settings_path))
    assert s.get("username") == ""
    assert s.get("last_version") == ""
    assert s.get("last_loader") == "Vanilla"
    assert s.get("jvm_args") == ["-Xmx4G", "-Xms2G"]
    assert s.get("ram_gb") == 4
    assert s.get("window_geometry") == DEFAULTS["window_geometry"]


def test_save_and_load_roundtrip(tmp_settings_path):
    base = os.path.dirname(tmp_settings_path)
    s1 = Settings(base)
    s1.set("username", "Steve_42")
    s1.set("last_version", "1.21")
    s1.set("last_loader", "Fabric")
    s1.set("ram_gb", 8)
    s1.save()

    assert os.path.exists(tmp_settings_path)

    s2 = Settings(base)
    assert s2.get("username") == "Steve_42"
    assert s2.get("last_version") == "1.21"
    assert s2.get("last_loader") == "Fabric"
    assert s2.get("ram_gb") == 8
    # Defaults preserved for fields not set
    assert s2.get("jvm_args") == ["-Xmx4G", "-Xms2G"]


def test_corrupted_file_falls_back_to_defaults(tmp_settings_path):
    base = os.path.dirname(tmp_settings_path)
    with open(tmp_settings_path, "w") as f:
        f.write("{ this is not json :::")
    s = Settings(base)
    assert s.get("username") == ""


def test_partial_file_merges_with_defaults(tmp_settings_path):
    base = os.path.dirname(tmp_settings_path)
    with open(tmp_settings_path, "w") as f:
        json.dump({"username": "Alex"}, f)
    s = Settings(base)
    assert s.get("username") == "Alex"
    assert s.get("last_loader") == "Vanilla"  # from defaults


def test_non_dict_json_uses_defaults(tmp_settings_path):
    base = os.path.dirname(tmp_settings_path)
    with open(tmp_settings_path, "w") as f:
        json.dump([1, 2, 3], f)
    s = Settings(base)
    assert s.get("username") == ""


def test_all_defaults_keys_present():
    """DEFAULTS debe tener todas las keys esperadas."""
    for key in ("username", "last_version", "last_loader", "jvm_args", "window_geometry", "ram_gb"):
        assert key in DEFAULTS, f"DEFAULTS missing key: {key}"


def test_effective_jvm_args(tmp_settings_path):
    base = os.path.dirname(tmp_settings_path)
    s = Settings(base)
    s.set("ram_gb", 6)
    s.set("custom_jvm_args", "-XX:+UseG1GC")
    args = s.get_effective_jvm_args()
    assert "-Xmx6G" in args
    assert "-Xms3G" in args
    assert "-XX:+UseG1GC" in args


def test_invalid_loaded_values_use_independent_defaults(tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "ram_gb": True,
                "last_loader": "Unknown",
                "username": 42,
                "close_on_launch": "false",
                "window_geometry": "bad",
                "jvm_args": [17],
                "custom_jvm_args": '-Dpath="unclosed',
                "allow_multi_instance": True,
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(str(tmp_path))
    for key in DEFAULTS:
        assert settings.get(key) == DEFAULTS[key]
    assert "allow_multi_instance" not in settings.data
    retrieved = settings.get("jvm_args")
    retrieved.append("changed")
    assert settings.get("jvm_args") == DEFAULTS["jvm_args"]


def test_save_failure_preserves_existing_file(tmp_path, monkeypatch):
    settings = Settings(str(tmp_path))
    settings.set("username", "Before")
    assert settings.save()
    original = (tmp_path / "settings.json").read_bytes()
    settings.set("username", "After")

    def fail_replace(*_args):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", fail_replace)
    assert not settings.save()
    assert (tmp_path / "settings.json").read_bytes() == original
    assert not list(tmp_path.glob(".settings-*.tmp"))


def test_jvm_args_preserve_windows_paths_and_spaces(tmp_path):
    settings = Settings(str(tmp_path))
    settings.set("custom_jvm_args", r'-Dpath="C:\Program Files\Java" -Dother=C:\Java -XX:+UseG1GC')
    assert settings.get_effective_jvm_args()[2:] == [
        r"-Dpath=C:\Program Files\Java",
        r"-Dother=C:\Java",
        "-XX:+UseG1GC",
    ]


@pytest.mark.parametrize(
    "key,value",
    [
        ("ram_gb", 0),
        ("ram_gb", 33),
        ("ram_gb", True),
        ("last_loader", "invalid"),
        ("custom_jvm_args", '"unclosed'),
    ],
)
def test_invalid_setting_rejected(tmp_path, key, value):
    settings = Settings(str(tmp_path))
    with pytest.raises(ValueError):
        settings.set(key, value)
    assert settings.get(key) == DEFAULTS[key]
