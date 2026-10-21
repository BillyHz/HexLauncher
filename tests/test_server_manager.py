"""Local-server failures must preserve worlds and reap owned child processes."""

import hashlib
import io
import json
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from src.hexlauncher.core import server_manager as module


class Response:
    def __init__(self, url, *, data=None, body=b""):
        self.url, self.data, self.body = url, data, body
        self.headers = {"content-length": str(len(body))}
        self.text = body.decode(errors="replace")

    def raise_for_status(self):
        pass

    def json(self):
        return self.data

    def iter_content(self, size):
        yield self.body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class VanillaTransport:
    def __init__(self, body=b"verified server", bad_hash=False):
        self.body, self.bad_hash, self.calls = body, bad_hash, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == module.MANIFEST_URL:
            data = {"versions": [{"id": "1.21.1", "url": "https://example.org/version"}]}
        elif url.endswith("/version"):
            data = {"javaVersion": {"majorVersion": 21}, "downloads": {"server": {
                "url": "https://example.org/server.jar", "size": len(self.body),
                "sha1": "0" * 40 if self.bad_hash else hashlib.sha1(self.body).hexdigest(),
            }}}
        else:
            return Response(url, body=self.body)
        return Response(url, data=data)


def manager(tmp_path, **kwargs):
    return module.MinecraftServerManager(tmp_path / "HexServer", tmp_path / "HexJDK", **kwargs)


def test_vanilla_setup_verified_isolated_and_preserves_configuration(tmp_path):
    transport = VanillaTransport()
    instance = manager(tmp_path, transport=transport)
    instance.setup_server("1.21.1", "vanilla")
    assert (instance.base_dir / "server.jar").read_bytes() == transport.body
    assert "eula=true" in (instance.base_dir / "eula.txt").read_text()
    properties = instance.base_dir / "server.properties"
    assert "server-port=25565" in properties.read_text()
    assert "online-mode=false" in properties.read_text()
    properties.write_text("motd=My friends\nserver-port=25565\n")
    (instance.base_dir / "world").mkdir()
    before = len(transport.calls)
    instance.setup_server("1.21.1", "vanilla")
    assert properties.read_text() == "motd=My friends\nserver-port=25565\n"
    assert len(transport.calls) == before
    assert all(call[1]["headers"]["User-Agent"] for call in transport.calls)
    with pytest.raises(RuntimeError, match="different"):
        instance.setup_server("1.20.1", "vanilla")


def test_corrupt_download_never_publishes_server(tmp_path):
    instance = manager(tmp_path, transport=VanillaTransport(bad_hash=True))
    with pytest.raises(RuntimeError, match="checksum"):
        instance.setup_server("1.21.1", "vanilla")
    assert not (instance.base_dir / "server.jar").exists()
    assert not (instance.base_dir / ".hexserver.json").exists()
    assert not list(instance.base_dir.glob(".hex-download-*"))


def test_download_preserves_existing_file_on_size_failure(tmp_path):
    instance = manager(tmp_path, transport=VanillaTransport())
    destination = tmp_path / "old.jar"
    destination.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="Incomplete"):
        instance._download("https://example.org/server.jar", destination, expected_size=999)
    assert destination.read_bytes() == b"old"


def test_unmanaged_world_is_not_overwritten(tmp_path):
    instance = manager(tmp_path, transport=VanillaTransport())
    (instance.base_dir / "world").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="unmanaged"):
        instance.setup_server("1.21.1")


class Process:
    def __init__(self, timeout=False):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.returncode = None
        self.commands = []
        self.timeout = timeout

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.commands.append(("wait", timeout))
        if self.timeout and self.returncode is None:
            raise subprocess.TimeoutExpired("java", timeout)
        self.returncode = 0
        return 0

    def terminate(self):
        self.commands.append(("terminate", None))
        self.returncode = 0

    def kill(self):
        self.commands.append(("kill", None))
        self.returncode = 0


