"""Labrinth v2 client. Progress callbacks execute on the calling worker thread."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

import requests

API_BASE = "https://api.modrinth.com/v2"
USER_AGENT = "BillyHz/HexLauncher/0.7.0 (https://github.com/BillyHz/HexLauncher)"
_MOD_LOCK = threading.RLock()
_MOD_REGISTRY = ".hexmods.json"


class ModrinthError(RuntimeError):
    """API, download, dependency or pack validation failure."""


def safe_path(root, relative):
    """Reject traversal, Windows device names and symlink escapes."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ModrinthError(f"Ruta inválida: {relative!r}")
    if relative.startswith("/") or any(p in ("..", ".") for p in relative.split("/")):
        raise ModrinthError(f"Ruta fuera de la instancia: {relative}")
    parts = PurePosixPath(relative).parts
    for part in parts:
        if part.endswith((" ", ".")) or re.search(r'[<>"|?*\x00-\x1f]', part):
            raise ModrinthError(f"Ruta inválida: {relative}")
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])", part.split(".")[0]):
            raise ModrinthError(f"Nombre reservado: {relative}")
    base = Path(root).resolve()
    target = (base / Path(*parts)).resolve()
    if target == base or not target.is_relative_to(base):
        raise ModrinthError(f"Ruta fuera de la instancia: {relative}")
    return target


