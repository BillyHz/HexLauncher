"""Temurin Java installer with verified downloads and staged replacement."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests

from src.hexlauncher.core.filesystem import replace_directory
from src.hexlauncher.core.modrinth import safe_path

logger = logging.getLogger(__name__)
ASSETS_URL = (
    "https://api.adoptium.net/v3/assets/latest/21/hotspot"
    "?architecture=x64&image_type=jdk&os=windows&vendor=eclipse"
)
FALLBACK_URL = (
    "https://github.com/adoptium/temurin21-binaries/releases/download/"
    "jdk-21.0.2%2B13/OpenJDK21U-jdk_x64_windows_hotspot_21.0.2_13.zip"
)


def install_jdk(java_dir: str | Path, progress_callback=None, status_callback=None, transport=None) -> str:
    """Download Windows x64 Java 21. Never extract or publish an unverified archive."""
    destination = Path(java_dir)
    executable = destination / "bin" / "java.exe"
    if executable.is_file():
        return str(executable)
    http = transport or requests
    headers = {"User-Agent": "BillyHz/HexLauncher/0.7.0-beta.1 (https://github.com/BillyHz/HexLauncher)"}

    def request(url, **kwargs):
        if urlparse(url).scheme != "https":
            raise RuntimeError("La descarga de Java debe utilizar HTTPS.")
        response = http.get(url, timeout=(10, 60), headers=headers, **kwargs)
        try:
            response.raise_for_status()
            if urlparse(response.url).scheme != "https":
                raise RuntimeError("Redirección de Java insegura.")
        except Exception:
            response.close()
            raise
        return response

    try:
        try:
            with request(ASSETS_URL) as response:
                package = response.json()[0]["binary"]["package"]
            url, published = package["link"], package["checksum"]
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("Adoptium lookup failed; using verified fallback: %s", exc)
            url = FALLBACK_URL
            with request(url + ".sha256.txt") as response:
                published = response.text.strip().split()[0]
        if not isinstance(published, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", published):
            raise RuntimeError("Adoptium no proporcionó un SHA-256 válido.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".hex-java-", dir=destination.parent) as temporary:
            archive_path = Path(temporary, "download.zip")
            if status_callback:
                status_callback("Descargando Java 21…")
            digest, done = hashlib.sha256(), 0
            with request(url, stream=True) as response, archive_path.open("wb") as output:
                total = int(response.headers.get("content-length", 0))
                for chunk in response.iter_content(256 * 1024):
                    if not chunk:
                        continue
                    done += len(chunk)
                    if done > 1024**3:
                        raise RuntimeError("El archivo Java excede el límite de 1 GB.")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress_callback:
                        progress_callback(done, total)
                if total and done != total:
                    raise RuntimeError("Descarga de Java incompleta.")
            if digest.hexdigest() != published.lower():
                raise RuntimeError("Fallo de verificación SHA-256 de Java.")
            if status_callback:
                status_callback("Extrayendo y validando Java…")
            extracted = Path(temporary, "extracted")
            extracted.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                entries = archive.infolist()
                if sum(file.file_size for file in entries) > 2 * 1024**3:
                    raise RuntimeError("Java descomprimido excede el límite de 2 GB.")
                roots = {
                    PurePosixPath(file.filename).parts[0]
                    for file in entries
                    if len(PurePosixPath(file.filename).parts) == 3
                    and PurePosixPath(file.filename).parts[1:] == ("bin", "java.exe")
                }
                if len(roots) != 1:
                    raise RuntimeError("El ZIP no contiene un único runtime Java válido.")
                root = roots.pop()
                seen = set()
                for file in entries:
                    relative = file.filename.rstrip("/")
                    if not relative:
                        continue
                    target = safe_path(extracted, relative)
                    if PurePosixPath(relative).parts[0] != root or stat.S_ISLNK(file.external_attr >> 16):
                        raise RuntimeError("El ZIP Java contiene rutas o enlaces inválidos.")
                    key = str(target).casefold()
                    if key in seen:
                        raise RuntimeError("El ZIP Java contiene rutas duplicadas.")
                    seen.add(key)
                    if file.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(file) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
            staged = extracted / root
            if not (staged / "bin" / "java.exe").is_file():
                raise RuntimeError("Java extraído no contiene bin/java.exe.")
            replace_directory(staged, destination)
        return str(executable)
    except (requests.RequestException, OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"No se pudo instalar Java: {exc}") from exc
