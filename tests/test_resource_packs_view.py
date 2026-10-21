"""Texture browsing runs off Tk and follows version and installation changes."""

import threading
from pathlib import Path

import pytest

from src.hexlauncher.i18n import tr
from tests.test_modrinth_view import pump
from tests.test_resource_packs import make_pack


@pytest.fixture
def textures(app_root, monkeypatch, tmp_path):
    view = app_root.resource_packs_view
    monkeypatch.setattr(app_root.version_var, "get", lambda: "1.21.1")
    monkeypatch.setattr(app_root, "_game_directory", lambda: str(tmp_path / "selected-instance"))
    monkeypatch.setattr(view, "_mode", "empty")
    view.refresh_context()
    return view


def test_dedicated_tab_and_search_thread(textures, app_root, monkeypatch):
    app_root.switch_view("textures")
    assert app_root.current_view == "textures"
    assert app_root.nav_tabs["textures"].is_active
    called, rendered = [], []

    def search(query, loader, version, **kwargs):
        called.append(threading.current_thread())
        assert loader == ""
        assert version == "1.21.1"
        assert kwargs["project_type"] == "resourcepack"
        return [{"title": "Pack"}]

    monkeypatch.setattr(textures.client, "search_mods", search)
    monkeypatch.setattr(textures, "_render_card", lambda *args: rendered.append(threading.current_thread()))
    textures.search_var.set("")  # empty searches explore the catalogue
    textures.do_search()
    pump(app_root, lambda: bool(rendered))
    assert called[0] is not threading.main_thread()
    assert rendered[0] is threading.main_thread()


def test_changing_version_discards_pending_search(textures, app_root, monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    rendered, finished = [], threading.Event()

    def search(*args, **kwargs):
        entered.set()
        gate.wait(2)
        finished.set()
        return [{"title": "Old version"}]

    monkeypatch.setattr(textures.client, "search_mods", search)
    monkeypatch.setattr(textures, "_render_card", lambda *args: rendered.append(args))
    textures.do_search()
    assert entered.wait(1)
    monkeypatch.setattr(app_root.version_var, "get", lambda: "1.20.1")
    textures.refresh_context()
    gate.set()
    assert finished.wait(1)
    pump(app_root, lambda: not app_root.queue.empty())
    app_root._process_queue()
    assert not rendered


def test_install_captures_destination_and_shares_operation_lock(textures, app_root, monkeypatch, tmp_path):
    from src.hexlauncher.views import resource_packs_view

    gate, entered = threading.Event(), threading.Event()
    calls = []

    def install(client, project, version, directory, progress):
        calls.append((project, version, directory, threading.current_thread()))
        entered.set()
        gate.wait(2)
        path = directory / "resourcepacks" / "downloaded.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        make_pack(path)
        return path

    monkeypatch.setattr(resource_packs_view, "install_resource_pack", install)
    textures.install_project("project", "1.21.1")
    try:
        assert entered.wait(1)
        assert app_root.modrinth_view._busy
        assert not app_root.settings_view.update_panel._idle()
        app_root._start_launch_thread()
        assert not app_root._is_launching
    finally:
        gate.set()
    pump(app_root, lambda: not textures._busy)
    assert not app_root.modrinth_view._busy
    assert calls[0][:3] == ("project", "1.21.1", tmp_path / "selected-instance")
    assert calls[0][3] is not threading.main_thread()
    assert "downloaded.zip" in textures.status_label.cget("text")
    assert any("downloaded.zip" in label.cget("text") for label in textures.results_scroll.winfo_children())


def test_failure_releases_lock_and_displays_error(textures, app_root, monkeypatch):
    from src.hexlauncher.views import resource_packs_view

    def fail(*args):
        raise ValueError("SHA-512 incorrecto")

    monkeypatch.setattr(resource_packs_view, "install_resource_pack", fail)
    textures.install_project("project", "1.21.1")
    pump(app_root, lambda: not textures._busy)
    assert not app_root.modrinth_view._busy
    assert "SHA-512" in textures.status_label.cget("text")
    assert textures.import_button.cget("state") == "normal"


def test_local_import_and_folder_use_selected_instance(textures, app_root, monkeypatch, tmp_path):
    from src.hexlauncher.views import resource_packs_view

    source = tmp_path / "local.zip"
    make_pack(source)
    monkeypatch.setattr(resource_packs_view.filedialog, "askopenfilename", lambda **kwargs: str(source))
    textures.import_local()
    pump(app_root, lambda: not textures._busy)
    assert (tmp_path / "selected-instance" / "resourcepacks" / "local.zip").exists()
    opened = []
    monkeypatch.setattr(app_root, "_open_dir", opened.append)
    textures.open_folder()
    assert opened == [str(tmp_path / "selected-instance" / "resourcepacks")]


def test_stale_card_cannot_install_for_another_version(textures, monkeypatch):
    monkeypatch.setattr(textures, "_run_install", lambda task: pytest.fail("Stale card must not install"))
    textures.install_project("project", "1.20.1")
    assert textures.status_label.cget("text") == tr("La versión cambió. Busca de nuevo antes de instalar.")


def test_instance_change_clears_search_even_when_minecraft_version_matches(textures, app_root, monkeypatch, tmp_path):
    textures._mode = "search"
    generation = textures._search_generation
    monkeypatch.setattr(app_root, "_game_directory", lambda: str(tmp_path / "another-instance"))
    textures.refresh_context()
    assert textures._search_generation > generation
    assert textures._context == ("1.21.1", str(Path(tmp_path / "another-instance").resolve()))


def test_texture_navigation_translates_when_language_changes(app_root):
    previous = app_root.settings.get("language")
    try:
        assert app_root.change_language("es")
        assert app_root.nav_tabs["textures"].cget("text") == "▧  Texturas"
        assert app_root.change_language("en")
        assert app_root.nav_tabs["textures"].cget("text") == "▧  Textures"
    finally:
        app_root.change_language(previous)
