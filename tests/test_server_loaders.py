"""Forge installers must match Minecraft and publish only complete installations."""

import hashlib
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.hexlauncher.core import server_loaders as loaders
from src.hexlauncher.core import server_manager as servers


class Response:
    def __init__(self, text="", data=None):
        self.text, self.data = text, data

    def json(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MetadataManager:
    def __init__(self, versions, promotions=None):
        self.xml = (
            "<metadata><versioning><versions>"
            + "".join(f"<version>{version}</version>" for version in versions)
            + "</versions></versioning></metadata>"
        )
        self.promotions = promotions or {}
        self.urls = []

    def _request(self, url, **kwargs):
        self.urls.append(url)
        return Response("a" * 40 if url.endswith(".sha1") else self.xml)

    def _json(self, url):
        self.urls.append(url)
        return {"promos": self.promotions}


@pytest.mark.parametrize(
    ("minecraft", "selected"),
    [
        ("1.20.2", "20.2.90"),
        ("1.21", "21.0.167"),
        ("1.21.1", "21.1.235"),
    ],
)
def test_neoforge_selects_exact_minecraft_stable_release(minecraft, selected):
    manager = MetadataManager(["20.2.90", "21.0.167", "21.1.235", "21.1.999-beta", "21.10.900"])
    result = loaders.resolve_installer(manager, minecraft, "neoforge")
    assert result["artifact_version"] == selected
    assert f"/{selected}/neoforge-{selected}-installer.jar" in result["url"]
    assert result["sha1"] == "a" * 40


def test_neoforge_1201_uses_historical_forge_artifact():
    result = loaders.resolve_installer(
        MetadataManager(["1.20.1-47.1.99", "1.20.2-48.1.0"]), "1.20.1", "neoforge"
    )
    assert "/net/neoforged/forge/1.20.1-47.1.99/forge-" in result["url"]
    assert result["argument_file"] == "libraries/net/neoforged/forge/1.20.1-47.1.99/win_args.txt"


def test_forge_prefers_recommended_over_newest_or_wrong_game_version():
    manager = MetadataManager(
        ["1.21.1-52.0.1", "1.21.1-52.1.9", "1.21.10-99.0.0", "1.21.1-53.0.0-beta"],
        {"1.21.1-recommended": "52.0.1"},
    )
    assert loaders.resolve_installer(manager, "1.21.1", "forge")["artifact_version"] == "1.21.1-52.0.1"


def test_only_prerelease_or_other_version_is_rejected():
    with pytest.raises(RuntimeError, match="No stable"):
        loaders.resolve_installer(MetadataManager(["21.1.1-beta", "21.10.1"]), "1.21.1", "neoforge")


def test_invalid_published_installer_checksum_rejected():
    manager = MetadataManager(["21.1.235"])
    original = manager._request
    manager._request = lambda url, **kwargs: Response("invalid") if url.endswith(".sha1") else original(url)
    with pytest.raises(RuntimeError, match="checksum"):
        loaders.resolve_installer(manager, "1.21.1", "neoforge")


def fixture_installation(tmp_path, monkeypatch):
    manager = servers.MinecraftServerManager(tmp_path / "HexServer", tmp_path / "HexJDK")
    manager.base_dir.mkdir()
    (manager.base_dir / "world").mkdir()
    (manager.base_dir / "world" / "level.dat").write_bytes(b"precious world")
    (manager.base_dir / "libraries").mkdir()
    (manager.base_dir / "libraries" / "old.jar").write_bytes(b"old runtime")
    metadata = {"version": "1.21.1", "loader": "neoforge", "java_major": 21}
    (manager.base_dir / ".hexserver.json").write_text(json.dumps(metadata))
    argument = "libraries/net/neoforged/neoforge/21.1.235/win_args.txt"
    monkeypatch.setattr(
        loaders,
        "resolve_installer",
        lambda *args: {
            "artifact_version": "21.1.235",
            "url": "https://example.org/installer.jar",
            "sha1": hashlib.sha1(b"installer").hexdigest(),
            "argument_file": argument,
        },
    )
    downloads = []

    def download(url, destination, hashes):
        downloads.append(hashes)
        Path(destination).write_bytes(b"installer")

    monkeypatch.setattr(manager, "_download", download)
    monkeypatch.setattr(loaders, "install_jdk", lambda *args, **kwargs: "java.exe")
    return manager, metadata, argument, downloads


@pytest.mark.parametrize(
    "failure", [RuntimeError("exit code 1"), subprocess.TimeoutExpired("installer", 900)]
)
def test_installer_failure_preserves_world_metadata_and_existing_runtime(tmp_path, monkeypatch, failure):
    manager, metadata, _, _ = fixture_installation(tmp_path, monkeypatch)

    def fail(*args):
        raise failure

    monkeypatch.setattr(loaders, "_run_installer", fail)
    with pytest.raises(type(failure)):
        loaders.install_modded_server(manager, "1.21.1", "neoforge", metadata)
    assert (manager.base_dir / "world" / "level.dat").read_bytes() == b"precious world"
    assert (manager.base_dir / "libraries" / "old.jar").read_bytes() == b"old runtime"
    assert json.loads((manager.base_dir / ".hexserver.json").read_text()) == metadata
    assert not list(tmp_path.glob(".hex-server-install-*"))


def test_successful_installer_publishes_checked_runtime_and_caches_setup(tmp_path, monkeypatch):
    manager, metadata, argument, downloads = fixture_installation(tmp_path, monkeypatch)

    def install(manager, java, installer, stage, callback, cancel_event=None):
        assert java == "java.exe"
        file = stage / argument
        file.parent.mkdir(parents=True)
        file.write_text("--launchTarget neoforgeserver")

    monkeypatch.setattr(loaders, "_run_installer", install)
    result = loaders.install_modded_server(manager, "1.21.1", "neoforge", metadata)
    assert result["launch_args"] == ["@" + argument, "nogui"]
    assert downloads == [{"sha1": hashlib.sha1(b"installer").hexdigest()}]
    assert (manager.base_dir / "world" / "level.dat").read_bytes() == b"precious world"
    monkeypatch.setattr(manager, "_json", lambda url: pytest.fail("cached setup made a network request"))
    assert manager.setup_server("1.21.1", "neoforge") == result


def test_metadata_publish_failure_restores_previous_runtime(tmp_path, monkeypatch):
    manager, metadata, argument, _ = fixture_installation(tmp_path, monkeypatch)

    def install(manager, java, installer, stage, callback, cancel_event=None):
        file = stage / argument
        file.parent.mkdir(parents=True)
        file.write_text("--launchTarget neoforgeserver")

    monkeypatch.setattr(loaders, "_run_installer", install)
    monkeypatch.setattr(manager, "_write_json", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        loaders.install_modded_server(manager, "1.21.1", "neoforge", metadata)
    assert (manager.base_dir / "libraries" / "old.jar").read_bytes() == b"old runtime"
    assert json.loads((manager.base_dir / ".hexserver.json").read_text()) == metadata


@pytest.mark.parametrize(
    "argument", ["@../outside.txt", "run.bat", "@libraries/net/neoforged/neoforge/21.1.1/unix_args.txt"]
)
def test_launch_metadata_cannot_execute_shell_or_escape_instance(tmp_path, argument):
    with pytest.raises(RuntimeError, match="argument file"):
        loaders.launch_arguments(tmp_path, {"loader": "neoforge", "launch_args": [argument, "nogui"]})


def test_cancelled_installer_terminates_owned_process_without_shell(tmp_path):
    calls = []
    cancelled = threading.Event()
    cancelled.set()

    class Process:
        stdout = None
        code = None
        terminated = False

        def poll(self):
            return self.code

        def terminate(self):
            self.terminated = True
            self.code = 0

        def wait(self, timeout=None):
            assert timeout == 10
            return self.code

    process = Process()
    manager = servers.MinecraftServerManager(
        tmp_path / "HexServer", popen=lambda args, **kwargs: calls.append((args, kwargs)) or process
    )
    installer = tmp_path / "installer.jar"
    with pytest.raises(RuntimeError, match="cancelled"):
        loaders._run_installer(manager, "java.exe", installer, tmp_path, None, cancelled)
    assert process.terminated
    assert calls[0][0] == ["java.exe", "-jar", str(installer), "--installServer"]
    assert not calls[0][1].get("shell")
    assert manager._installer is None


def test_failed_installer_termination_stays_owned_until_stop_retry(tmp_path):
    class Process:
        def __init__(self):
            self.code = None
            self.fail = True

        def poll(self):
            return self.code

        def terminate(self):
            if self.fail:
                raise OSError("access denied")
            self.code = 0

        def kill(self):
            self.terminate()

        def wait(self, timeout=None):
            return self.code

    manager = servers.MinecraftServerManager(tmp_path / "HexServer")
    process = Process()
    manager._installer = process
    assert manager.is_running
    with pytest.raises(RuntimeError, match="stopped"):
        manager.stop_server()
    assert manager._installer is process
    process.fail = False
    manager.stop_server()
    assert not manager.is_running
    assert manager._installer is None


def test_modded_start_uses_java_relative_windows_argfile_and_ram_without_batch(tmp_path, monkeypatch):
    manager = servers.MinecraftServerManager(tmp_path / "HexServer")
    argument = "libraries/net/minecraftforge/forge/1.21.1-52.0.1/win_args.txt"
    runtime = manager.base_dir / argument
    runtime.parent.mkdir(parents=True)
    runtime.write_text("--launchTarget forgeserver")
    metadata = {"version": "1.21.1", "loader": "forge", "launch_args": ["@" + argument, "nogui"]}
    (manager.base_dir / ".hexserver.json").write_text(json.dumps(metadata))
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    manager._popen = lambda command, **kwargs: calls.append((command, kwargs)) or process
    monkeypatch.setattr(manager, "safe_ram_limit", lambda: 8)
    monkeypatch.setattr(manager, "ensure_playit_binary", lambda: "playit.exe")
    monkeypatch.setattr(servers, "install_jdk", lambda *args, **kwargs: "java.exe")
    monkeypatch.setattr(servers.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    manager.start_server(6)
    assert calls[0][0] == ["java.exe", "-Xmx6G", "-Xms2G", "@" + argument, "nogui"]
    assert calls[0][1]["cwd"] == str(manager.base_dir)
    assert not calls[0][1].get("shell")
