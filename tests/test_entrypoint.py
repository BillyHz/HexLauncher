"""The hidden packaged check must not enter CTk's Windows titlebar setup."""

from types import SimpleNamespace

import main


def test_console_parent_relaunches_windowed_and_preserves_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.sys, "executable", "C:/Python/python.exe")
    monkeypatch.setattr(main.sys, "argv", ["main.py", "argument with spaces"])
    monkeypatch.setattr(main.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(main.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert main._relaunch_without_console()
    command = calls[0][0][0]
    assert command == [
        main.os.path.join("C:/Python", "pythonw.exe"),
        main.os.path.abspath(main.__file__),
        "--hex-windowed",
        "argument with spaces",
    ]
    assert calls[0][1]["creationflags"] == main.subprocess.CREATE_NO_WINDOW


def test_windowed_child_does_not_relaunch(monkeypatch):
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--hex-windowed"])
    assert not main._relaunch_without_console()


def test_missing_pythonw_uses_hidden_python_process(monkeypatch):
    commands = []
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.sys, "executable", "C:/Python/python.exe")
    monkeypatch.setattr(main.sys, "argv", ["main.py"])
    monkeypatch.setattr(main.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(main.subprocess, "Popen", lambda command, **kwargs: commands.append(command))
    assert main._relaunch_without_console()
    assert commands[0][0] == main.sys.executable


def test_smoke_uses_native_hidden_loop(monkeypatch):
    callbacks, events = [], []
    app = SimpleNamespace(
        _initial_refresh_after_id="refresh",
        after_cancel=lambda timer: events.append(("cancel", timer)),
        withdraw=lambda: events.append("hidden"),
        destroy=lambda: events.append("destroyed"),
        after=lambda delay, callback: callbacks.append(callback),
        mainloop=lambda: events.append("wrong loop"),
    )
    monkeypatch.setattr(main, "HexLauncher", lambda: app)
    monkeypatch.setattr(main.sys, "argv", ["launcher", "--smoke-test"])
    monkeypatch.setattr(main.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(main.tkinter.Tk, "mainloop", lambda root: callbacks[-1]())
    main.run()
    assert events == [("cancel", "refresh"), "hidden", "destroyed"]


def test_normal_entrypoint_uses_custom_loop(monkeypatch):
    events = []
    monkeypatch.setattr(main, "HexLauncher", lambda: SimpleNamespace(mainloop=lambda: events.append("loop")))
    monkeypatch.setattr(main.sys, "argv", ["launcher"])
    main.run()
    assert events == ["loop"]
