"""Isolated Minecraft server installation and owned Playit process lifecycle.

Callbacks run on worker threads: callers must marshal them onto their UI loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import psutil
import requests

from src.hexlauncher.core.jdk import install_jdk
from src.hexlauncher.core.playit import agent_tunnels, minecraft_tunnel
from src.hexlauncher.core.server_loaders import install_modded_server, launch_arguments

logger = logging.getLogger(__name__)
USER_AGENT = "BillyHz/HexLauncher/0.7.0 (https://github.com/BillyHz/HexLauncher)"
MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PAPER_API = "https://fill.papermc.io/v3"
FABRIC_API = "https://meta.fabricmc.net/v2"
# v1 replaced standalone CLI with a service daemon. Pin the supported standalone
# protocol rather than downloading a daemon and pretending it has CLI flags.
PLAYIT_RELEASE_API = "https://api.github.com/repos/playit-cloud/playit-agent/releases/tags/v0.17.1"
PLAYIT_SHA256 = "9b00d6ff7d37d1052e5ae097e1348e11deae8617cd7a8ba39d1777f2006316a3"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CLAIM = re.compile(r"https://playit\.gg/claim/[a-zA-Z0-9_-]+")
ADDRESS = re.compile(r"\b([a-zA-Z0-9.-]+\.(?:at\.ply\.gg|ply\.gg|joinmc\.link|playit\.gg))(?::(\d{1,5}))?\b")


class MinecraftServerManager:
    """One server and one owned tunnelling agent; network methods are blocking."""

    def __init__(self, base_dir="HexServer", java_dir="HexJDK", *, transport=None, popen=None):
        self.base_dir = Path(base_dir).resolve()
        self.java_dir = Path(java_dir).resolve()
        self.http = transport or requests
        self._popen = popen or subprocess.Popen
        self._lock = threading.RLock()
        self._stop_lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._server = None
        self._playit = None
        self._installer = None
        self._stopping = False
        self._generation = 0
        self._on_log = None
        self._on_status = None
        self._last_tunnel_lookup = None
        self._tunnel_address = ""
        self._tunnel_disabled = False

    @property
    def is_running(self):
        with self._lock:
            return any(
                process is not None and process.poll() is None
                for process in (self._server, self._playit, self._installer)
            )

    @staticmethod
    def safe_ram_limit():
        memory = psutil.virtual_memory()
        # Keep at least 2 GiB available to the OS/client, cap at half physical RAM.
        return max(0, min(8, int(min(memory.available - 2 * 1024**3, memory.total / 2) / 1024**3)))

    def _request(self, url, **kwargs):
        if urlparse(url).scheme != "https":
            raise ValueError("Downloads must use HTTPS.")
        response = self.http.get(url, headers={"User-Agent": USER_AGENT}, timeout=(10, 60), **kwargs)
        try:
            response.raise_for_status()
            if urlparse(getattr(response, "url", url)).scheme != "https":
                raise ValueError("Insecure download redirect.")
        except Exception:
            response.close()
            raise
        return response

    def _json(self, url):
        with self._request(url) as response:
            return response.json()

    def _download(self, url, destination, hashes=None, expected_size=None):
        hashes = hashes or {}
        calculators = {}
        for algorithm, digest in hashes.items():
            if algorithm not in {"sha1", "sha256", "sha512"}:
                raise ValueError("Unsupported download checksum.")
            hasher = hashlib.new(algorithm)
            if not isinstance(digest, str) or not re.fullmatch(
                rf"[0-9a-fA-F]{{{hasher.digest_size * 2}}}", digest
            ):
                raise ValueError("Invalid published download checksum.")
            calculators[algorithm] = hasher
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".hex-download-", dir=destination.parent)
        temporary = Path(name)
        try:
            with os.fdopen(handle, "wb") as output, self._request(url, stream=True) as response:
                total = 0
                for chunk in response.iter_content(256 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 1024**3:
                        raise RuntimeError("Download exceeds the 1 GiB safety limit.")
                    output.write(chunk)
                    for calculator in calculators.values():
                        calculator.update(chunk)
                advertised = response.headers.get("content-length")
                if (
                    not total
                    or (expected_size is not None and total != expected_size)
                    or (advertised and total != int(advertised))
                ):
                    raise RuntimeError("Incomplete download.")
                output.flush()
                os.fsync(output.fileno())
            if any(calculators[key].hexdigest() != value.lower() for key, value in hashes.items()):
                raise RuntimeError("Downloaded file checksum does not match; existing file was preserved.")
            if not hashes and destination.suffix == ".jar":
                with zipfile.ZipFile(temporary) as archive:
                    if "META-INF/MANIFEST.MF" not in archive.namelist() or archive.testzip() is not None:
                        raise RuntimeError("The generated Fabric launcher is not a valid JAR.")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_json(path, value):
        handle, name = tempfile.mkstemp(prefix=".hex-metadata-", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                json.dump(value, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    def setup_server(self, version, loader="paper", on_log_callback=None, cancel_event=None):
        """Prepare a verified jar; never overwrite an existing world's configuration."""
        if not isinstance(version, str) or not re.fullmatch(r"[a-zA-Z0-9_.+-]{1,80}", version):
            raise ValueError("Invalid Minecraft version.")
        loader = loader.lower()
        if loader not in {"paper", "fabric", "vanilla", "forge", "neoforge"}:
            raise ValueError("Choose Paper, Fabric, Vanilla, Forge or NeoForge.")
        with self._operation_lock:
            if self.is_running:
                raise RuntimeError("Stop the server before changing its installation.")
            self.base_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = self.base_dir / ".hexserver.json"
            jar = self.base_dir / "server.jar"
            if metadata_path.exists():
                old = json.loads(metadata_path.read_text(encoding="utf-8"))
                if old.get("version") != version or old.get("loader") != loader:
                    raise RuntimeError(
                        "HexServer already contains a different version or server type. "
                        "Back up and move HexServer before creating another server."
                    )
                try:
                    launch_arguments(self.base_dir, old)
                except RuntimeError:
                    pass
                else:
                    self._ensure_defaults()
                    return old
            elif jar.exists() or any(
                (self.base_dir / name).exists() for name in ("world", "world_nether", "world_the_end")
            ):
                raise RuntimeError(
                    "HexServer contains an unmanaged server or world. Back it up and move it before setup."
                )
            manifest = self._json(MANIFEST_URL)
            entry = next((item for item in manifest["versions"] if item["id"] == version), None)
            if entry is None:
                raise ValueError("Minecraft version is absent from the official manifest.")
            info = self._json(entry["url"])
            required_java = int(info.get("javaVersion", {}).get("majorVersion", 8))
            if required_java < 17:
                raise RuntimeError(
                    "Servers requiring Java 8/16 are not supported by the internal Java 21 runtime. "
                    "Choose Minecraft 1.18 or newer."
                )
            if required_java > 21:
                raise RuntimeError(
                    f"Minecraft {version} requires Java {required_java}; "
                    "HexLauncher currently provides Java 21. Choose a compatible version."
                )
            metadata = {"version": version, "loader": loader, "java_major": required_java}
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Server setup cancelled.")
            if loader in {"forge", "neoforge"}:
                metadata = install_modded_server(
                    self, version, loader, metadata, on_log_callback, cancel_event
                )
                self._ensure_defaults()
                return metadata
            if loader == "paper":
                builds = self._json(f"{PAPER_API}/projects/paper/versions/{version}/builds")
                stable = [item for item in builds if item.get("channel") == "STABLE"]
                if not stable:
                    raise RuntimeError(
                        "No stable Paper build exists for this Minecraft version. Choose Fabric or Vanilla."
                    )
                build = max(stable, key=lambda item: int(item["id"]))
                download = build["downloads"]["server:default"]
                url, hashes = download["url"], {"sha256": download["checksums"]["sha256"]}
                metadata["build"] = build["id"]
                required_java = max(
                    required_java, int(build.get("java", {}).get("version", {}).get("minimum", 21))
                )
                if required_java > 21:
                    raise RuntimeError(
                        f"This Paper build requires Java {required_java}; "
                        "choose a Java 21 compatible version."
                    )
                metadata["java_major"] = required_java
                size = download.get("size")
            elif loader == "fabric":
                loaders = self._json(f"{FABRIC_API}/versions/loader/{version}")
                selected = next(
                    (item["loader"]["version"] for item in loaders if item["loader"].get("stable")), None
                )
                installers = self._json(f"{FABRIC_API}/versions/installer")
                installer = next((item["version"] for item in installers if item.get("stable")), None)
                if not selected or not installer:
                    raise RuntimeError("No stable Fabric loader/installer is available.")
                url = f"{FABRIC_API}/versions/loader/{version}/{selected}/{installer}/server/jar"
                # This generated launcher endpoint publishes no checksum sidecar.
                # Trust the official HTTPS origin and validate the resulting JAR.
                hashes, size = {}, None
                metadata.update(fabric_loader=selected, fabric_installer=installer)
            else:
                download = info.get("downloads", {}).get("server")
                if not download:
                    raise RuntimeError("This version has no official server download.")
                url, hashes, size = download["url"], {"sha1": download["sha1"]}, download["size"]
            self._ensure_defaults()
            self._download(url, jar, hashes, size)
            try:
                self._write_json(metadata_path, metadata)
            except Exception:
                # No previous jar exists here: cached installations returned above.
                # Leave setup retryable instead of orphaning an unmanaged server.jar.
                jar.unlink(missing_ok=True)
                raise
            return metadata

    def _ensure_defaults(self):
        eula = self.base_dir / "eula.txt"
        if not eula.exists():
            eula.write_text("# Minecraft EULA: https://aka.ms/MinecraftEULA\neula=true\n", encoding="utf-8")
        properties = self.base_dir / "server.properties"
        if not properties.exists():
            properties.write_text(
                "server-port=25565\nserver-ip=127.0.0.1\nonline-mode=false\nmotd=Servidor de HexLauncher\n",
                encoding="utf-8",
            )

    def ensure_playit_binary(self):
        """Download an official Windows x64 agent without installing a global service."""
        destination = self.base_dir / "playit.exe"
        if destination.is_file():
            return str(destination)
        release = self._json(PLAYIT_RELEASE_API)
        asset = next(
            (item for item in release["assets"] if item["name"] == "playit-windows-x86_64-signed.exe"), None
        )
        if asset is None:
            raise RuntimeError("The official Playit release has no Windows x64 executable.")
        url = asset["browser_download_url"]
        if (
            url
            != "https://github.com/playit-cloud/playit-agent/releases/download/v0.17.1/playit-windows-x86_64-signed.exe"
        ):
            raise RuntimeError("Unexpected Playit release download origin.")
        hashes = {"sha256": PLAYIT_SHA256}
        self._download(url, destination, hashes, asset.get("size"))
        return str(destination)

    def _notify(self, kind, value=""):
        if self._on_status:
            try:
                self._on_status(kind, value)
            except Exception:
                logger.exception("Server status callback failed")

    def _log(self, line):
        if self._on_log:
            try:
                self._on_log(line)
            except Exception:
                logger.exception("Server log callback failed")

    def _parse_playit_line(self, line):
        claim = CLAIM.search(line)
        if claim:
            self._notify("claim", claim.group(0))
        # Only publish this server's active mapping, not unrelated account tunnels.
        if "disabled" in line.lower() or not re.search(
            r"=>\s*(?:127\.0\.0\.1|localhost|\[::1\]):25565\b", line
        ):
            return
        address = ADDRESS.search(line.split("=>", 1)[0])
        if address and (not address.group(2) or 0 < int(address.group(2)) <= 65535):
            self._notify("address", address.group(0))

    def _read_output(self, process, source, generation):
        try:
            if process.stdout is not None:
                for raw in process.stdout:
                    with self._lock:
                        if generation != self._generation:
                            break
                    line = ANSI.sub("", raw).strip()
                    if not line:
                        continue
                    self._log(f"[{source}] {line}")
                    if source == "Playit":
                        self._parse_playit_line(line)
                        if "tunnel running" in line.lower():
                            self._refresh_playit_address(generation)
                    elif "Done (" in line and "For help" in line:
                        self._notify("ready", "Minecraft server is ready.")
            code = process.wait()
            with self._lock:
                current = generation == self._generation
                stopping = self._stopping
            if current and not stopping:
                if source == "Playit":
                    self._notify("address", "")
                self._notify("error", f"{source} exited unexpectedly (code {code}).")
                if source == "Minecraft":
                    self.stop_server()
        except (OSError, ValueError) as exc:
            self._log(f"[{source}] Output monitor failed: {exc}")
        finally:
            if process.stdout is not None:
                process.stdout.close()

    def _refresh_playit_address(self, generation):
        # v0.17.1 --stdout logs only the first line of its screen, omitting
        # the actual mappings. Query the same read-only API used by the agent.
        now = time.monotonic()
        if self._last_tunnel_lookup is not None and now - self._last_tunnel_lookup < 15:
            return
        self._last_tunnel_lookup = now
        try:
            address, disabled = minecraft_tunnel(agent_tunnels(self.base_dir / "playit.toml", self.http))
        except (OSError, ValueError, RuntimeError, requests.RequestException):
            # Never log the credential or an HTTP request object with its headers.
            self._log("[Playit] Could not refresh tunnel metadata; retrying later.")
            return
        with self._lock:
            if generation != self._generation or self._stopping:
                return
            if address != self._tunnel_address:
                self._tunnel_address = address
                self._notify("address", address)
            if disabled and not address and not self._tunnel_disabled:
                self._notify("status", "El túnel de Playit está desactivado. Actívalo en el panel de Playit.")
            self._tunnel_disabled = disabled and not address

    def start_server(self, ram_gb=4, on_log_callback=None, on_playit_status=None):
        with self._operation_lock:
            if isinstance(ram_gb, bool) or not isinstance(ram_gb, int) or not 2 <= ram_gb <= 8:
                raise ValueError("Server RAM must be an integer between 2 and 8 GiB.")
            if ram_gb > self.safe_ram_limit():
                raise RuntimeError(
                    "Not enough available RAM; reduce the allocation or close other applications."
                )
            with self._lock:
                if self.is_running or self._stopping:
                    raise RuntimeError("The local server is already running or stopping.")
                self._on_log, self._on_status = on_log_callback, on_playit_status
            metadata_path = self.base_dir / ".hexserver.json"
            metadata = (
                json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
            )
            arguments = launch_arguments(self.base_dir, metadata)
            self._validate_configuration()
            java = install_jdk(
                self.java_dir, transport=self.http, status_callback=lambda text: self._notify("status", text)
            )
            playit = self.ensure_playit_binary()
            options = dict(
                cwd=str(self.base_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._lock:
                self._generation += 1
                generation = self._generation
                self._last_tunnel_lookup = None
                self._tunnel_address = ""
                self._tunnel_disabled = False
                self._stopping = False
                self._server = self._popen(
                    [java, f"-Xmx{ram_gb}G", "-Xms2G", *arguments],
                    stdin=subprocess.PIPE,
                    **options,
                )
                server = self._server
            threading.Thread(
                target=self._read_output, args=(server, "Minecraft", generation), daemon=True
            ).start()
            try:
                with self._lock:
                    if self._stopping or server.poll() is not None:
                        raise RuntimeError("Minecraft stopped during startup.")
                    self._playit = self._popen(
                        [playit, "--stdout", "--secret_path", str(self.base_dir / "playit.toml"), "start"],
                        stdin=subprocess.DEVNULL,
                        **options,
                    )
                    agent = self._playit
                threading.Thread(
                    target=self._read_output, args=(agent, "Playit", generation), daemon=True
                ).start()
            except Exception:
                self.stop_server()
                raise
            self._notify("status", "Create a Minecraft Java tunnel in Playit pointing to 127.0.0.1:25565.")

    def stop_server(self):
        """Graceful world save first; bounded forced fallback for unresponsive processes."""
        with self._stop_lock:
            with self._lock:
                self._stopping = True
                server, agent = self._server, self._playit
            failures = []
            installer = self._installer
            if installer is not None and installer.poll() is None:
                try:
                    try:
                        installer.terminate()
                    except OSError:
                        installer.kill()
                    try:
                        installer.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        installer.kill()
                        installer.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    failures.append(f"Server installer could not be stopped: {exc}")
            if installer is not None and installer.poll() is not None:
                self._installer = None
            if agent is not None and agent.poll() is None:
                try:
                    agent.terminate()
                    try:
                        agent.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        agent.kill()
                        agent.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    failures.append(f"Playit could not be stopped: {exc}")
            if server is not None and server.poll() is None:
                try:
                    self._log("[Minecraft] Saving world and stopping…")
                    try:
                        if server.stdin is not None:
                            server.stdin.write("stop\n")
                            server.stdin.flush()
                        server.wait(timeout=60)
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        self._log(
                            "[Minecraft] Graceful stop timed out; forcing termination. "
                            "Check the world backup before restarting."
                        )
                        server.terminate()
                        try:
                            server.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            server.kill()
                            server.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    failures.append(f"Minecraft could not be stopped: {exc}")
            with self._lock:
                if server is None or server.poll() is not None:
                    self._server = None
                if agent is None or agent.poll() is not None:
                    self._playit = None
                self._stopping = False
                still_running = self.is_running
                if not still_running:
                    # Output readers can finish after wait() has returned on
                    # this thread. Retire their generation before releasing the
                    # lock so a normal stop cannot become an unexpected-exit alert.
                    self._generation += 1
            if server is not None and server.poll() is not None and server.stdin is not None:
                try:
                    server.stdin.close()
                except (OSError, ValueError):
                    pass
            if still_running:
                raise RuntimeError(
                    "; ".join(failures) or "A local server process is still running. Retry Stop."
                )
            for failure in failures:
                self._log(failure)
            if not still_running:
                self._notify("stopped", "")

    def _validate_configuration(self):
        def values(filename):
            path = self.base_dir / filename
            if not path.is_file():
                return {}
            result = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(("#", "!")) or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
            return result

        if values("eula.txt").get("eula", "true").lower() != "true":
            raise RuntimeError("The Minecraft EULA is not accepted in HexServer/eula.txt.")
        config = values("server.properties")
        if config.get("server-port", "25565") != "25565":
            raise RuntimeError("Set server-port=25565 in HexServer/server.properties for this Playit tunnel.")
        if config.get("server-ip", "127.0.0.1") not in {"", "127.0.0.1", "localhost", "::1"}:
            raise RuntimeError(
                "Set server-ip=127.0.0.1 in HexServer/server.properties for this Playit tunnel."
            )
