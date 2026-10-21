"""Offline coverage of release selection, corrupt downloads and rollback."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from src.hexlauncher.core.updater import (
    Release,
    check_update,
    cleanup_updates,
    download_update,
    replace_executable,
    version_key,
)

PAYLOAD = b"MZ\x00verified executable fixture"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class Response:
    status_code = 200

    def __init__(self, data=None, payload=PAYLOAD):
        self.data = data
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.data

    def iter_content(self, size):
        yield self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def release_data():
    return {
        "tag_name": "v0.8.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "HexLauncher.exe",
                "state": "uploaded",
                "size": len(PAYLOAD),
                "digest": f"sha256:{DIGEST}",
                "browser_download_url": "https://github.com/BillyHz/HexLauncher/releases/download/v0.8.0/HexLauncher.exe",
            }
        ],
    }


def client(response):
    return SimpleNamespace(get=lambda *args, **kwargs: response)


def test_stable_follows_prerelease_and_numeric_order():
    assert version_key("0.7.0-beta.1") < version_key("v0.7.0") < version_key("0.10.0")
    assert version_key("0.7.0-beta.9") < version_key("0.7.0-rc.1")
    with pytest.raises(ValueError):
        version_key("v0.8.0 & command")


def test_historical_release_tags_keep_prerelease_ordering():
    assert version_key("vAlpha0.7.0") == version_key("0.7.0-alpha.0")
    assert version_key("vBeta0.7.0") == version_key("0.7.0-beta.0")
    assert version_key("vRC0.7.0") == version_key("0.7.0-rc.0")
    assert version_key("vAlpha0.7.0") < version_key("0.7.0-beta.1") < version_key("v0.7.0")


@pytest.mark.parametrize("tag", ["vAlpha0.7.0", "vAlpha0.8.0", "vBeta0.8.0", "vRC0.8.0"])
def test_legacy_prerelease_marked_as_stable_does_not_trigger_update(tag):
    data = release_data()
    data["tag_name"] = tag
    assert check_update("0.7.0-beta.1", session=client(Response(data))) is None


@pytest.mark.parametrize("tag", ["latest", "HexLauncher release", "", None, 42])
def test_unknown_release_tag_is_ignored_instead_of_breaking_check(tag):
    data = release_data()
    data["tag_name"] = tag
    assert check_update("0.7.0-beta.1", session=client(Response(data))) is None


def test_release_selection_and_no_downgrades():
    session = client(Response(release_data()))
    assert check_update("0.7.0-beta.1", session).sha256 == DIGEST
    assert check_update("0.8.0", session) is None
    assert check_update("0.9.0", session) is None


@pytest.mark.parametrize("field", ["draft", "prerelease"])
def test_unpublished_and_prerelease_ignored(field):
    data = release_data()
    data[field] = True
    assert check_update("0.7.0-beta.1", session=client(Response(data))) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", None),
        ("digest", "sha256:bad"),
        ("size", 0),
        ("size", True),
        ("size", 201 * 1024 * 1024),
        (
            "browser_download_url",
            "http://github.com/BillyHz/HexLauncher/releases/download/v0.8.0/HexLauncher.exe",
        ),
        ("browser_download_url", "https://github.com/other/repo/releases/download/v0.8.0/HexLauncher.exe"),
    ],
)
def test_invalid_asset_refused(field, value):
    data = release_data()
    data["assets"][0][field] = value
    with pytest.raises(ValueError):
        check_update("0.7.0-beta.1", session=client(Response(data)))


def test_missing_release_is_not_an_error():
    response = Response()
    response.status_code = 404
    assert check_update(session=client(response)) is None


def test_prerelease_tag_is_ignored_even_if_marked_stable():
    data = release_data()
    data["tag_name"] = "v0.8.0-beta.1"
    assert check_update("0.7.0-beta.1", session=client(Response(data))) is None


def test_download_and_replacement_leave_user_files_intact(tmp_path):
    target = tmp_path / "HexLauncher.exe"
    target.write_bytes(b"MZold version")
    settings = tmp_path / "settings.json"
    settings.write_text("saved settings")
    release = Release("0.8.0", "https://github.com/asset", DIGEST, len(PAYLOAD))
    pending = download_update(release, target, session=client(Response()))
    restarted = []
    replace_executable(pending, target, DIGEST, restarted.append)
    assert target.read_bytes() == PAYLOAD
    assert (pending.parent / "previous.exe").read_bytes() == b"MZold version"
    assert settings.read_text() == "saved settings"
    assert restarted == [target]


@pytest.mark.parametrize("payload", [b"MZ" + b"x" * (len(PAYLOAD) - 2), PAYLOAD[:-1], PAYLOAD + b"extra"])
def test_failed_download_removes_staging_and_preserves_target(tmp_path, payload):
    target = tmp_path / "HexLauncher.exe"
    target.write_bytes(b"old")
    release = Release("0.8.0", "https://github.com/asset", DIGEST, len(PAYLOAD))
    with pytest.raises(ValueError):
        download_update(release, target, session=client(Response(payload=payload)))
    assert list(tmp_path.iterdir()) == [target]
    assert target.read_bytes() == b"old"


def test_hash_checked_again_before_replacing(tmp_path):
    target = tmp_path / "HexLauncher.exe"
    target.write_bytes(b"old")
    pending = tmp_path / "pending.exe"
    pending.write_bytes(b"MZtampered")
    with pytest.raises(ValueError):
        replace_executable(pending, target, DIGEST)
    assert target.read_bytes() == b"old"


def test_restart_failure_restores_backup(tmp_path):
    target = tmp_path / "HexLauncher.exe"
    target.write_bytes(b"old")
    stage = tmp_path / "stage"
    stage.mkdir()
    pending = stage / "pending.exe"
    pending.write_bytes(PAYLOAD)

    def fail_restart(path):
        raise OSError("cannot restart")

    with pytest.raises(OSError, match="cannot restart"):
        replace_executable(pending, target, DIGEST, fail_restart)
    assert target.read_bytes() == b"old"
    assert not (stage / "completed.json").exists()


def test_successful_update_cleanup_preserves_user_files(tmp_path):
    target = tmp_path / "HexLauncher.exe"
    target.write_bytes(b"MZold")
    settings = tmp_path / "settings.json"
    settings.write_text("settings")
    pending = download_update(
        Release("0.8.0", "https://github.com/asset", DIGEST, len(PAYLOAD)),
        target, session=client(Response()),
    )
    (pending.parent / "helper.exe").write_bytes(b"MZhelper")
    replace_executable(pending, target, DIGEST, lambda path: None)
    assert not cleanup_updates(target)
    assert not pending.parent.exists()
    assert target.read_bytes() == PAYLOAD
    assert settings.read_text() == "settings"
    assert not cleanup_updates(target)  # repeated startup is harmless


@pytest.mark.parametrize("extra", ["pending.exe", "error.txt", "user-world"])
def test_cleanup_retains_incomplete_failed_or_unknown_staging(tmp_path, extra):
    target = tmp_path / "HexLauncher.exe"
    stage = tmp_path / ".hex-update-test"
    stage.mkdir()
    (stage / "completed.json").write_text(json.dumps({"target": str(target.resolve())}))
    (stage / "previous.exe").write_bytes(b"backup")
    (stage / extra).write_bytes(b"retain")
    assert not cleanup_updates(target)
    assert (stage / "previous.exe").read_bytes() == b"backup"
    assert (stage / extra).read_bytes() == b"retain"


def test_cleanup_retries_locked_helper_before_removing_backup(tmp_path, monkeypatch):
    from pathlib import Path

    target = tmp_path / "HexLauncher.exe"
    stage = tmp_path / ".hex-update-test"
    stage.mkdir()
    helper = stage / "helper.exe"
    helper.write_bytes(b"helper")
    backup = stage / "previous.exe"
    backup.write_bytes(b"backup")
    (stage / "completed.json").write_text(json.dumps({"target": str(target.resolve())}))
    unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path == helper:
            raise PermissionError("helper is running")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked)
        assert cleanup_updates(target)
        assert backup.read_bytes() == b"backup"
    assert not cleanup_updates(target)
    assert not stage.exists()


def test_cleanup_does_not_touch_other_target_or_invalid_marker(tmp_path):
    target = tmp_path / "HexLauncher.exe"
    stage = tmp_path / ".hex-update-test"
    stage.mkdir()
    marker = stage / "completed.json"
    backup = stage / "previous.exe"
    backup.write_bytes(b"backup")
    for contents in ["invalid json", "[]", json.dumps({"target": "another.exe"})]:
        marker.write_text(contents)
        assert not cleanup_updates(target)
        assert backup.read_bytes() == b"backup"


def test_update_panel_requires_idle_launcher(app_root, monkeypatch):
    panel = app_root.settings_view.update_panel
    monkeypatch.setattr(panel, "enabled", True)
    monkeypatch.setattr(panel, "release", Release("0.8.0", "https://github.com/asset", DIGEST, len(PAYLOAD)))
    monkeypatch.setattr(app_root, "_is_launching", True)
    panel.install()
    assert not panel._busy
    assert not app_root._updating


def test_apply_releases_busy_state_before_requesting_close(monkeypatch, tmp_path):
    from src.hexlauncher.views import update_panel

    events = []
    panel = SimpleNamespace(_busy=True, _idle=lambda: True)

    def close():
        assert not panel._busy  # otherwise the close loop would wait forever
        events.append("closed")

    panel.launcher = SimpleNamespace(
        settings=SimpleNamespace(save=lambda: True), _on_close=close,
    )
    panel._failed = lambda message: pytest.fail(message)
    monkeypatch.setattr(update_panel, "start_update", lambda *args: events.append("helper started"))
    update_panel.UpdatePanel._apply(panel, tmp_path / "pending.exe", DIGEST)
    assert events == ["helper started", "closed"]


def test_update_preference_save_failure_restores_previous_value(app_root, monkeypatch):
    panel = app_root.settings_view.update_panel
    previous = app_root.settings.get("auto_check_updates")
    panel.automatic.set(not previous)
    monkeypatch.setattr(app_root.settings, "save", lambda: False)
    panel._save_preference()
    assert app_root.settings.get("auto_check_updates") == previous
    assert panel.automatic.get() == previous
