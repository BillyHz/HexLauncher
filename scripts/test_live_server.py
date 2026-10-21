"""Opt-in real Paper/Playit smoke test using an isolated copy of an existing setup.

Run from the repository: python scripts/test_live_server.py
Player worlds/settings are never copied or modified. Test secrets remain under build/.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.hexlauncher.core.server_manager import MinecraftServerManager


def varint(value):
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        result.append(byte | (128 if value else 0))
        if not value:
            return bytes(result)


def read_exact(connection, size):
    result = b""
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise RuntimeError("Minecraft closed the connection before replying")
        result += chunk
    return result


def read_varint(connection):
    result = 0
    for index in range(5):
        byte = read_exact(connection, 1)[0]
        result |= (byte & 127) << (index * 7)
        if not byte & 128:
            return result
    raise ValueError("Invalid Minecraft VarInt")


def status_ping(host, port=25565):
    started = time.monotonic()
    with socket.create_connection((host, port), timeout=8) as connection:
        connection.settimeout(8)
        encoded = host.encode("utf-8")
        handshake = b"\0" + varint(767) + varint(len(encoded)) + encoded + struct.pack(">H", port) + b"\1"
        connection.sendall(varint(len(handshake)) + handshake + b"\1\0")
        length = read_varint(connection)
        if not 0 < length < 1024**2 or read_varint(connection) != 0:
            raise ValueError("Invalid Minecraft status packet")
        payload = json.loads(read_exact(connection, read_varint(connection)))
        token = struct.pack(">q", time.time_ns() // 1_000_000)
        connection.sendall(b"\x09\x01" + token)
        assert read_varint(connection) == 9 and read_exact(connection, 9) == b"\1" + token
    return {"version": payload["version"]["name"], "players": payload["players"]["online"],
            "roundtrip_ms": round((time.monotonic() - started) * 1000, 1)}


def run(require_public=False):
    output = ROOT / "build"
    output.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="server-live-", dir=output))
    source = ROOT / "HexServer"
    report = {"test_directory": str(directory), "cycles": [], "events": [], "errors": []}
    lines = []
    ready = threading.Event()
    public = [""]

    def log(line):
        # Do not print tokens or agent claim links to the transcript/report.
        cleaned = re.sub(r"https://playit\.gg/claim/\S+", "[claim link omitted]", line)
        if re.search(r"secret[_ -]?(?:key|token)\s*[=:]", cleaned, flags=re.I):
            cleaned = "[secret-bearing log omitted]"
        lines.append(cleaned)
        if "Done (" in line or "ERROR" in line or "exited" in line:
            print(cleaned, flush=True)

    def event(kind, value):
        if kind == "ready":
            ready.set()
        if kind == "address":
            public[0] = value
        report["events"].append({"kind": kind, "value": "[claim link omitted]" if kind == "claim" else value})
        print("EVENT", kind, "[claim link omitted]" if kind == "claim" else value, flush=True)

    manager = MinecraftServerManager(directory, ROOT / "HexJDK")
    try:
        with socket.socket() as check:
            check.bind(("127.0.0.1", 25565))
        for name in ("server.jar", ".hexserver.json", "playit.exe", "playit.toml"):
            if (source / name).is_file():
                shutil.copy2(source / name, directory / name)
        for name in ("cache", "libraries", "versions"):
            if (source / name).is_dir():
                shutil.copytree(source / name, directory / name)
        metadata = json.loads((directory / ".hexserver.json").read_text())
        manager.setup_server(metadata["version"], metadata["loader"])
        # Reduce test-world generation cost while keeping the real server protocol.
        with (directory / "server.properties").open("a") as properties:
            properties.write("view-distance=3\nsimulation-distance=3\nlevel-seed=hexlauncher-smoke-test\n")
        identity = None
        for cycle in range(2):
            ready.clear()
            public[0] = ""
            print(f"START cycle {cycle + 1}: {metadata['loader']} {metadata['version']}", flush=True)
            manager.start_server(2, log, event)
            processes = [manager._server, manager._playit]
            result = {"cycle": cycle + 1, "processes": [
                {"pid": process.pid, "name": psutil.Process(process.pid).name()} for process in processes
            ]}
            report["cycles"].append(result)
            assert ready.wait(90), "Minecraft did not become ready within 90 seconds"
            result["local_status"] = status_ping("127.0.0.1")
            print("LOCAL", result["local_status"], flush=True)
            deadline = time.monotonic() + (35 if cycle == 0 else 15)
            while not public[0] and time.monotonic() < deadline:
                time.sleep(.25)
            if public[0]:
                host, _, port = public[0].partition(":")
                try:
                    result["public_status"] = status_ping(host, int(port) if port else 25565)
                    print("PUBLIC", result["public_status"], flush=True)
                except Exception as exc:
                    result["public_error"] = str(exc)
            else:
                result["public_error"] = "No active tunnel address was reported by Playit"
            manager.stop_server()
            result["stopped"] = all(process.poll() is not None for process in processes)
            result["exit_codes"] = [process.poll() for process in processes]
            assert result["stopped"] and not manager.is_running
            assert (directory / "world" / "level.dat").is_file()
            current_identity = hashlib.sha256((directory / "world" / "uid.dat").read_bytes()).hexdigest()
            if identity is not None:
                assert current_identity == identity, "World identity changed across restart"
            identity = current_identity
            result["world_saved"] = True
            result["world_identity_preserved"] = True
            print("STOPPED, world saved", flush=True)
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print("FAIL", report["errors"][-1], flush=True)
    finally:
        try:
            manager.stop_server()
        except Exception as exc:
            report["errors"].append(f"Cleanup failed: {type(exc).__name__}: {exc}")
        report["processes_remaining"] = manager.is_running
        report["public_verified"] = len(report["cycles"]) == 2 and all(
            "public_status" in cycle for cycle in report["cycles"]
        )
        (directory / "playit.toml").unlink(missing_ok=True)
        (directory / "test.log").write_text("\n".join(lines), encoding="utf-8")
        (output / "server-live-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("REPORT", output / "server-live-report.json", flush=True)
    return 1 if report["errors"] or (require_public and not report["public_verified"]) else 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-public", action="store_true",
                        help="Fail unless both cycles receive a real Minecraft reply through Playit")
    raise SystemExit(run(parser.parse_args().require_public))