def test_stop_saves_world_and_terminates_owned_agent(tmp_path):
    instance = manager(tmp_path)
    server, agent = Process(), Process()
    written = []
    server.stdin = SimpleNamespace(write=written.append, flush=lambda: None, close=lambda: None)
    instance._server, instance._playit = server, agent
    instance.stop_server()
    assert written == ["stop\n"]
    assert ("wait", 60) in server.commands
    assert ("terminate", None) not in server.commands
    assert ("terminate", None) in agent.commands
    assert not instance.is_running
    instance.stop_server()


def test_failed_agent_spawn_rolls_back_started_minecraft(tmp_path, monkeypatch):
    server = Process()
    written = []
    server.stdin = SimpleNamespace(write=written.append, flush=lambda: None, close=lambda: None)
    calls = []

    def spawn(command, **kwargs):
        calls.append(command)
        if len(calls) == 2:
            raise OSError("cannot spawn agent")
        return server

    instance = manager(tmp_path, popen=spawn)
    instance.base_dir.mkdir()
    (instance.base_dir / "server.jar").write_bytes(b"jar")
    monkeypatch.setattr(instance, "safe_ram_limit", lambda: 8)
    monkeypatch.setattr(instance, "ensure_playit_binary", lambda: "playit.exe")
    monkeypatch.setattr(module, "install_jdk", lambda *args, **kwargs: "java.exe")
    monkeypatch.setattr(module.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    with pytest.raises(OSError, match="cannot spawn"):
        instance.start_server()
    assert written == ["stop\n"]
    assert not instance.is_running


def test_unresponsive_server_gets_bounded_fallback(tmp_path):
    instance = manager(tmp_path)
    server = Process(timeout=True)
    instance._server = server
    instance.stop_server()
    assert ("terminate", None) in server.commands
    assert not instance.is_running


@pytest.mark.parametrize("source", ["Minecraft", "Playit"])
def test_late_output_reader_after_normal_stop_does_not_report_failure(tmp_path, source):
    instance = manager(tmp_path)
    process = Process()
    process.stdout = io.StringIO("")
    instance._server = process if source == "Minecraft" else None
    instance._playit = process if source == "Playit" else None
    statuses = []
    instance._on_status = lambda kind, value: statuses.append((kind, value))
    generation = instance._generation
    instance.stop_server()
    # Deliberately let the monitor observe process termination only after Stop
    # has reset _stopping, reproducing the real reader/wait scheduling race.
    instance._read_output(process, source, generation)
    assert not any(kind == "error" for kind, value in statuses)
    assert not instance.is_running


def test_insufficient_memory_rejects_before_process_creation(tmp_path, monkeypatch):
    instance = manager(tmp_path, popen=lambda *args, **kwargs: pytest.fail("process was spawned"))
    monkeypatch.setattr(instance, "safe_ram_limit", lambda: 1)
    with pytest.raises(RuntimeError, match="RAM"):
        instance.start_server(2)


def test_metadata_different_loader_rejected(tmp_path):
    instance = manager(tmp_path)
    instance.base_dir.mkdir()
    (instance.base_dir / ".hexserver.json").write_text(json.dumps({"version": "1.21.1", "loader": "paper"}))
    with pytest.raises(RuntimeError, match="different"):
        instance.setup_server("1.21.1", "fabric")


def test_playit_only_publishes_active_mapping_for_this_server(tmp_path):
    instance = manager(tmp_path)
    statuses = []
    instance._on_status = lambda kind, value: statuses.append((kind, value))
    instance._parse_playit_line("Visit https://playit.gg/claim/abcdef1234")
    instance._parse_playit_line("friends.at.ply.gg:24501 => 127.0.0.1:25565")
    instance._parse_playit_line("other.at.ply.gg:24502 => 127.0.0.1:25566")
    instance._parse_playit_line("disabled.at.ply.gg:24503 => (disabled account limit)")
    instance._parse_playit_line("evil.at.ply.gg:99999 => 127.0.0.1:25565")
    assert statuses == [("claim", "https://playit.gg/claim/abcdef1234"),
                        ("address", "friends.at.ply.gg:24501")]


def test_playit_failure_does_not_skip_world_save(tmp_path):
    instance = manager(tmp_path)
    server, agent = Process(), Process()
    written = []
    server.stdin = SimpleNamespace(write=written.append, flush=lambda: None, close=lambda: None)

    def fail_terminate():
        raise OSError("process access denied")

    agent.terminate = fail_terminate
    instance._server, instance._playit = server, agent
    try:
        instance.stop_server()
    except (OSError, RuntimeError):
        pass
    assert written == ["stop\n"]


def test_cached_setup_repairs_missing_defaults(tmp_path):
    instance = manager(tmp_path, transport=VanillaTransport())
    instance.setup_server("1.21.1", "vanilla")
    (instance.base_dir / "eula.txt").unlink()
    (instance.base_dir / "server.properties").unlink()
    instance.setup_server("1.21.1", "vanilla")
    assert "eula=true" in (instance.base_dir / "eula.txt").read_text()
    assert "server-port=25565" in (instance.base_dir / "server.properties").read_text()


def test_paper_chooses_latest_stable_and_verifies_checksum(tmp_path):
    class PaperTransport(VanillaTransport):
        def get(self, url, **kwargs):
            if url.endswith("/builds"):
                artifact = {"url": "https://example.org/paper.jar", "size": len(self.body),
                            "checksums": {"sha256": hashlib.sha256(self.body).hexdigest()}}
                return Response(url, data=[{"id": 1, "channel": "STABLE",
                                            "downloads": {"server:default": artifact}},
                                           {"id": 20, "channel": "EXPERIMENTAL"}])
            return super().get(url, **kwargs)

    transport = PaperTransport()
    instance = manager(tmp_path, transport=transport)
    result = instance.setup_server("1.21.1", "paper")
    assert result["build"] == 1
    assert (instance.base_dir / "server.jar").read_bytes() == transport.body


@pytest.mark.parametrize("manifest", [True, False])
def test_fabric_generated_jar_validation(tmp_path, manifest):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("loader.class", b"stub")
        if manifest:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")

    class FabricTransport(VanillaTransport):
        def get(self, url, **kwargs):
            if "/versions/loader/" in url and not url.endswith("/server/jar"):
                return Response(url, data=[{"loader": {"stable": True, "version": "0.16.0"}}])
            if url.endswith("/versions/installer"):
                return Response(url, data=[{"stable": True, "version": "1.0.0"}])
            if url.endswith("/server/jar"):
                return Response(url, body=stream.getvalue())
            return super().get(url, **kwargs)

    instance = manager(tmp_path, transport=FabricTransport())
    if manifest:
        instance.setup_server("1.21.1", "fabric")
        assert (instance.base_dir / "server.jar").read_bytes() == stream.getvalue()
    else:
        with pytest.raises(RuntimeError, match="valid JAR"):
            instance.setup_server("1.21.1", "fabric")
        assert not (instance.base_dir / "server.jar").exists()


def test_playit_binary_pinned_checksum_is_mandatory(tmp_path, monkeypatch):
    body = b"MZsigned agent"
    asset_url = "https://github.com/playit-cloud/playit-agent/releases/download/v0.17.1/playit-windows-x86_64-signed.exe"

    class AgentTransport:
        def get(self, url, **kwargs):
            if url == module.PLAYIT_RELEASE_API:
                return Response(url, data={"assets": [{"name": "playit-windows-x86_64-signed.exe",
                                                      "browser_download_url": asset_url,
                                                      "size": len(body)}]})
            return Response(url, body=body)

    instance = manager(tmp_path, transport=AgentTransport())
    with pytest.raises(RuntimeError, match="checksum"):
        instance.ensure_playit_binary()
    assert not (instance.base_dir / "playit.exe").exists()
    monkeypatch.setattr(module, "PLAYIT_SHA256", hashlib.sha256(body).hexdigest())
    instance.ensure_playit_binary()
    assert (instance.base_dir / "playit.exe").read_bytes() == body
