"""Publish staged runtime directories without destroying the previous installation."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def replace_directory(staged: Path, destination: Path) -> None:
    """Rename a sibling staging directory into place, rolling back on failure."""
    staged, destination = staged.resolve(), destination.absolute()
    if destination.is_symlink():
        raise RuntimeError("No se puede reemplazar una carpeta enlazada.")
    if staged == destination or destination.is_relative_to(staged) or staged.is_relative_to(destination):
        raise RuntimeError("Rutas de instalación inválidas.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(f".{destination.name}-backup-{uuid.uuid4().hex}")
    existed = destination.exists()
    if existed:
        os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except OSError as exc:
        if existed:
            try:
                os.replace(backup, destination)
            except OSError as rollback:
                raise RuntimeError(
                    f"No se pudo restaurar la instalación. Copia preservada en {backup}"
                ) from rollback
        raise RuntimeError(f"No se pudo publicar la instalación: {exc}") from exc
    if existed:
        try:
            shutil.rmtree(backup)
        except OSError:
            logger.warning("Installation succeeded; previous backup retained at %s", backup, exc_info=True)


def sync_mods(source: str | Path, destination: str | Path) -> int:
    """Stage the complete new mod set, preserve other files, publish or roll back."""
    source, destination = Path(source), Path(destination)
    if destination.is_symlink() or source.is_symlink():
        raise RuntimeError("La carpeta de mods no puede ser un enlace.")
    source.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    try:
        with tempfile.TemporaryDirectory(prefix=".hex-sync-", dir=destination.parent) as temporary:
            staged = Path(temporary, "mods")
            staged.mkdir()
            if destination.exists():
                for file in destination.iterdir():
                    if file.is_file() and (file.suffix.lower() == ".jar" or file.name == ".hexmods.json"):
                        continue
                    if file.is_symlink():
                        raise RuntimeError(f"No se puede sincronizar el enlace {file.name}.")
                    if file.is_dir():
                        shutil.copytree(file, staged / file.name, symlinks=True)
                    else:
                        shutil.copy2(file, staged / file.name)
            for file in source.iterdir():
                if file.suffix.lower() != ".jar" and file.name != ".hexmods.json":
                    continue
                if file.is_symlink() or not file.is_file():
                    raise RuntimeError(f"Archivo de mod inválido: {file.name}")
                shutil.copy2(file, staged / file.name)
                if file.suffix.lower() == ".jar":
                    copied += 1
            replace_directory(staged, destination)
        return copied
    except OSError as exc:
        raise RuntimeError(f"No se pudieron sincronizar los mods: {exc}") from exc
