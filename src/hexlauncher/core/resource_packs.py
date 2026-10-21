"""Import resource-pack ZIPs without extracting or overwriting existing packs."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path

MAX_PACK_SIZE = 512 * 1024 * 1024
MAX_UNPACKED_SIZE = 2 * 1024 * 1024 * 1024


def install_resource_pack(client, project_id, game_version, game_directory, progress_callback=None) -> Path:
    """Download a compatible Modrinth ZIP, verify it, then import without extraction."""
    from src.hexlauncher.core.modrinth import ModrinthError, safe_path

    # Resource packs are filtered by Minecraft version, never by the mod loader.
    versions = client.get_project_versions(project_id, "", game_version)
    compatible = [version for version in versions if game_version in version.get("game_versions", [])]
    if not compatible:
        raise ModrinthError("No hay un pack de texturas compatible con esta versión de Minecraft.")
    release = next((version for version in compatible if version.get("version_type") == "release"), compatible[0])
    file = client.primary_file(release, ".zip")
    hashes = file.get("hashes", {})
    if not (hashes.get("sha512") or hashes.get("sha1")):
        raise ModrinthError("El pack de texturas no tiene hashes de integridad.")
    size = file.get("size")
    if type(size) is not int or not 0 < size <= MAX_PACK_SIZE:
        raise ModrinthError("El pack supera el límite de 512 MB.")
    name = file["filename"]
    if "/" in name or "\\" in name:
        raise ModrinthError("Nombre de pack de texturas inválido.")
    with tempfile.TemporaryDirectory(prefix=".hex-textures-") as temporary:
        source = safe_path(temporary, name)
        client.download_file(
            file["url"], source, hashes.get("sha512"), progress_callback,
            expected_hash_sha1=hashes.get("sha1"), expected_size=size, max_size=MAX_PACK_SIZE,
        )
        return import_resource_pack(source, Path(game_directory))


def import_resource_pack(source: Path, game_directory: Path) -> Path:
    if source.suffix.lower() != ".zip" or not source.is_file():
        raise ValueError("Selecciona un pack de texturas en formato ZIP.")
    if source.stat().st_size > MAX_PACK_SIZE:
        raise ValueError("El pack supera el límite de 512 MB.")
    directory = game_directory / "resourcepacks"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    destination = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".hex-pack-", suffix=".tmp", delete=False
        ) as out:
            temporary = Path(out.name)
            with source.open("rb") as stream:
                total = 0
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > MAX_PACK_SIZE:
                        raise ValueError("El pack supera el límite de 512 MB.")
                    out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        with zipfile.ZipFile(temporary) as archive:
            entries = archive.infolist()
            if sum(entry.file_size for entry in entries) > MAX_UNPACKED_SIZE:
                raise ValueError("El contenido del pack es demasiado grande.")
            metadata = archive.getinfo("pack.mcmeta")
            if metadata.file_size > 1024 * 1024:
                raise ValueError("El archivo pack.mcmeta es demasiado grande.")
            data = json.loads(archive.read(metadata).decode("utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("pack"), dict):
                raise ValueError("El pack.mcmeta no contiene una definición de pack válida.")
            if archive.testzip() is not None:
                raise ValueError("El ZIP del pack está dañado.")
        # Exclusive reservation avoids overwriting a pack, including concurrent imports.
        for number in range(10000):
            name = source.name if number == 0 else f"{source.stem} ({number}){source.suffix}"
            candidate = directory / name
            try:
                with candidate.open("xb"):
                    pass
            except FileExistsError:
                continue
            destination = candidate
            break
        if destination is None:
            raise ValueError("No se pudo encontrar un nombre disponible para el pack.")
        os.replace(temporary, destination)
        published = True
        return destination
    except (zipfile.BadZipFile, KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ZIP inválido: el pack debe incluir pack.mcmeta en la raíz.") from exc
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
        if destination and not published:
            destination.unlink(missing_ok=True)
