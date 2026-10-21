"""Official Forge-family installers and isolated server runtime publication."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from src.hexlauncher.core.jdk import install_jdk

FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged"
FORGE_PROMOTIONS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"


def _text(manager, url):
    with manager._request(url) as response:
        return response.text


def _versions(manager, base):
    document = _text(manager, f"{base}/maven-metadata.xml")
    if len(document) > 4 * 1024 * 1024:
        raise RuntimeError("Loader metadata exceeds its safety limit.")
    return [
        element.text or "" for element in ET.fromstring(document).findall("./versioning/versions/version")
    ]


def resolve_installer(manager, minecraft_version, loader):
    """Choose a stable official release for the exact Minecraft version."""
    if loader == "forge":
        base, artifact, group = FORGE_MAVEN, "forge", "net/minecraftforge"
        releases = _versions(manager, base)
        candidates = [
            v for v in releases if re.fullmatch(re.escape(minecraft_version) + r"-\d+(?:\.\d+)+", v)
        ]
        promotion = manager._json(FORGE_PROMOTIONS).get("promos", {}).get(f"{minecraft_version}-recommended")
        preferred = f"{minecraft_version}-{promotion}" if promotion else None
    elif loader == "neoforge":
        if minecraft_version == "1.20.1":
            artifact, group = "forge", "net/neoforged"
            base = f"{NEOFORGE_MAVEN}/{artifact}"
            candidates = [v for v in _versions(manager, base) if re.fullmatch(r"1\.20\.1-\d+(?:\.\d+)+", v)]
        else:
            match = re.fullmatch(r"1\.(\d+)(?:\.(\d+))?", minecraft_version)
            if not match or int(match.group(1)) < 20:
                raise RuntimeError("NeoForge has no release for this Minecraft version.")
            prefix = f"{int(match.group(1))}.{int(match.group(2) or 0)}."
            artifact, group = "neoforge", "net/neoforged"
            base = f"{NEOFORGE_MAVEN}/{artifact}"
            candidates = [v for v in _versions(manager, base) if re.fullmatch(re.escape(prefix) + r"\d+", v)]
        preferred = None
    else:
        raise ValueError("Unsupported installer loader.")
    if not candidates:
        raise RuntimeError(f"No stable {loader.title()} release exists for Minecraft {minecraft_version}.")
    selected = (
        preferred
        if preferred in candidates
        else max(candidates, key=lambda v: tuple(map(int, re.findall(r"\d+", v))))
    )
    url = f"{base}/{selected}/{artifact}-{selected}-installer.jar"
    checksum_text = _text(manager, url + ".sha1").strip().split()
    checksum = checksum_text[0] if checksum_text else ""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", checksum):
        raise RuntimeError("The official installer checksum is invalid.")
    return {
        "artifact_version": selected,
        "url": url,
        "sha1": checksum,
        "argument_file": f"libraries/{group}/{artifact}/{selected}/win_args.txt",
    }


def launch_arguments(base_dir, metadata):
    """Only allow the installed runtime's known launch shape and confined files."""
    root = Path(base_dir).resolve()
    args = metadata.get("launch_args", ["-jar", "server.jar", "nogui"])
    if metadata.get("loader") in {"forge", "neoforge"}:
        if not isinstance(args, list) or len(args) != 2 or args[1] != "nogui" or not isinstance(args[0], str):
            raise RuntimeError("Invalid modded server launch metadata.")
        relative = args[0][1:] if args[0].startswith("@") else ""
        if not re.fullmatch(
            r"libraries/net/(?:minecraftforge/forge|neoforged/(?:forge|neoforge))/[a-zA-Z0-9_.+-]+/win_args\.txt",
            relative,
        ):
            raise RuntimeError("Invalid modded server argument file.")
        path = root / relative
    else:
        if args != ["-jar", "server.jar", "nogui"]:
            raise RuntimeError("Invalid server launch metadata.")
        path = root / "server.jar"
    if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise RuntimeError("Server runtime is missing or outside HexServer. Run setup again.")
    return args


def _run_installer(manager, java, installer, stage, callback, cancel_event=None):
    process = manager._popen(
        [java, "-jar", str(installer), "--installServer"],
        cwd=str(stage),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    manager._installer = process

    def read():
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    if callback:
                        try:
                            callback(f"[Installer] {line.strip()[:4000]}")
                        except Exception:
                            pass
        finally:
            if process.stdout is not None:
                process.stdout.close()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 900
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Server setup cancelled.")
            if time.monotonic() >= deadline:
                raise RuntimeError("Server installer timed out after 15 minutes.")
            try:
                code = process.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                continue
        if code:
            raise RuntimeError(f"Server installer failed (exit code {code}). See the installation log.")
    except BaseException:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise
    finally:
        reader.join(timeout=5)
        if process.poll() is not None:
            manager._installer = None


def install_modded_server(manager, version, loader, metadata, on_log_callback=None, cancel_event=None):
    """Install into staging; publish libraries and metadata with rollback."""

    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Server setup cancelled.")

    check_cancelled()
    release = resolve_installer(manager, version, loader)
    root = manager.base_dir
    with tempfile.TemporaryDirectory(prefix=".hex-server-install-", dir=root.parent) as temporary:
        stage = Path(temporary)
        installer = stage / "installer.jar"
        manager._download(release["url"], installer, {"sha1": release["sha1"]})
        check_cancelled()
        java = install_jdk(manager.java_dir, transport=manager.http, status_callback=on_log_callback)
        check_cancelled()
        _run_installer(manager, java, installer, stage, on_log_callback, cancel_event)
        metadata = {
            **metadata,
            "loader_version": release["artifact_version"],
            "launch_args": ["@" + release["argument_file"], "nogui"],
        }
        launch_arguments(stage, metadata)
        check_cancelled()
        libraries = stage / "libraries"
        if any(path.is_symlink() for path in libraries.rglob("*")):
            raise RuntimeError("Installer created an unsafe symbolic link.")
        destination = root / "libraries"
        if destination.is_symlink():
            raise RuntimeError("HexServer libraries cannot be a symbolic link.")
        backup = root / f".libraries-backup-{uuid.uuid4().hex}"
        replaced = destination.exists()
        if replaced:
            os.replace(destination, backup)
        try:
            os.replace(libraries, destination)
            manager._write_json(root / ".hexserver.json", metadata)
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination)
            if replaced:
                os.replace(backup, destination)
            raise
        if replaced:
            shutil.rmtree(backup, ignore_errors=True)
        return metadata
