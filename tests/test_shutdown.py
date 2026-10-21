"""Closing must leave file-writing workers and the UI queue alive."""

from types import SimpleNamespace

import pytest

from main import HexLauncher


@pytest.mark.parametrize("operation", ["mods", "launch", "update"])
def test_close_waits_for_file_operations_then_shuts_down(operation):
    callbacks, cancelled, events = {}, [], []

    def after(delay, callback):
        token = f"timer-{len(events)}"
        events.append("scheduled")
        callbacks[token] = callback
        return token

    app = SimpleNamespace(
        _is_destroyed=False, _close_after_id=None,
        _is_launching=operation == "launch", _mc_process=None,
        modrinth_view=SimpleNamespace(_busy=operation == "mods"),
        settings_view=SimpleNamespace(update_panel=SimpleNamespace(_busy=operation == "update")),
        bottom_bar=SimpleNamespace(
            status_label=SimpleNamespace(configure=lambda **kwargs: None),
            username_input=SimpleNamespace(get=lambda: "Alex"),
        ),
        settings=SimpleNamespace(set=lambda *args: None, save=lambda: events.append("saved")),
        version_var=SimpleNamespace(get=lambda: "1.21"),
        loader_var=SimpleNamespace(get=lambda: "Fabric"),
        geometry=lambda: "1000x680+0+0",
        server_view=SimpleNamespace(active=False, _closing=False),
        after=after, after_cancel=lambda token: cancelled.append(token),
        destroy=lambda: events.append("destroyed"),
    )
    app._on_close = lambda: HexLauncher._on_close(app)
    app._on_close()
    first_timer = app._close_after_id
    app._on_close()  # repeated clicks must replace the pending close timer
    assert first_timer in cancelled
    assert "destroyed" not in events
    assert "saved" not in events
    app.modrinth_view._busy = False
    app._is_launching = False
    app.settings_view.update_panel._busy = False
    callbacks[app._close_after_id]()
    assert events[-2:] == ["saved", "destroyed"]
    assert app._close_after_id is None
