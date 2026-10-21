"""Dedicated Modrinth resource-pack search and installation, independent of mod loaders."""

from __future__ import annotations

import io
import logging
import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from src.hexlauncher.core.modrinth import ModrinthClient
from src.hexlauncher.core.resource_packs import import_resource_pack, install_resource_pack
from src.hexlauncher.i18n import tr, translate_displayed
from src.hexlauncher.palette import BG, CARD, CARD_LIGHT, CYAN, CYAN_H, MUTED, SUCCESS, WARN, WHITE
from src.hexlauncher.utils.ui_tasks import render_in_batches, replace_results_content
from src.hexlauncher.widgets import ResponsiveScrollableFrame

logger = logging.getLogger(__name__)


class ResourcePacksView(ctk.CTkFrame):
    def __init__(self, parent, launcher, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.launcher = launcher
        self.client = ModrinthClient()
        self._busy = False
        self._search_generation = 0
        self._context = None
        self._images = []
        self._icon_slots = threading.BoundedSemaphore(4)
        self._last_progress = 0
        self._mode = "empty"
        self._build_view()
        self.refresh_context()

    def _build_view(self):
        ctk.CTkLabel(
            self, text=tr("Packs de texturas"), anchor="w",
            font=("Segoe UI", 20, "bold"), text_color=WHITE,
        ).pack(fill="x", padx=20, pady=(12, 0))
        self.context_label = ctk.CTkLabel(self, text="", anchor="w", text_color=MUTED)
        self.context_label.pack(fill="x", padx=20, pady=(0, 6))
        destination = ctk.CTkFrame(self, fg_color=CARD)
        destination.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(destination, text=tr("Instalación de destino"), text_color=MUTED).pack(
            side="left", padx=12, pady=8,
        )
        self.instance_menu = ctk.CTkOptionMenu(
            destination, variable=self.launcher.modrinth_view.instance_var,
            values=[tr("Instalación habitual")], fg_color=CARD_LIGHT,
            command=self._select_instance,
        )
        self.instance_menu.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        search = ctk.CTkFrame(self, fg_color=CARD)
        search.pack(fill="x", padx=16, pady=(0, 8))
        self.search_var = ctk.StringVar()
        self.search_input = ctk.CTkEntry(
            search, textvariable=self.search_var,
            placeholder_text=tr("Buscar packs de texturas en Modrinth…"), height=34,
        )
        self.search_input.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self.search_input.bind("<Return>", lambda _: self.do_search())
        ctk.CTkButton(
            search, text=tr("Buscar"), command=self.do_search, width=90,
            fg_color=CYAN, hover_color=CYAN_H, text_color=BG,
        ).pack(side="right", padx=8)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 4))
        self.import_button = ctk.CTkButton(
            actions, text=tr("Añadir ZIP local…"), command=self.import_local,
            fg_color=CARD_LIGHT, width=170,
        )
        self.import_button.pack(side="left", padx=4)
        ctk.CTkButton(
            actions, text=tr("Mis texturas"), command=self.show_installed,
            fg_color=CARD_LIGHT, width=150,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            actions, text=tr("Abrir carpeta de texturas"), command=self.open_folder,
            fg_color=CARD_LIGHT, width=190,
        ).pack(side="left", padx=4)
        self.status_label = ctk.CTkLabel(
            self, text=tr("Busca un pack por nombre o pulsa Buscar para explorar."),
            anchor="w", justify="left", wraplength=920, text_color=MUTED,
        )
        self.status_label.pack(fill="x", padx=20, pady=4)
        self.progress_bar = ctk.CTkProgressBar(self, progress_color=CYAN, height=5)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=20, pady=(0, 6))
        self._results_viewport = ResponsiveScrollableFrame(self, fg_color=CARD)
        self._results_viewport.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        self.results_scroll = replace_results_content(self.launcher, self._results_viewport)
        ctk.CTkLabel(
            self, text=tr("Actívalas en Minecraft: Opciones > Paquetes de recursos."),
            text_color=MUTED, anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 6))

    def _post(self, callback):
        self.launcher.after(0, lambda: callback() if self.winfo_exists() else None)

    def _status(self, message, color=MUTED):
        self.status_label.configure(text=translate_displayed(message), text_color=color)

    def _select_instance(self, label):
        self.launcher.modrinth_view._select_instance(label)
        self.refresh_context()

    def _clear(self):
        self._images.clear()
        self.results_scroll = replace_results_content(
            self.launcher, self._results_viewport, self.results_scroll,
        )

    def refresh_context(self):
        app = self.launcher
        self.instance_menu.configure(values=[tr("Instalación habitual"), *app.modrinth_view._instances])
        version = app.version_var.get()
        self.context_label.configure(
            text=tr("Minecraft {version} · Usa la versión seleccionada abajo.").format(version=version)
        )
        try:
            context = (version, str(Path(app._game_directory()).resolve()))
        except (OSError, ValueError) as exc:
            context = None
            self._status(translate_displayed(str(exc)), WARN)
        if context != self._context:
            self._context = context
            self._search_generation += 1
            self._clear()
            if self._mode == "installed":
                self.show_installed()
            elif not self._busy:
                self._status(tr("Busca un pack por nombre o pulsa Buscar para explorar."))

    def _selection(self):
        self.refresh_context()
        version = self.launcher.version_var.get()
        if not version or version in {
            "Cargando…", "Loading…", "No se encontraron versiones", "No versions found",
        }:
            self._status(tr("Selecciona una versión de Minecraft."), WARN)
            return None
        if self._context is None:
            return None
        return version, Path(self._context[1])

    def do_search(self):
        selection = self._selection()
        if selection is None:
            return
        version, _ = selection
        self._mode = "search"
        self._search_generation += 1
        generation = self._search_generation
        query = self.search_var.get().strip()
        self._clear()
        self._status(tr("Buscando texturas para Minecraft {version}…").format(version=version))

        def worker():
            try:
                hits = self.client.search_mods(query, "", version, project_type="resourcepack")

                def render():
                    if generation != self._search_generation:
                        return
                    self._status(tr("{count} pack(s) para Minecraft {version}").format(
                        count=len(hits), version=version,
                    ))
                    if not hits:
                        ctk.CTkLabel(
                            self.results_scroll, text=tr("No hay resultados. Prueba otro nombre o versión."),
                            text_color=MUTED,
                        ).pack(pady=24)
                    render_in_batches(
                        self.launcher, hits,
                        lambda hit: self._render_card(hit, version, generation),
                        lambda: self.winfo_exists() and generation == self._search_generation,
                    )

                self._post(render)
            except Exception as exc:
                self._post(lambda message=str(exc): self._status(translate_displayed(message), WARN)
                           if generation == self._search_generation else None)

        threading.Thread(target=worker, daemon=True).start()

    def _render_card(self, hit, version, generation):
        card = ctk.CTkFrame(self.results_scroll, fg_color=CARD_LIGHT)
        card.pack(fill="x", padx=6, pady=4)
        icon = ctk.CTkLabel(card, text="▧", width=52, height=52, text_color=CYAN)
        icon.pack(side="left", padx=8, pady=8)
        ctk.CTkButton(
            card, text=tr("Instalar"), width=90, fg_color=CYAN, hover_color=CYAN_H, text_color=BG,
            command=lambda: self.install_project(hit.get("project_id") or hit.get("slug"), version),
        ).pack(side="right", padx=10)
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        ctk.CTkLabel(
            info, text=f"{hit.get('title', '?')} · {hit.get('author', '?')}",
            font=("Segoe UI", 12, "bold"), text_color=WHITE, anchor="w", wraplength=590,
        ).pack(fill="x")
        ctk.CTkLabel(
            info, text=hit.get("description", "")[:180], text_color=MUTED,
            anchor="w", justify="left", wraplength=590,
        ).pack(fill="x")
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
                    picture = source.convert("RGBA")
                    picture.thumbnail((48, 48))

                def apply():
                    if generation != self._search_generation or not label.winfo_exists():
                        return
                    native = ctk.CTkImage(light_image=picture, dark_image=picture, size=(48, 48))
                    self._images.append(native)
                    label.configure(image=native, text="")

                self._post(apply)
            except Exception:
                logger.debug("Resource-pack icon unavailable", exc_info=True)
            finally:
                self._icon_slots.release()

        threading.Thread(target=worker, daemon=True).start()

    def _available(self):
        app = self.launcher
        if app._is_launching or app._mc_process is not None or app.modrinth_view._busy or app._updating:
            self._status(tr("Espera a que termine la instalación o cierra Minecraft."), WARN)
            return False
        return True

    def _progress(self, done, total):
        now = time.monotonic()
        if (total and done >= total) or now - self._last_progress >= 0.1:
            self._last_progress = now
            self._post(lambda value=min(done / total, 1) if total else 0: self.progress_bar.set(value))

    def _run_install(self, task):
        if not self._available():
            return
        # Share the existing installation gate: launch, close, updates and instance
        # switching already wait for it, including local ZIP imports.
        self._busy = self.launcher.modrinth_view._busy = True
        self.import_button.configure(state="disabled")
        self.instance_menu.configure(state="disabled")
        self.progress_bar.set(0)
        self._status(tr("Descargando y verificando pack de texturas…"), CYAN)

        def worker():
            try:
                installed = task()
                self._post(lambda: self._finished(installed, None))
            except Exception as exc:
                logger.warning("Resource-pack installation failed: %s", exc)
                self._post(lambda message=str(exc): self._finished(None, message))

        threading.Thread(target=worker, daemon=True).start()

    def _finished(self, installed, error):
        self._busy = self.launcher.modrinth_view._busy = False
        self.import_button.configure(state="normal")
        self.instance_menu.configure(state="normal")
        self.progress_bar.set(0 if error else 1)
        if error:
            self._status(tr("Error: {message}").format(message=translate_displayed(error)), WARN)
        else:
            self.show_installed()
            self._status(tr("Texturas añadidas: {name}. Actívalas en Opciones > Paquetes de recursos.").format(
                name=installed.name,
            ), SUCCESS)
        self.launcher.bottom_bar.status_label.configure(text=self.status_label.cget("text"))

    def install_project(self, project_id, version):
        if not self._available():
            return
        selection = self._selection()
        if selection is None:
            return
        if selection[0] != version:
            self._status(tr("La versión cambió. Busca de nuevo antes de instalar."), WARN)
            return
        directory = selection[1]
        self._run_install(lambda: install_resource_pack(
            self.client, project_id, version, directory, self._progress,
        ))

    def import_local(self):
        if not self._available():
            return
        filename = filedialog.askopenfilename(
            parent=self, title=tr("Añadir pack de texturas"), filetypes=[("Minecraft resource pack", "*.zip")],
        )
        if filename:
            try:
                directory = Path(self.launcher._game_directory())
            except (OSError, ValueError) as exc:
                self._status(translate_displayed(str(exc)), WARN)
                return
            self._run_install(lambda: import_resource_pack(Path(filename), directory))

    def show_installed(self):
        self._mode = "installed"
        self._search_generation += 1
        self._clear()
        try:
            directory = Path(self.launcher._game_directory()) / "resourcepacks"
            packs = sorted(path for path in directory.glob("*.zip") if path.is_file())
            self._status(tr("{count} pack(s) en esta instalación.").format(count=len(packs)))
            if not packs:
                ctk.CTkLabel(
                    self.results_scroll, text=tr("Aún no hay texturas. Busca un pack o añade un ZIP local."),
                    text_color=MUTED,
                ).pack(pady=24)
            for pack in packs:
                ctk.CTkLabel(
                    self.results_scroll, text=pack.name, anchor="w", justify="left",
                    wraplength=850, text_color=WHITE,
                ).pack(fill="x", padx=16, pady=8)
        except (OSError, ValueError) as exc:
            self._status(translate_displayed(str(exc)), WARN)

    def open_folder(self):
        try:
            self.launcher._open_dir(str(Path(self.launcher._game_directory()) / "resourcepacks"))
        except (OSError, ValueError) as exc:
            self._status(translate_displayed(str(exc)), WARN)
