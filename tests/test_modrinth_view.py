"""Threading and launch regression checks, with no live API calls or game launch."""

import json
import threading
import time
from types import SimpleNamespace

import pytest

from main import HexLauncher
from src.hexlauncher.core.modrinth import ModrinthError
from src.hexlauncher.i18n import tr


def pump(root, condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert condition()


def test_search_worker_and_render_thread(app_root, monkeypatch):
    view = app_root.modrinth_view
    app_root.loader_var.set("Fabric")
    app_root.version_var.set("1.21")
    view.kind_var.set("Mods")
    view.search_var.set("sodium")
    threads = []
    rendered = []

    def search(query, loader, version, **kwargs):
        threads.append(threading.current_thread())
        assert (query, loader, version) == ("sodium", "Fabric", "1.21")
        return [{"title": "Sodium"}]

    monkeypatch.setattr(view.client, "search_mods", search)
    monkeypatch.setattr(view, "_render_mod_card", lambda *args: rendered.append(threading.current_thread()))
    view.do_search()
    pump(app_root, lambda: bool(rendered))
    assert threads[0] is not threading.main_thread()
    assert threads[0].daemon
    assert rendered[0] is threading.main_thread()


def test_search_stale_response_ignored(app_root, monkeypatch):
    view = app_root.modrinth_view
    app_root.loader_var.set("Fabric")
    app_root.version_var.set("1.21")
    view.search_var.set("first")
    gate, entered = threading.Event(), threading.Event()
    rendered = []

    def search(query, *args, **kwargs):
        if query == "first":
            entered.set()
            gate.wait(2)
        return [{"title": query}]

    monkeypatch.setattr(view.client, "search_mods", search)
    monkeypatch.setattr(view, "_render_mod_card", lambda hit, *args: rendered.append(hit["title"]))
    view.do_search()
    assert entered.wait(1)
    view.search_var.set("second")
    view.do_search()
    pump(app_root, lambda: rendered == ["second"])
    gate.set()
    pump(app_root, lambda: not app_root.queue.empty())
    app_root._process_queue()
    assert rendered == ["second"]


def test_install_failure_message_survives_worker_exception(app_root):
    view = app_root.modrinth_view

    def task():
        assert threading.current_thread() is not threading.main_thread()
        raise ModrinthError("SHA-512 incorrecto")

    view._run_install(task)
    pump(app_root, lambda: not view._busy)
    assert "SHA-512 incorrecto" in view.status_label.cget("text")


def test_busy_install_blocks_launch(app_root, monkeypatch):
    view = app_root.modrinth_view
    view._busy = True
    try:
        monkeypatch.setattr(app_root, "_launch_game", lambda *args: pytest.fail("Launch must be blocked"))
        app_root._start_launch_thread()
        assert not app_root._is_launching
    finally:
        view._busy = False


def test_thread_after_queue_never_calls_tk_on_worker(app_root):
    called = []
    worker = threading.Thread(
        target=lambda: app_root.after(1, lambda: called.append(threading.current_thread())), daemon=True
    )
    worker.start()
    worker.join(1)
    pump(app_root, lambda: bool(called))
    assert called == [threading.main_thread()]


def test_filters_clear_old_install_cards(app_root):
    view = app_root.modrinth_view
    view._render_mod_card({"title": "Old", "project_id": "old"}, "1.21", "Fabric")
    assert view.results_scroll.winfo_children()
    generation = view._search_generation
    view.update_filter_badge()
    assert view._search_generation == generation + 1
    assert not view.results_scroll.winfo_children()


def test_install_uses_selected_instance_destination(app_root, monkeypatch, tmp_path):
    view = app_root.modrinth_view
    destination = tmp_path / "instance" / "mods"
    calls = []
    monkeypatch.setattr(app_root, "_mods_folder_for", lambda loader, version: str(destination))
    monkeypatch.setattr(view, "_run_install", lambda task: task())
    monkeypatch.setattr(
        view.client,
        "install_mod",
        lambda project, loader, version, directory, progress: calls.append(directory),
    )
    view._install_project("project", "Example", "Fabric", "1.21", "mod")
    assert calls == [destination]


def test_delete_uses_transactional_uninstall(app_root, monkeypatch, tmp_path):
    view = app_root.modrinth_view
    path = tmp_path / "instance" / "mods" / "example.jar"
    calls = []
    monkeypatch.setattr(view.client, "uninstall_mod", lambda directory, name: calls.append((directory, name)))
    monkeypatch.setattr(view, "refresh_installed_mods", lambda: None)
    monkeypatch.setattr(app_root, "_update_mods_count", lambda: None)
    view._delete_mod(path)
    assert calls == [(path.parent, path.name)]


def test_username_validation_keeps_stop_accessible(app_root):
    bar = app_root.bottom_bar
    previous = app_root._mc_process
    app_root._mc_process = object()
    try:
        bar.set_play_enabled(False)
        assert bar.play_button.cget("state") == "normal"
        assert bar.play_button.cget("text") == tr("■   DETENER")
    finally:
        app_root._mc_process = previous
        bar.set_running_state(False)


def test_avatar_worker_dispatches_image_to_ui(app_root, monkeypatch, tmp_path):
    from PIL import Image

    avatar = app_root.bottom_bar.avatar
    Image.new("RGBA", (8, 8), "cyan").save(tmp_path / "Steve.png")
    monkeypatch.setattr(avatar, "_cache_dir", str(tmp_path))
    applied = []
    monkeypatch.setattr(
        avatar,
        "_apply_ctk_image",
        lambda image, username: applied.append((threading.current_thread(), username)),
    )
    avatar._fetch_avatar("Steve")
    pump(app_root, lambda: bool(applied))
    assert applied == [(threading.main_thread(), "Steve")]


def test_launch_failure_is_not_overwritten(monkeypatch):
    messages = []
    launcher = SimpleNamespace(
        _download_jdk=lambda: (_ for _ in ()).throw(RuntimeError("download failed")),
        after=lambda delay, callback, *args: callback(*args),
        bottom_bar=SimpleNamespace(
            status_label=SimpleNamespace(configure=lambda **kw: messages.append(kw["text"])),
            progress_bar=SimpleNamespace(set=lambda value: None),
            set_play_enabled=lambda enabled: None,
        ),
        _check_installed=lambda version: None,
    )
    HexLauncher._launch_game(launcher, "Steve", "1.21", "fabric")
    assert messages[-1] == "Error: download failed"


def test_pack_launch_uses_instance_and_pinned_loader(tmp_path, monkeypatch):
    from minecraft_launcher_lib import mod_loader

    import main

    directory = tmp_path / "HexInstances" / "pack"
    directory.mkdir(parents=True)
    (directory / ".hexpack.json").write_text(
        json.dumps({"dependencies": {"minecraft": "1.21", "fabric-loader": "0.16.0"}}), encoding="utf-8"
    )
    commands, installed = [], []
    monkeypatch.setattr(main, "BASE_PATH", str(tmp_path))
    monkeypatch.setattr(
        main.minecraft_launcher_lib.install,
        "install_minecraft_version",
        lambda version, path, **kw: installed.append((version, path)),
    )
    loader = SimpleNamespace(
        is_minecraft_version_supported=lambda version: True,
        get_latest_loader_version=lambda version: pytest.fail("Pack must use pinned loader"),
        install=lambda version, path, **kw: (
            installed.append((version, path, kw["loader_version"])) or "fabric-loader-0.16.0-1.21"
        ),
    )
    monkeypatch.setattr(mod_loader, "get_mod_loader", lambda name: loader)
    monkeypatch.setattr(
        main.minecraft_launcher_lib.command,
        "get_minecraft_command",
        lambda version, path, options: commands.append((version, path, options)) or ["java"],
    )
    monkeypatch.setattr(main.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(wait=lambda: 0))
    launcher = SimpleNamespace(
        _download_jdk=lambda: None,
        after=lambda delay, callback, *args: callback(*args),
        settings=SimpleNamespace(
            get=lambda key: "" if key == "custom_java_path" else False,
            get_effective_jvm_args=lambda: ["-Xmx4G"],
        ),
        bottom_bar=SimpleNamespace(
            status_label=SimpleNamespace(configure=lambda **kw: None),
            progress_bar=SimpleNamespace(set=lambda value: None),
            set_play_enabled=lambda enabled: None,
            set_running_state=lambda enabled: None,
        ),
        _sync_mods=lambda *args: pytest.fail("Do not replace pack mods with the global library"),
        _check_installed=lambda version: None,
    )
    HexLauncher._launch_game(launcher, "Steve", "1.20.1", "forge", str(directory))
    assert installed == [("1.21", str(directory)), ("1.21", str(directory), "0.16.0")]
    assert commands[0][:2] == ("fabric-loader-0.16.0-1.21", str(directory))
    assert launcher._mc_process is None
