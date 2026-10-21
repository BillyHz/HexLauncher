"""Resource packs stay zipped, preserve existing files and follow instance selection."""

import json
import time
import zipfile
from pathlib import Path

import pytest

from src.hexlauncher.core.resource_packs import import_resource_pack


def make_pack(path, metadata="pack.mcmeta"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(metadata, json.dumps({"pack": {"pack_format": 15, "description": "Test"}}))
        archive.writestr("assets/minecraft/textures/test.png", b"texture")


def test_import_preserves_zip_and_existing_pack(tmp_path):
    source = tmp_path / "textures.zip"
    make_pack(source)
    game = tmp_path / "game"
    first = import_resource_pack(source, game)
    second = import_resource_pack(source, game)
    assert first.name == "textures.zip"
    assert second.name == "textures (1).zip"
    assert first.read_bytes() == second.read_bytes() == source.read_bytes()
    assert not (game / "assets").exists()
    assert {path.name for path in first.parent.iterdir()} == {first.name, second.name}


@pytest.mark.parametrize("metadata", ["nested/pack.mcmeta", "other.json"])
def test_missing_root_metadata_does_not_install(tmp_path, metadata):
    source = tmp_path / "invalid.zip"
    make_pack(source, metadata)
    with pytest.raises(ValueError):
        import_resource_pack(source, tmp_path / "game")
    assert list((tmp_path / "game" / "resourcepacks").iterdir()) == []


def test_invalid_json_does_not_install(tmp_path):
    source = tmp_path / "invalid.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("pack.mcmeta", "not json")
    with pytest.raises(ValueError):
        import_resource_pack(source, tmp_path / "game")
    assert not list((tmp_path / "game" / "resourcepacks").iterdir())


def test_size_limit_preserves_existing_files(tmp_path, monkeypatch):
    from src.hexlauncher.core import resource_packs

    source = tmp_path / "large.zip"
    make_pack(source)
    monkeypatch.setattr(resource_packs, "MAX_PACK_SIZE", 10)
    with pytest.raises(ValueError):
        import_resource_pack(source, tmp_path / "game")
    assert not (tmp_path / "game").exists()


def test_ui_import_uses_selected_instance(app_root, tmp_path, monkeypatch):
    from src.hexlauncher.views import resource_packs_view

    source = tmp_path / "textures.zip"
    make_pack(source)
    selected = tmp_path / "selected-pack"
    monkeypatch.setattr(app_root, "_game_directory", lambda: str(selected))
    view = app_root.resource_packs_view
    monkeypatch.setattr(resource_packs_view.filedialog, "askopenfilename", lambda **kwargs: str(source))
    view.import_local()
    deadline = time.monotonic() + 5
    while app_root.modrinth_view._busy and time.monotonic() < deadline:
        app_root.update()
        time.sleep(0.01)
    assert not app_root.modrinth_view._busy
    assert (selected / "resourcepacks" / source.name).exists()
    assert "textures.zip" in app_root.bottom_bar.status_label.cget("text")
    assert any("textures.zip" in label.cget("text") for label in view.results_scroll.winfo_children())
    assert view.import_button.cget("state") == "normal"


def test_ui_folder_follows_selected_installation(app_root, tmp_path, monkeypatch):
    selected = tmp_path / "instance"
    opened = []
    monkeypatch.setattr(app_root, "_game_directory", lambda: str(selected))
    monkeypatch.setattr(app_root, "_open_dir", opened.append)
    app_root.resource_packs_view.open_folder()
    assert opened == [str(Path(selected, "resourcepacks"))]
