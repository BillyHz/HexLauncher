"""Local imports validate the complete selection and preserve existing mods."""

import json
import time
import zipfile
from pathlib import Path

import pytest

from src.hexlauncher.core.modrinth import ModrinthClient, ModrinthError


def make_jar(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({"id": path.stem, "version": "1"}))
    return path


def test_import_multiple_jars_preserves_existing_mods_and_registry(tmp_path):
    destination = tmp_path / "mods"
    destination.mkdir()
    existing = make_jar(destination / "existing.jar")
    registry = destination / ".hexmods.json"
    projects = {"managed": {"filename": existing.name, "version_id": "v1", "dependencies": {}}}
    registry.write_text(json.dumps({"format": 1, "projects": projects}))
    sources = [make_jar(tmp_path / name) for name in ("one.jar", "two.jar")]
    progress = []
    client = ModrinthClient()
    assert client.import_local_mods(sources, destination, lambda *args: progress.append(args)) == [
        "one.jar", "two.jar",
    ]
    assert progress == [(1, 2), (2, 2)]
    assert client.read_installed_mods(destination) == projects
    for source in sources:
        assert (destination / source.name).read_bytes() == source.read_bytes()
    assert existing.is_file()


def test_invalid_jar_rejects_entire_selection(tmp_path):
    good = make_jar(tmp_path / "good.jar")
    bad = tmp_path / "bad.jar"
    bad.write_bytes(b"not a jar")
    destination = tmp_path / "mods"
    with pytest.raises(ModrinthError, match="JAR"):
        ModrinthClient().import_local_mods([good, bad], destination)
    assert list(destination.iterdir()) == []
    assert good.exists()


def test_duplicate_name_does_not_overwrite_existing_mod(tmp_path):
    destination = tmp_path / "mods"
    destination.mkdir()
    existing = destination / "same.jar"
    existing.write_bytes(b"keep this file")
    source = make_jar(tmp_path / "same.jar")
    with pytest.raises(ModrinthError, match="Ya existe"):
        ModrinthClient().import_local_mods([source], destination)
    assert existing.read_bytes() == b"keep this file"


def test_publication_failure_restores_entire_selection(tmp_path, monkeypatch):
    from src.hexlauncher.core import modrinth

    destination = tmp_path / "mods"
    destination.mkdir()
    existing = make_jar(destination / "existing.jar")
    previous = existing.read_bytes()
    sources = [make_jar(tmp_path / name) for name in ("one.jar", "two.jar")]
    replace = modrinth.os.replace

    def fail_second(source, target):
        if Path(target) == destination / "two.jar":
            raise OSError("disk failure")
        replace(source, target)

    monkeypatch.setattr(modrinth.os, "replace", fail_second)
    with pytest.raises(ModrinthError, match="restauraron"):
        ModrinthClient().import_local_mods(sources, destination)
    assert list(destination.iterdir()) == [existing]
    assert existing.read_bytes() == previous


def test_local_import_uses_selected_destination_and_lists_files(app_root, monkeypatch, tmp_path):
    from src.hexlauncher.views import modrinth_view

    view = app_root.modrinth_view
    sources = [make_jar(tmp_path / name) for name in ("one.jar", "two.jar")]
    destination = tmp_path / "selected-instance" / "mods"
    monkeypatch.setattr(app_root.loader_var, "get", lambda: "Fabric")
    monkeypatch.setattr(app_root.version_var, "get", lambda: "1.21")
    monkeypatch.setattr(app_root, "_mods_folder_for", lambda *args: str(destination))
    monkeypatch.setattr(modrinth_view.filedialog, "askopenfilenames", lambda **kwargs: tuple(map(str, sources)))
    view._import_mods()
    deadline = time.monotonic() + 5
    while view._busy and time.monotonic() < deadline:
        app_root.update()
        time.sleep(0.01)
    assert not view._busy
    assert sorted(path.name for path in destination.glob("*.jar")) == ["one.jar", "two.jar"]
    assert "2" in view.status_label.cget("text")
    assert len(view.results_scroll.winfo_children()) == 2


def test_vanilla_import_explains_loader_before_opening_picker(app_root, monkeypatch):
    from src.hexlauncher.views import modrinth_view
    from src.hexlauncher.i18n import tr

    view = app_root.modrinth_view
    monkeypatch.setattr(app_root.loader_var, "get", lambda: "Vanilla")
    monkeypatch.setattr(app_root.version_var, "get", lambda: "1.21")
    monkeypatch.setattr(
        modrinth_view.filedialog, "askopenfilenames",
        lambda **kwargs: pytest.fail("Choose a loader before selecting files"),
    )
    view._import_mods()
    assert view.status_label.cget("text") == tr("Selecciona Fabric, Forge o NeoForge para instalar mods.")
