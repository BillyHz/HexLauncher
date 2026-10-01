"""Cyberpunk Modrinth browser. Every network operation runs in a daemon worker."""

from __future__ import annotations

import io
import logging
import threading
import uuid
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from src.hexlauncher.core.modrinth import ModrinthClient, ModrinthError
from src.hexlauncher.i18n import tr
from src.hexlauncher.palette import BG, CARD, CARD_LIGHT, CYAN, CYAN_H, MUTED, SUCCESS, WARN, WHITE
from src.hexlauncher.paths import BASE_PATH
from src.hexlauncher.widgets import Badge

logger = logging.getLogger(__name__)


class ModrinthView(ctk.CTkFrame):
    def __init__(self, parent, launcher, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.launcher = launcher
        self.client = ModrinthClient()
        self._search_generation = 0
        self._busy = False
        self._images = []
        self._icon_slots = threading.BoundedSemaphore(4)
        self._build_view()

    def _build_view(self):
        controls = ctk.CTkFrame(self, fg_color=CARD)
        controls.pack(fill="x", padx=16, pady=8)
        self.kind_var = ctk.StringVar(value="Mods")
        ctk.CTkOptionMenu(
            controls,
            variable=self.kind_var,
            values=["Mods", "Modpacks"],
            command=lambda _: self.update_filter_badge(),
            fg_color=CYAN_H,
            width=110,
        ).pack(side="left", padx=8, pady=8)
        ctk.CTkButton(
            controls,
            text=tr("Importar .mrpack"),
            command=self._import_pack,
            fg_color=CYAN,
            hover_color=CYAN_H,
            text_color=BG,
            width=130,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            controls,
            text=tr("Mods instalados"),
            command=self.refresh_installed_mods,
            fg_color=CARD_LIGHT,
            width=130,
        ).pack(side="left", padx=4)
        self.filter_badge = Badge(controls, text=tr("Filtro: —"), fg_color=CARD_LIGHT, text_color=CYAN)
        self.filter_badge.pack(side="right", padx=8)

        search = ctk.CTkFrame(self, fg_color=CARD)
        search.pack(fill="x", padx=16, pady=(0, 8))
        self.search_var = ctk.StringVar()
        self.search_input = ctk.CTkEntry(
            search, textvariable=self.search_var, placeholder_text=tr("Buscar mods o modpacks…"), height=34
        )
        self.search_input.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self.search_input.bind("<Return>", lambda _: self.do_search())
        self.btn_search = ctk.CTkButton(
            search,
            text=tr("Buscar"),
            command=self.do_search,
            fg_color=CYAN,
            hover_color=CYAN_H,
            text_color=BG,
            width=85,
        )
        self.btn_search.pack(side="right", padx=8)
        self.status_label = ctk.CTkLabel(
            self,
            text=tr("Busca proyectos o importa un modpack."),
            anchor="w",
            text_color=MUTED,
            wraplength=900,
        )
        self.status_label.pack(fill="x", padx=20, pady=4)
        self.progress_bar = ctk.CTkProgressBar(self, progress_color=CYAN, height=5)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=20, pady=(0, 8))
        self.instance_var = ctk.StringVar(value=tr("Instalación habitual"))
        self.instance_menu = ctk.CTkOptionMenu(
            self,
            variable=self.instance_var,
            values=[tr("Instalación habitual")],
            command=self._select_instance,
            fg_color=CARD_LIGHT,
        )
        self.instance_menu.pack(fill="x", padx=16, pady=(0, 8))
        self.results_scroll = ctk.CTkScrollableFrame(self, fg_color=CARD)
        self.results_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.refresh_instances()
        self.update_filter_badge()

    def _post(self, callback):
        self.launcher.after(0, lambda: callback() if self.winfo_exists() else None)

    def _status(self, text, color=MUTED):
        self.status_label.configure(text=text, text_color=color)

    def _progress(self, done, total):
        # Throttle worker callbacks so large downloads cannot flood Tk's queue.
        import time

        now = time.monotonic()
        if total and done >= total or now - getattr(self, "_last_progress", 0) >= 0.1:
            self._last_progress = now
            value = min(done / total, 1) if total else 0
            self._post(lambda v=value: self.progress_bar.set(v))

    def update_filter_badge(self):
        self._search_generation += 1
        self._clear()
        self.filter_badge.configure_badge(
            text=f"{self.launcher.loader_var.get()} · MC {self.launcher.version_var.get()}"
        )

    def _filters(self):
        loader, version = self.launcher.loader_var.get(), self.launcher.version_var.get()
        if not version or version in (
            "Cargando…",
            "No se encontraron versiones",
            tr("Cargando…"),
            tr("No se encontraron versiones"),
        ):
            self._status(tr("Selecciona una versión de Minecraft."), WARN)
            return None
        if loader == "Vanilla" and self.kind_var.get() == "Mods":
            self._status(tr("Selecciona Fabric, Forge o NeoForge para instalar mods."), WARN)
            return None
        return loader, version

    def _clear(self):
        self._images.clear()
        for widget in self.results_scroll.winfo_children():
            widget.destroy()

    def do_search(self):
        filters = self._filters()
        query = self.search_var.get().strip()
        if not query or not filters:
            return
        loader, version = filters
        kind = "modpack" if self.kind_var.get() == "Modpacks" else "mod"
        self._search_generation += 1
        generation = self._search_generation
        self._clear()
        self._status(tr("Buscando '{query}'…").format(query=query))

        def worker():
            try:
                hits = self.client.search_mods(query, loader, version, project_type=kind)

                def render():
                    if generation != self._search_generation:
                        return
                    self._status(
                        tr("{count} resultado(s) para {loader} {version}").format(
                            count=len(hits), loader=loader, version=version
                        ),
                        SUCCESS,
                    )
                    for hit in hits:
                        self._render_mod_card(hit, version, loader, kind, generation)

                self._post(render)
            except Exception as exc:
                message = str(exc)
                self._post(
                    lambda: self._status(message, WARN) if generation == self._search_generation else None
                )

        threading.Thread(target=worker, daemon=True).start()

    def _render_mod_card(self, hit, version, loader, kind="mod", generation=None):
        card = ctk.CTkFrame(self.results_scroll, fg_color=CARD_LIGHT)
        card.pack(fill="x", padx=6, pady=4)
        icon = ctk.CTkLabel(card, text="🧩", width=52, height=52, text_color=CYAN)
        icon.pack(side="left", padx=8, pady=8)
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        ctk.CTkLabel(
            info,
            text=f"{hit.get('title', '?')} · {hit.get('author', '?')}",
            font=("Segoe UI", 12, "bold"),
            text_color=WHITE,
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            info,
            text=hit.get("description", "")[:180],
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=580,
        ).pack(fill="x")
        project = hit.get("project_id") or hit.get("slug")
        ctk.CTkButton(
            card,
            text=tr("Instalar"),
            width=85,
            fg_color=CYAN,
            hover_color=CYAN_H,
            text_color=BG,
            command=lambda: self._install_project(project, hit.get("title", "?"), loader, version, kind),
        ).pack(side="right", padx=10)
        if hit.get("icon_url"):
            self._load_icon(hit["icon_url"], icon, generation)

    def _load_icon(self, url, label, generation):
        def worker():
            if not self._icon_slots.acquire(blocking=False):
                return
            try:
                with self.client._get(url, stream=True) as response:
                    data = bytearray()
                    for chunk in response.iter_content(64 * 1024):
                        data.extend(chunk)
                        if len(data) > 2 * 1024**2:
                            return
                with Image.open(io.BytesIO(data)) as source:
                    if source.width * source.height > 16_000_000:
                        return
                    image = source.convert("RGBA")
                    image.thumbnail((48, 48))

                def apply():
                    if generation != self._search_generation or not label.winfo_exists():
                        return
                    native = ctk.CTkImage(light_image=image, dark_image=image, size=(48, 48))
                    self._images.append(native)
                    label.configure(image=native, text="")

                self._post(apply)
            except Exception:
                logger.debug("Mod icon unavailable", exc_info=True)
            finally:
                self._icon_slots.release()

        threading.Thread(target=worker, daemon=True).start()

    def _run_install(self, task):
        if self._busy or self.launcher._is_launching or self.launcher._mc_process is not None:
            self._status(tr("Espera a que termine la instalación o cierra Minecraft."), WARN)
            return
        self._busy = True
        self.progress_bar.set(0)
        self._status(tr("Preparando instalación y verificando dependencias…"), CYAN)

        def worker():
            try:
                result = task()
                self._post(lambda: self._install_finished(result))
            except Exception as exc:
                logger.exception("Modrinth installation failed")
                message = str(exc)
                self._post(lambda: self._install_failed(message))

        threading.Thread(target=worker, daemon=True).start()

    def _install_failed(self, message):
        self._busy = False
        self.progress_bar.set(0)
        self._status(tr("Error: {message}").format(message=message), WARN)

    def _install_finished(self, result):
        self._busy = False
        self.progress_bar.set(1)
        if isinstance(result, tuple):
            directory, index = result
            self.refresh_instances()
            self._activate_pack(directory, index)
            self._status(
                tr("✓ Modpack '{name}' instalado y seleccionado.").format(name=index["name"]), SUCCESS
            )
        else:
            self._status(tr("✓ Mod y dependencias requeridas instalados."), SUCCESS)
        self.launcher._update_mods_count()

    def _install_project(self, project, title, loader, version, kind):
        # Card filters are captured at search time, never reread on a worker.
        try:
            destination = Path(self.launcher._mods_folder_for(loader, version))
        except (OSError, ValueError, ModrinthError) as exc:
            self._status(str(exc), WARN)
            return

        def task():
            if kind == "mod":
                return self.client.install_mod(project, loader, version, destination, self._progress)
            import tempfile

            versions = self.client.get_project_versions(project, loader, version)
            if not versions:
                raise ModrinthError(tr("No hay modpack compatible."))
            file = self.client.primary_file(versions[0], ".mrpack")
            hashes = file.get("hashes", {})
            if not (hashes.get("sha512") or hashes.get("sha1")):
                raise ModrinthError(tr("El modpack no tiene hashes de integridad."))
            with tempfile.TemporaryDirectory() as temporary:
                pack = Path(temporary, "download.mrpack")
                self.client.download_file(
                    file["url"],
                    pack,
                    hashes.get("sha512"),
                    self._progress,
                    expected_hash_sha1=hashes.get("sha1"),
                    expected_size=file.get("size"),
                )
                return self._install_pack_file(pack)

        self._run_install(task)

    def _import_pack(self):
        if self._busy:
            return
        path = filedialog.askopenfilename(
            parent=self, title=tr("Importar modpack"), filetypes=[("Modrinth modpack", "*.mrpack")]
        )
        if path:
            self._run_install(lambda: self._install_pack_file(path))

    def _install_pack_file(self, path):
        directory = Path(BASE_PATH, "HexInstances", uuid.uuid4().hex)
        index = self.client.install_mrpack(path, directory, self._progress)
        return str(directory), index

    def refresh_instances(self):
        import json

        self._instances = {}
        root = Path(BASE_PATH, "HexInstances")
        if root.exists():
            for metadata in root.glob("*/.hexpack.json"):
                try:
                    index = json.loads(metadata.read_text(encoding="utf-8"))
                    label = f"{index['name']} · {metadata.parent.name[:8]}"
                    self._instances[label] = (str(metadata.parent), index)
                except (OSError, ValueError, KeyError):
                    logger.warning("Invalid pack metadata: %s", metadata)
        self.instance_menu.configure(values=[tr("Instalación habitual"), *self._instances])
        active = self.launcher.settings.get("active_instance_dir")
        chosen = next(
            (label for label, (path, _) in self._instances.items() if path == active),
            tr("Instalación habitual"),
        )
        self.instance_var.set(chosen)

    def _select_instance(self, label):
        if self._busy or self.launcher._is_launching or self.launcher._mc_process is not None:
            self.refresh_instances()
            self._status(tr("Cierra el juego antes de cambiar de instancia."), WARN)
            return
        if label in self._instances:
            self._activate_pack(*self._instances[label])
        else:
            self.launcher.settings.set("active_instance_dir", "")
            self.launcher.settings.save()
            self.launcher.bottom_bar.loader_menu.configure(state="normal")
            self.launcher.bottom_bar.version_combo.configure(state="normal")
            self.launcher._update_version_list()
            self.update_filter_badge()
            self.launcher._update_mods_count()
            self._status(tr("Instalación habitual seleccionada."))

    def _activate_pack(self, directory, index):
        deps = index["dependencies"]
        loader = next(
            (
                name
                for key, name in (("fabric-loader", "Fabric"), ("forge", "Forge"), ("neoforge", "NeoForge"))
                if key in deps
            ),
            "Vanilla",
        )
        self.launcher.settings.set("active_instance_dir", directory)
        self.launcher.settings.save()
        self.launcher.loader_var.set(loader)
        self.launcher.version_var.set(deps["minecraft"])
        self.launcher.bottom_bar.loader_menu.configure(state="disabled")
        self.launcher.bottom_bar.version_combo.configure(state="disabled")
        self.instance_var.set(
            next(
                (label for label, (path, _) in self._instances.items() if path == directory),
                tr("Instalación habitual"),
            )
        )
        self.update_filter_badge()
        self.launcher._update_mods_count()

    def refresh_installed_mods(self):
        self._search_generation += 1
        self._clear()
        filters = self._filters()
        if not filters:
            return
        loader, version = filters
        try:
            path = Path(self.launcher._mods_folder_for(loader, version))
            scope = (
                tr("Instancia activa")
                if self.launcher.settings.get("active_instance_dir")
                else tr("Biblioteca")
            )
            self._status(f"{scope}: {loader} · {version}")
            for file in sorted(path.glob("*.jar")):
                row = ctk.CTkFrame(self.results_scroll, fg_color=CARD_LIGHT)
                row.pack(fill="x", padx=6, pady=4)
                ctk.CTkLabel(row, text=file.name, text_color=WHITE).pack(side="left", padx=10)
                ctk.CTkButton(
                    row,
                    text=tr("Eliminar"),
                    width=80,
                    fg_color=CARD,
                    command=lambda p=file: self._delete_mod(p),
                ).pack(side="right", padx=8, pady=8)
        except (OSError, ValueError, ModrinthError) as exc:
            self._status(str(exc), WARN)

    def _delete_mod(self, path):
        if self._busy or self.launcher._is_launching or self.launcher._mc_process is not None:
            self._status(tr("Cierra el juego antes de modificar los mods."), WARN)
            return
        try:
            self.client.uninstall_mod(path.parent, path.name)
            self.refresh_installed_mods()
            self.launcher._update_mods_count()
        except (OSError, ModrinthError) as exc:
            self._status(str(exc), WARN)
