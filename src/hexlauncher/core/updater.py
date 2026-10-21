"""Verified GitHub updates and a separate Windows replacement process.

Only the executable is replaced. Settings, worlds and instances stay in place.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from src.hexlauncher.version import VERSION

REPOSITORY = "BillyHz/HexLauncher"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_SIZE = 200 * 1024 * 1024
logger = logging.getLogger(__name__)


def version_key(value: str) -> tuple[int, int, int, int, int]:
    if not isinstance(value, str):
        raise ValueError("Unsupported release version")
    # Historical releases used tags such as vAlpha0.7.0, even with GitHub's
    # prerelease flag unset. Preserve their prerelease ordering, never upgrade
    # them into stable releases just by stripping the prefix.
    legacy = re.fullmatch(r"v?(alpha|beta|rc)(\d+)\.(\d+)\.(\d+)", value, re.IGNORECASE)
    if legacy:
        return (int(legacy[2]), int(legacy[3]), int(legacy[4]),
                {"alpha": 0, "beta": 1, "rc": 2}[legacy[1].lower()], 0)
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?", value)
    if not match:
        raise ValueError("Unsupported release version")
    return (
        int(match[1]),
        int(match[2]),
        int(match[3]),
        {"alpha": 0, "beta": 1, "rc": 2, None: 3}[match[4]],
        int(match[5] or 0),
    )


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    size: int


def check_update(current: str = VERSION, session=None) -> Release | None:
    import requests

    client = session or requests
    response = client.get(
        API_URL,
        timeout=(10, 20),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"HexLauncher/{VERSION}",
        },
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name", "")
    current_key = version_key(current)
    try:
        candidate = version_key(tag)
    except ValueError:
        logger.warning("Ignoring unrecognized release tag: %r", tag)
        return None
    if candidate[3] != 3 or candidate <= current_key:
        return None
    for asset in data.get("assets", []):
        if asset.get("name") != "HexLauncher.exe" or asset.get("state") != "uploaded":
            continue
        url = asset.get("browser_download_url", "")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or not parsed.path.startswith(f"/{REPOSITORY}/releases/download/{tag}/")
        ):
            raise ValueError("Unexpected update download URL")
        digest = asset.get("digest") or ""
        if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
            raise ValueError("Release has no SHA-256 digest; update refused")
        size = asset.get("size")
        if type(size) is not int or not 0 < size <= MAX_SIZE:
            raise ValueError("Invalid update size")
        return Release(tag.removeprefix("v"), url, digest[7:].lower(), size)
    raise ValueError("Release is missing HexLauncher.exe")


def verify_file(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Update is not a Windows executable")
        stream.seek(0)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Update SHA-256 verification failed")


def download_update(release: Release, executable: Path, progress=None, session=None) -> Path:
    import requests

    client = session or requests
    # Staging on the same volume permits atomic replacement without elevation.
    directory = Path(tempfile.mkdtemp(prefix=".hex-update-", dir=executable.parent))
    destination = directory / "pending.exe"
    try:
        with client.get(release.url, stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            downloaded = 0
            with destination.open("xb") as stream:
                for chunk in response.iter_content(256 * 1024):
                    downloaded += len(chunk)
                    if downloaded > release.size or downloaded > MAX_SIZE:
                        raise ValueError("Update exceeds its published size")
                    stream.write(chunk)
                    if progress:
                        progress(downloaded / release.size)
                stream.flush()
                os.fsync(stream.fileno())
        if downloaded != release.size:
            raise ValueError("Incomplete update download")
        verify_file(destination, release.sha256)
        return destination
    except BaseException:
        destination.unlink(missing_ok=True)
        directory.rmdir()
        raise


def start_update(pending: Path, executable: Path, digest: str) -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic installation requires the Windows executable")
    verify_file(pending, digest)
    helper = pending.parent / "helper.exe"
    shutil.copy2(executable, helper)
    subprocess.Popen(
        [str(helper), "--apply-update", str(os.getpid()), str(executable), str(pending), digest],
        cwd=executable.parent,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def replace_executable(pending: Path, target: Path, digest: str, restart=None) -> None:
    """Keep a recoverable backup and restore it if replacement/restart fails."""
    verify_file(pending, digest)
    backup = pending.parent / "previous.exe"
    shutil.copy2(target, backup)
    replaced = False
    try:
        # Windows may keep the one-file bootloader open briefly after the UI exits.
        for attempt in range(50):
            try:
                os.replace(pending, target)
                replaced = True
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.2)
        if restart:
            restart(target)
    except BaseException:
        if replaced:
            os.replace(backup, target)
        raise
    if restart:
        # Cleanup is allowed only after replacement and restart succeeded. The
        # restarted launcher waits for GUI initialization before removing backups.
        try:
            (pending.parent / "completed.json").write_text(
                json.dumps({"target": str(target.resolve())}), encoding="utf-8"
            )
        except OSError:
            logger.warning("Could not mark completed update at %s", pending.parent, exc_info=True)


def cleanup_updates(executable: Path) -> bool:
    """Remove completed update artifacts; retain failed/unrecognized staging.

    Return True if Windows still has an artifact open, so startup can retry.
    Delete only known files directly inside a real sibling staging directory.
    """
    executable = executable.resolve()
    retry = False
    for directory in executable.parent.glob(".hex-update-*"):
        try:
            if not directory.is_dir() or directory.resolve() != directory:
                continue
            marker = directory / "completed.json"
            entries = list(directory.iterdir())
            if any(
                entry.name not in {"helper.exe", "previous.exe", "completed.json"}
                or entry.is_symlink()
                or not entry.is_file()
                for entry in entries
            ):
                continue
            if json.loads(marker.read_text(encoding="utf-8")).get("target") != str(executable):
                continue
            # Try the helper first: Windows locks it until its process exits.
            (directory / "helper.exe").unlink(missing_ok=True)
            (directory / "previous.exe").unlink(missing_ok=True)
            marker.unlink()
            directory.rmdir()
        except (ValueError, AttributeError):
            continue
        except OSError:
            retry = True
    return retry


def apply_update(arguments: list[str]) -> int:
    """Entry point in the copied executable, before importing any GUI modules."""
    import ctypes
    from ctypes import wintypes

    if sys.platform != "win32" or not getattr(sys, "frozen", False) or len(arguments) != 4:
        return 1
    pid_text, target_text, pending_text, digest = arguments
    target, pending = Path(target_text).resolve(), Path(pending_text).resolve()
    helper = Path(sys.executable).resolve()
    if (
        pending.parent != helper.parent
        or pending.name != "pending.exe"
        or helper.name != "helper.exe"
        or not helper.parent.name.startswith(".hex-update-")
        or target.parent != helper.parent.parent
        or target.suffix.lower() != ".exe"
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or not pid_text.isdecimal()
    ):
        return 1
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, int(pid_text))
        if handle:
            try:
                if kernel.WaitForSingleObject(handle, 60000) != 0:
                    raise RuntimeError("Launcher did not close within 60 seconds")
            finally:
                kernel.CloseHandle(handle)
        elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: process already exited
            raise ctypes.WinError(ctypes.get_last_error())
        replace_executable(
            pending,
            target,
            digest,
            restart=lambda path: subprocess.Popen(
                [str(path)],
                cwd=path.parent,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
            ),
        )
        return 0
    except Exception as exc:
        (helper.parent / "error.txt").write_text(str(exc), encoding="utf-8")
        return 1