class ModrinthClient:
    """Stateless HTTP client usable by independent workers.

    Download callbacks receive (bytes_done, bytes_total), pack callbacks receive
    (files_done, files_total). Unknown download lengths are reported as zero.
    """

    def __init__(self, user_agent=USER_AGENT, timeout=(10, 60), transport=None):
        self.headers = {"User-Agent": user_agent}
        self.timeout = timeout
        self.transport = transport or requests

    def _get(self, url, **kwargs):
        if not isinstance(url, str) or urlparse(url).scheme != "https" or not urlparse(url).hostname:
            raise ModrinthError("Las descargas deben utilizar HTTPS.")
        try:
            response = self.transport.get(url, headers=self.headers, timeout=self.timeout, **kwargs)
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", response.headers.get("X-Ratelimit-Reset", "60"))
                response.close()
                raise ModrinthError(f"Límite de Modrinth alcanzado. Reintenta en {retry} segundos.")
            response.raise_for_status()
            if urlparse(response.url).scheme != "https":
                response.close()
                raise ModrinthError("Redirección insegura.")
            return response
        except requests.RequestException as exc:
            if exc.response is not None:
                exc.response.close()
            raise ModrinthError(f"Error de conexión con Modrinth: {exc}") from exc

    def _json(self, endpoint, params=None):
        with self._get(f"{API_BASE}/{endpoint}", params=params) as response:
            try:
                return response.json()
            except ValueError as exc:
                raise ModrinthError("Modrinth devolvió JSON inválido.") from exc

    def search_mods(self, query, loader, game_version, limit=20, offset=0, *, project_type="mod"):
        if project_type not in ("mod", "modpack") or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Tipo, límite u offset inválido.")
        facets = [[f"project_type:{project_type}"]]
        if loader and loader.lower() != "vanilla":
            facets.append([f"categories:{loader.lower()}"])
        if game_version:
            facets.append([f"versions:{game_version}"])
        data = self._json(
            "search", {"query": query, "facets": json.dumps(facets), "limit": limit, "offset": offset}
        )
        if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
            raise ModrinthError("Respuesta de búsqueda inválida.")
        return data["hits"]

    def get_project_versions(self, project_id, loader, game_version):
        params = {}
        if loader and loader.lower() != "vanilla":
            params["loaders"] = json.dumps([loader.lower()])
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        data = self._json(f"project/{quote(str(project_id), safe='')}/version", params)
        if not isinstance(data, list):
            raise ModrinthError("Lista de versiones inválida.")
        return sorted(data, key=lambda v: v.get("date_published", ""), reverse=True)

    def get_version(self, version_id):
        data = self._json(f"version/{quote(str(version_id), safe='')}")
        if not isinstance(data, dict) or not data.get("id"):
            raise ModrinthError("Versión inválida.")
        return data

    def resolve_dependencies(self, version_id, *, loader=None, game_version=None):
        """Required versions only, dependencies first, with cycle/conflict detection."""
        root = self.get_version(version_id)
        loaders = [loader.lower()] if loader else root.get("loaders", [])
        games = [game_version] if game_version else root.get("game_versions", [])
        visited, active, projects, result = set(), set(), {}, []

        def visit(version):
            vid = version["id"]
            if vid in active:
                raise ModrinthError("Dependencias circulares detectadas.")
            if vid in visited:
                return
            if loaders and not set(loaders).intersection(version.get("loaders", [])):
                raise ModrinthError(f"Dependencia incompatible con {loaders}: {vid}")
            if games and not set(games).intersection(version.get("game_versions", [])):
                raise ModrinthError(f"Dependencia incompatible con Minecraft {games}: {vid}")
            pid = version.get("project_id", vid)
            if pid in projects and projects[pid] != vid:
                raise ModrinthError(f"Versiones requeridas en conflicto para {pid}.")
            projects[pid] = vid
            active.add(vid)
            for dep in version.get("dependencies", []):
                if dep.get("dependency_type") != "required":
                    continue
                if dep.get("version_id"):
                    child = self.get_version(dep["version_id"])
                elif dep.get("project_id"):
                    candidates = self._json(
                        f"project/{quote(dep['project_id'], safe='')}/version",
                        {"loaders": json.dumps(loaders), "game_versions": json.dumps(games)},
                    )
                    if not isinstance(candidates, list) or not candidates:
                        raise ModrinthError(f"No hay dependencia compatible: {dep['project_id']}")
                    child = max(candidates, key=lambda v: v.get("date_published", ""))
                else:
                    raise ModrinthError(f"Dependencia externa no resoluble: {dep.get('file_name', '?')}")
                visit(child)
            active.remove(vid)
            visited.add(vid)
            if vid != root["id"]:
                result.append(version)

        try:
            visit(root)
        except RecursionError as exc:
            raise ModrinthError("Demasiados niveles de dependencias.") from exc
        return result

    def download_file(
        self,
        url,
        destination_path,
        expected_hash_sha512=None,
        progress_callback=None,
        *,
        expected_hash_sha1=None,
        expected_size=None,
    ):
        """Verify a temporary download before atomically replacing the destination."""
        for value, length in ((expected_hash_sha512, 128), (expected_hash_sha1, 40)):
            if value is not None and not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value):
                raise ModrinthError("Hash esperado inválido.")
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".hex-download-", suffix=".part", dir=dest.parent)
        sha512, sha1, done = hashlib.sha512(), hashlib.sha1(), 0
        try:
            with os.fdopen(fd, "wb") as output:
                with self._get(url, stream=True) as response:
                    total = int(response.headers.get("content-length", 0))
                    if progress_callback:
                        progress_callback(0, total)
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        output.write(chunk)
                        sha512.update(chunk)
                        sha1.update(chunk)
                        done += len(chunk)
                        if progress_callback:
                            progress_callback(done, total)
                    if total and done != total:
                        raise ModrinthError("Descarga incompleta.")
            if expected_size is not None and done != expected_size:
                raise ModrinthError("El tamaño no coincide con el manifiesto.")
            if expected_hash_sha512 and sha512.hexdigest() != expected_hash_sha512.lower():
                raise ModrinthError("SHA-512 incorrecto.")
            if expected_hash_sha1 and sha1.hexdigest() != expected_hash_sha1.lower():
                raise ModrinthError("SHA-1 incorrecto.")
            os.replace(temporary, dest)
            if progress_callback:
                progress_callback(done, done)
            return str(dest)
        except (requests.RequestException, OSError, ValueError) as exc:
            raise ModrinthError(f"No se pudo descargar {dest.name}: {exc}") from exc
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def primary_file(version, suffix=".jar"):
        files = [
            f
            for f in version.get("files", [])
            if f.get("filename", "").lower().endswith(suffix)
            and f.get("file_type") not in ("sources-jar", "dev-jar", "javadoc-jar")
        ]
        if not files:
            raise ModrinthError(f"No hay archivo {suffix} instalable.")
        return next((f for f in files if f.get("primary")), files[0])

    @staticmethod
    def read_installed_mods(mods_dir):
        """Read managed projects; untracked jars always remain user owned."""
        path = safe_path(mods_dir, _MOD_REGISTRY)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("format") != 1 or not isinstance(data.get("projects"), dict):
                raise ValueError("Invalid registry")
            for pid, record in data["projects"].items():
                if not isinstance(pid, str) or not isinstance(record, dict):
                    raise ValueError("Invalid project")
                name = record["filename"]
                if "/" in name or "\\" in name or not name.lower().endswith(".jar"):
                    raise ValueError("Invalid filename")
                safe_path(mods_dir, name)
                if not isinstance(record["dependencies"], dict) or not isinstance(record["version_id"], str):
                    raise ValueError("Invalid version")
            return data["projects"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ModrinthError(f"Registro de mods inválido: {exc}") from exc

    @staticmethod
    def _commit_mods(destination, staged, removals, projects):
        """Back up every affected file before committing jars and their registry."""
        registry = Path(staged) / _MOD_REGISTRY
        registry.write_text(json.dumps({"format": 1, "projects": projects}, indent=2), encoding="utf-8")
        additions = {p.name: p for p in Path(staged).iterdir() if p.is_file()}
        affected = set(additions) | set(removals)
        with tempfile.TemporaryDirectory(prefix=".hex-backup-", dir=destination.parent) as backup:
            original = set()
            for name in affected:
                target = safe_path(destination, name)
                if target.exists():
                    shutil.copy2(target, Path(backup) / name)
                    original.add(name)
            try:
                for name in removals:
                    safe_path(destination, name).unlink(missing_ok=True)
                for name, source in additions.items():
                    os.replace(source, safe_path(destination, name))
            except OSError as exc:
                errors = []
                for name in affected:
                    try:
                        target = safe_path(destination, name)
                        if name in original:
                            shutil.copy2(Path(backup) / name, target)
                        else:
                            target.unlink(missing_ok=True)
                    except OSError as rollback_error:
                        errors.append(str(rollback_error))
                if errors:
                    # Keep recovery copies outside the temporary directory.
                    recovery = Path(tempfile.mkdtemp(prefix=".hex-recovery-", dir=destination.parent))
                    shutil.copytree(backup, recovery, dirs_exist_ok=True)
                    raise ModrinthError(f"Rollback incompleto; copia de recuperación: {recovery}") from exc
                raise ModrinthError(
                    f"No se pudo guardar la instalación; se restauraron los mods: {exc}"
                ) from exc

    def uninstall_mod(self, mods_dir, filename):
        """Remove one jar and metadata atomically; retain dependencies for other mods."""
        with _MOD_LOCK:
            destination = Path(mods_dir)
            if (
                not isinstance(filename, str)
                or "/" in filename
                or "\\" in filename
                or not filename.lower().endswith(".jar")
            ):
                raise ModrinthError("Nombre de mod inválido.")
            safe_path(destination, filename)
            projects = self.read_installed_mods(destination)
            removed = {pid for pid, r in projects.items() if r["filename"].casefold() == filename.casefold()}
            if any(set(r["dependencies"]) & removed for pid, r in projects.items() if pid not in removed):
                raise ModrinthError("Otro mod instalado requiere este mod.")
            projects = {pid: r for pid, r in projects.items() if pid not in removed}
            destination.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".hex-mods-", dir=destination.parent) as staging:
                self._commit_mods(destination, staging, [filename], projects)

    def install_mod(self, project_id, loader, game_version, mods_dir, progress_callback=None):
        with _MOD_LOCK:
            return self._install_mod(project_id, loader, game_version, mods_dir, progress_callback)

    def _install_mod(self, project_id, loader, game_version, mods_dir, progress_callback=None):
        versions = self.get_project_versions(project_id, loader, game_version)
        if not versions:
            raise ModrinthError("No hay versión compatible de este mod.")
        root = versions[0]
        plan = self.resolve_dependencies(root["id"], loader=loader, game_version=game_version) + [root]
        destination = Path(mods_dir)
        destination.mkdir(parents=True, exist_ok=True)
        projects = self.read_installed_mods(destination)
        planned = {v.get("project_id", v["id"]): v for v in plan}
        updated = dict(projects)
        removals = set()
        for pid, version in planned.items():
            requirements = {}
            for dep in version.get("dependencies", []):
                if dep.get("dependency_type") == "required":
                    child = next(
                        (
                            v
                            for v in plan
                            if v["id"] == dep.get("version_id")
                            or v.get("project_id") == dep.get("project_id")
                        ),
                        None,
                    )
                    if child:
                        requirements[child.get("project_id", child["id"])] = dep.get("version_id")
            updated[pid] = {
                "version_id": version["id"],
                "filename": self.primary_file(version)["filename"],
                "hashes": self.primary_file(version).get("hashes", {}),
                "dependencies": requirements,
                "incompatible": [
                    {"project_id": dep.get("project_id"), "version_id": dep.get("version_id")}
                    for dep in version.get("dependencies", [])
                    if dep.get("dependency_type") == "incompatible"
                ],
            }
            if pid in projects and projects[pid]["filename"] != updated[pid]["filename"]:
                removals.add(projects[pid]["filename"])
        for record in updated.values():
            for conflict in record.get("incompatible", []):
                if any(
                    (conflict.get("version_id") and other["version_id"] == conflict["version_id"])
                    or (not conflict.get("version_id") and pid == conflict.get("project_id"))
                    for pid, other in updated.items()
                ):
                    raise ModrinthError("Mods incompatibles en conflicto con la instalación.")
            for required_pid, required_version in record["dependencies"].items():
                if required_pid not in updated or (
                    required_version and updated[required_pid]["version_id"] != required_version
                ):
                    raise ModrinthError("Versiones requeridas en conflicto con los mods instalados.")
        names = set()
        with tempfile.TemporaryDirectory(prefix=".hex-mods-", dir=destination.parent) as staging:
            for i, version in enumerate(plan):
                file = self.primary_file(version)
                name = file["filename"]
                if "/" in name or "\\" in name or name.casefold() in names:
                    raise ModrinthError("Nombre de archivo duplicado o inválido.")
                names.add(name.casefold())
                target = safe_path(staging, name)
                safe_path(destination, name)
                owners = [
                    pid
                    for pid, record in projects.items()
                    if record["filename"].casefold() == name.casefold()
                ]
                pid = version.get("project_id", version["id"])
                if owners and owners != [pid]:
                    raise ModrinthError("El archivo pertenece a otro proyecto instalado.")
                if not owners and safe_path(destination, name).exists():
                    raise ModrinthError("Ya existe un mod manual con ese nombre; no se sobrescribirá.")
                hashes = file.get("hashes", {})
                if not (hashes.get("sha512") or hashes.get("sha1")):
                    raise ModrinthError("Modrinth no proporcionó un hash de integridad.")

                def progress(done, total, index=i):
                    if progress_callback:
                        progress_callback(index + (done / total if total else 0), len(plan))

                self.download_file(
                    file["url"],
                    target,
                    hashes.get("sha512"),
                    progress,
                    expected_hash_sha1=hashes.get("sha1"),
                    expected_size=file.get("size"),
                )
            self._commit_mods(destination, staging, removals, updated)
        return plan

    def install_mrpack(self, mrpack_path, instance_dir, progress_callback=None):
        """Install into a NEW instance, preserving pinned loader metadata.

        Optional client files are included; unsupported files skipped. Apply
        overrides then client-overrides. No instance is published on failure.
        """
        destination = Path(instance_dir)
        if destination.exists():
            raise ModrinthError("La instancia ya existe. Elige una carpeta nueva.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(mrpack_path) as archive:
                entries = archive.infolist()
                if sum(e.file_size for e in entries) > 4 * 1024**3:
                    raise ModrinthError("El modpack descomprimido excede 4 GB.")
                indices = [e for e in entries if e.filename == "modrinth.index.json"]
                if len(indices) != 1 or indices[0].file_size > 8 * 1024**2:
                    raise ModrinthError("Manifiesto ausente, duplicado o demasiado grande.")
                index = json.loads(archive.read(indices[0]).decode("utf-8"))
                if (
                    not isinstance(index, dict)
                    or index.get("formatVersion") != 1
                    or index.get("game") != "minecraft"
                    or not isinstance(index.get("files"), list)
                    or not isinstance(index.get("dependencies"), dict)
                    or not isinstance(index.get("name"), str)
                    or not index.get("versionId")
                ):
                    raise ModrinthError("modrinth.index.json no es válido.")
                deps = index["dependencies"]
                if not isinstance(deps.get("minecraft"), str) or not deps["minecraft"]:
                    raise ModrinthError("El pack no declara su versión de Minecraft.")
                if set(deps) - {"minecraft", "fabric-loader", "forge", "neoforge"}:
                    raise ModrinthError("Loader no soportado por HexLauncher.")
                if len(deps) > 2 or any(not isinstance(v, str) or not v for v in deps.values()):
                    raise ModrinthError("Dependencias de Minecraft/loaders inválidas.")
                if any(
                    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*", v) or ".." in v for v in deps.values()
                ):
                    raise ModrinthError("Identificador de Minecraft/loader inválido.")
                with tempfile.TemporaryDirectory(prefix=".hex-pack-", dir=destination.parent) as staging:
                    files, seen = [], set()
                    for file in index["files"]:
                        if not isinstance(file, dict):
                            raise ModrinthError("Entrada de archivo inválida.")
                        target = safe_path(staging, file.get("path"))
                        key = str(target).casefold()
                        if key in seen:
                            raise ModrinthError("Rutas duplicadas en el manifiesto.")
                        seen.add(key)
                        hashes = file.get("hashes", {})
                        downloads, env = file.get("downloads"), file.get("env", {})
                        if (
                            not isinstance(hashes, dict)
                            or not hashes.get("sha512")
                            or not hashes.get("sha1")
                            or not isinstance(downloads, list)
                            or not downloads
                            or not isinstance(file.get("fileSize"), int)
                            or file["fileSize"] < 0
                            or not isinstance(env, dict)
                        ):
                            raise ModrinthError("Archivo sin hashes, tamaño o descargas válidas.")
                        for algorithm, length in (("sha512", 128), ("sha1", 40)):
                            if not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", str(hashes[algorithm])):
                                raise ModrinthError("Hash inválido en el manifiesto.")
                        if any(not isinstance(u, str) or urlparse(u).scheme != "https" for u in downloads):
                            raise ModrinthError("URL inválida en el modpack.")
                        if env.get("client", "required") not in ("required", "optional", "unsupported"):
                            raise ModrinthError("Entorno cliente inválido.")
                        if env.get("client") != "unsupported":
                            files.append((file, target))
                    overrides = []
                    for prefix in ("overrides/", "client-overrides/"):
                        layer = set()
                        for entry in entries:
                            if not entry.filename.startswith(prefix) or entry.is_dir():
                                continue
                            target = safe_path(staging, entry.filename[len(prefix) :])
                            if stat.S_ISLNK(entry.external_attr >> 16):
                                raise ModrinthError("No se permiten enlaces simbólicos.")
                            key = str(target).casefold()
                            if key in layer:
                                raise ModrinthError("Override duplicado.")
                            layer.add(key)
                            overrides.append((entry, target))
                    total = len(files) + len(overrides)
                    if progress_callback:
                        progress_callback(0, total)
                    for i, (file, target) in enumerate(files):
                        last_error = None

                        def download_progress(done, size, position=i):
                            if progress_callback:
                                progress_callback(position + (done / size if size else 0), total)

                        for url in file["downloads"]:
                            try:
                                self.download_file(
                                    url,
                                    target,
                                    file["hashes"]["sha512"],
                                    download_progress,
                                    expected_hash_sha1=file["hashes"]["sha1"],
                                    expected_size=file["fileSize"],
                                )
                                last_error = None
                                break
                            except ModrinthError as exc:
                                last_error = exc
                        if last_error:
                            raise last_error
                        if progress_callback:
                            progress_callback(i + 1, total)
                    for i, (entry, target) in enumerate(overrides, start=len(files)):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as source, open(target, "wb") as output:
                            shutil.copyfileobj(source, output)
                        if progress_callback:
                            progress_callback(i + 1, total)
                    Path(staging, ".hexpack.json").write_text(json.dumps(index), encoding="utf-8")
                    os.rename(staging, destination)
                return index
        except (zipfile.BadZipFile, KeyError, ValueError, OSError, RuntimeError) as exc:
            if isinstance(exc, ModrinthError):
                raise
            raise ModrinthError(f"No se pudo instalar el modpack: {exc}") from exc


def search_mods(query, mc_version="", loader="", limit=20):
    return ModrinthClient().search_mods(query, loader, mc_version, limit)


def get_project_versions(slug_or_id, mc_version="", loader=""):
    return ModrinthClient().get_project_versions(slug_or_id, loader, mc_version)


def download_file(url, dest_path, sha1_expected=""):
    return ModrinthClient().download_file(url, dest_path, expected_hash_sha1=sha1_expected or None)
