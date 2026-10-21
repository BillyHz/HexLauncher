"""Server UI concurrency and shutdown checks without exposing a real tunnel."""

import threading
import time

import pytest

from src.hexlauncher.i18n import tr
from src.hexlauncher.views import server_view


def pump(root, condition):
    deadline = time.monotonic() + 4
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert condition()


class FakeManager:
    def __init__(self):
        self.is_running = False
        self.calls = []
        self.callback = None

    def setup_server(self, version, loader, **kwargs):
        self.calls.append(("setup", threading.current_thread(), version, loader))

    def ensure_playit_binary(self):
        self.calls.append(("download", threading.current_thread()))

    def start_server(self, ram, on_log, on_status):
        self.calls.append(("start", threading.current_thread(), ram))
        self.is_running = True
        self.callback = on_status
        on_log("[Minecraft] Done!")
        on_status("claim", "https://playit.gg/claim/example")
        on_status("address", "friends.at.ply.gg:12345")

    def stop_server(self):
        self.calls.append(("stop", threading.current_thread()))
        self.is_running = False


@pytest.fixture
def view(app_root, monkeypatch):
    view = app_root.server_view
    manager = FakeManager()
    monkeypatch.setattr(view, "manager", manager)
    monkeypatch.setattr(server_view, "safe_ram_limit", lambda: 8)
    view.version_var.set("1.21.1")
    view.loader_var.set("Paper")
    view.ram_var.set("4 GB")
    view._cancel.clear()
    view._closing = view._starting = view._stopping = False
    yield view
    if view._operation_thread and view._operation_thread.is_alive():
        view._operation_thread.join(timeout=2)
    manager.is_running = False
    view._closing = view._starting = view._stopping = False
    view._set_controls()


def test_start_stop_and_events_are_marshaled_to_ui(app_root, view, monkeypatch):
    applied = []
    original = view._apply_event

    def apply(kind, value):
        applied.append(threading.current_thread())
        original(kind, value)

    monkeypatch.setattr(view, "_apply_event", apply)
    view.toggle_server()
    pump(app_root, lambda: not view._starting and view._public_address)
    assert all(call[1].daemon and call[1] is not threading.main_thread() for call in view.manager.calls)
    assert applied and all(thread is threading.main_thread() for thread in applied)
    assert view.copy_button.cget("state") == "normal"
    assert view.claim_button.cget("state") == "normal"
    assert view.start_button.cget("text") == tr("Detener Servidor")
    view.toggle_server()
    pump(app_root, lambda: not view._stopping)
    assert view.manager.calls[-1][0] == "stop"
    assert view.manager.calls[-1][1].daemon
    assert not view.manager.is_running


def test_shutdown_during_setup_cancels_start_and_waits_off_ui(app_root, view, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def setup(*args, **kwargs):
        entered.set()
        release.wait(timeout=3)

    monkeypatch.setattr(view.manager, "setup_server", setup)
    view.toggle_server()
    assert entered.wait(timeout=1)
    completed = []
    view.shutdown(lambda: completed.append(threading.current_thread()))
    assert not completed
    release.set()
    pump(app_root, lambda: bool(completed))
    assert completed == [threading.main_thread()]
    assert [call[0] for call in view.manager.calls] == ["stop"]


def test_insufficient_memory_prevents_any_download(view, monkeypatch):
    monkeypatch.setattr(server_view, "safe_ram_limit", lambda: 1)
    view.toggle_server()
    assert not view.manager.calls
    assert "RAM" in view.status_label.cget("text")


def test_shutdown_failure_keeps_window_available(app_root, view, monkeypatch):
    def fail():
        raise OSError("owned process still alive")

    monkeypatch.setattr(view.manager, "stop_server", fail)
    completed = []
    view.shutdown(lambda: completed.append(True))
    pump(app_root, lambda: not view._closing)
    assert not completed
    assert "owned process still alive" in view.status_label.cget("text")
    assert app_root.winfo_exists()


def test_launcher_close_waits_for_server_shutdown(app_root, view, monkeypatch):
    view.manager.is_running = True
    completions, destroyed = [], []
    monkeypatch.setattr(view, "shutdown", lambda callback: completions.append(callback))
    monkeypatch.setattr(app_root, "destroy", lambda: destroyed.append(threading.current_thread()))
    app_root._on_close()
    assert completions and not destroyed
    completions[0]()
    assert destroyed == [threading.main_thread()]


@pytest.mark.parametrize("loader", ["Forge", "NeoForge"])
def test_modded_loaders_available_and_setup_runs_in_worker(app_root, view, loader):
    assert loader in view.loader_menu.cget("values")
    view.loader_var.set(loader)
    view.toggle_server()
    pump(app_root, lambda: not view._starting)
    setup = view.manager.calls[0]
    assert setup[0] == "setup" and setup[3] == loader.lower()
    assert setup[1] is not threading.main_thread() and setup[1].daemon
    assert app_root.settings.get("server_loader") == loader.lower()
    view.toggle_server()
    pump(app_root, lambda: not view._stopping)
