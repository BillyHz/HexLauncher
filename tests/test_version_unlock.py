"""Explain pack-pinned versions and allow returning to the regular installation."""

import pytest

from src.hexlauncher.i18n import tr


@pytest.fixture
def pinned(app_root, tmp_path, monkeypatch):
    root = app_root
    pack = tmp_path / "pack"
    (pack / "mods").mkdir(parents=True)
    marker = pack / "mods" / "keep.jar"
    marker.write_bytes(b"keep")
    monkeypatch.setattr(root, "_update_version_list", lambda: None)
    monkeypatch.setattr(root, "_update_mods_count", lambda: None)
    root.modrinth_view._activate_pack(
        str(pack), {"dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.16"}}
    )
    yield root, marker
    root.settings.set("active_instance_dir", "")
    root.bottom_bar.loader_menu.configure(state="normal")
    root.bottom_bar.version_combo.configure(state="normal")
    root.bottom_bar.show_pinned_version()


def test_disabled_click_explains_fixed_version(pinned):
    root, _ = pinned
    root.bottom_bar.version_combo._clicked()
    assert root.bottom_bar.version_combo._active_dropdown is None
    assert "1.21.1" in root.bottom_bar.pack_notice.cget("text")
    assert root.bottom_bar.status_label.cget("text") == tr(
        "El modpack fija esta versión. Usa instalación habitual para cambiarla."
    )


def test_standard_button_unlocks_version_without_changing_pack(pinned):
    root, marker = pinned
    root.bottom_bar.standard_instance_button.invoke()
    assert root.settings.get("active_instance_dir") == ""
    selector = root.bottom_bar.version_combo
    assert selector.cget("state") == "normal"
    selector.configure(values=["1.21.1", "1.20.1"])
    selector._clicked()
    assert selector._active_dropdown is not None
    selector._active_dropdown._on_select("1.20.1")
    assert root.version_var.get() == "1.20.1"
    assert marker.read_bytes() == b"keep"


def test_failed_save_keeps_pack_and_version_locked(pinned, monkeypatch):
    root, marker = pinned
    previous = root.settings.get("active_instance_dir")
    monkeypatch.setattr(root.settings, "save", lambda: False)
    root.bottom_bar.standard_instance_button.invoke()
    assert root.settings.get("active_instance_dir") == previous
    assert root.bottom_bar.version_combo.cget("state") == "disabled"
    assert marker.read_bytes() == b"keep"
