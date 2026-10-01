"""Order-sensitive version queries: stale responses must never update selection."""

import threading
from types import SimpleNamespace

from minecraft_launcher_lib import mod_loader

import main

FETCH = main.HexLauncher._fetch_versions


def test_old_release_refresh_ignored(monkeypatch):
    queued, applied = [], []
    launcher = SimpleNamespace(
        _versions_request_id=2,
        _releases=["current"],
        after=lambda delay, callback: queued.append(callback),
        _update_version_list=lambda: applied.append(True),
    )
    monkeypatch.setattr(
        main.minecraft_launcher_lib.utils, "get_version_list", lambda: [{"id": "stale", "type": "release"}]
    )
    FETCH(launcher, 1)
    for callback in queued:
        callback()
    assert launcher._releases == ["current"]
    assert not applied


def test_latest_refresh_applies_on_ui_callback(monkeypatch):
    queued, applied = [], []
    launcher = SimpleNamespace(
        _versions_request_id=2,
        _releases=[],
        after=lambda delay, callback: queued.append(callback),
        _update_version_list=lambda: applied.append(True),
    )
    monkeypatch.setattr(
        main.minecraft_launcher_lib.utils,
        "get_version_list",
        lambda: [{"id": "1.21", "type": "release"}, {"id": "snapshot", "type": "snapshot"}],
    )
    FETCH(launcher, 2)
    assert launcher._releases == []
    queued[0]()
    assert launcher._releases == ["1.21"]
    assert applied == [True]


def test_loader_response_cannot_override_newer_selection(monkeypatch):
    queued, applied = [], []
    loader_name = ["Fabric"]
    gates = {"fabric": threading.Event(), "forge": threading.Event()}
    entered = {"fabric": threading.Event(), "forge": threading.Event()}
    launcher = SimpleNamespace(
        _filter_request_id=0,
        _releases=["1.21", "1.20.1"],
        _is_launching=False,
        _mc_process=None,
        loader_var=SimpleNamespace(get=lambda: loader_name[0]),
        settings=SimpleNamespace(get=lambda key: ""),
        bottom_bar=SimpleNamespace(status_label=SimpleNamespace(configure=lambda **kw: None)),
        after=lambda delay, callback: queued.append(callback),
        _populate_menu=lambda versions: applied.append(versions),
    )

    def get_loader(name):
        def supported(stable):
            entered[name].set()
            gates[name].wait(2)
            return ["1.21"] if name == "fabric" else ["1.20.1"]

        return SimpleNamespace(get_minecraft_versions=supported)

    monkeypatch.setattr(mod_loader, "get_mod_loader", get_loader)
    main.HexLauncher._update_version_list(launcher)
    assert entered["fabric"].wait(1)
    loader_name[0] = "Forge"
    main.HexLauncher._update_version_list(launcher)
    assert entered["forge"].wait(1)
    gates["forge"].set()
    gates["fabric"].set()
    # Workers are bounded by the gates, with no network calls.
    import time

    deadline = time.monotonic() + 2
    while len(queued) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(queued) == 2
    for callback in queued:
        callback()
    assert applied == [["1.20.1"]]
