"""HexLauncher — modern, minimalist, high-performance Minecraft launcher.

Features:
- Sleek modern TLauncher-inspired bottom dock and tabbed navigation.
- Integrated Modrinth browser & mod manager.
- Adoptium OpenJDK 21 LTS automatic installation & SHA-256 verification.
- Mod loader support: Fabric, Forge, NeoForge, and Vanilla.
- Live RAM allocation & JVM performance optimization.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter
import uuid

import customtkinter as ctk
import minecraft_launcher_lib

from src.hexlauncher.bottom_bar import BottomBar
from src.hexlauncher.i18n import refresh_language, set_language, tr, translate_displayed
from src.hexlauncher.loader_folders import LOADER_FOLDERS
from src.hexlauncher.palette import (
    BG,
    CARD,
    CARD_LIGHT,
    CYAN,
    CYAN_DIM,
    MUTED_LIGHT,
    TEXT_MAIN,
)
from src.hexlauncher.paths import (
    BASE_PATH,
    ICON_NAME,
    JAVA_BIN,
    JAVA_DIR,
    LOGS_DIR,
    MC_DIR,
    MODS_DIR,
)
from src.hexlauncher.utils.settings import Settings
from src.hexlauncher.views.home_view import HomeView
from src.hexlauncher.views.modrinth_view import ModrinthView
from src.hexlauncher.views.settings_view import SettingsView
from src.hexlauncher.widgets import Badge, NavTabButton

# Tcl locates its runtime when the first Tk window is created, after imports.
tcl = os.path.normpath(os.path.join(sys.base_prefix, "tcl"))
if os.path.isdir(tcl):
    os.environ.setdefault("TCL_LIBRARY", os.path.normpath(os.path.join(tcl, "tcl8.6")))
    os.environ.setdefault("TK_LIBRARY", os.path.normpath(os.path.join(tcl, "tk8.6")))

logging.basicConfig(
    filename=os.path.join(LOGS_DIR, "launcher.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("HexLauncher")


class HexLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._is_destroyed = False
        self._queue_after_id = None
        self.queue = queue.Queue()
        self.settings = Settings(BASE_PATH)
        set_language(self.settings.get("language"))
        self._mc_process: subprocess.Popen | None = None
        self._releases: list[str] = []
        self._versions_request_id = 0
        self._filter_request_id = 0
        self._stop_requested = False
        self._max_progress = 1

        self.title("HexLauncher")

        # Geometry restoration
        _saved_geom = self.settings.get("window_geometry")
        if isinstance(_saved_geom, str) and "+" in _saved_geom:
            try:
                # Extract the +x+y position part from saved geometry
                position = _saved_geom[_saved_geom.index("+") :]
                self.geometry(f"1000x680{position}")
            except Exception:
                self.geometry("1000x680")
        else:
            self.geometry("1000x680")

        self.resizable(False, False)
        self.configure(fg_color=BG)

        if os.path.exists(ICON_NAME):
            try:
                self.iconbitmap(ICON_NAME)
            except Exception:
                logger.debug("iconbitmap failed", exc_info=True)

        self.loader_var = ctk.StringVar(value=self.settings.get("last_loader") or "Vanilla")
        self.version_var = ctk.StringVar(value=tr("Cargando…"))

        self._is_launching = False
        self._mc_process = None

        self._build_ui()
        refresh_language(self.main_container)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._queue_after_id = super().after(50, self._process_queue)
        self._initial_refresh_after_id = self.after(100, self._refresh_versions)

    def _process_queue(self, event=None):
        if getattr(self, "_is_destroyed", False):
            return
        try:
            if not self.winfo_exists():
                return
            for _ in range(100):
                callback = self.queue.get_nowait()
                try:
                    callback()
                    refresh_language(self.main_container)
                except Exception as e:
                    logger.error("Error executing queued callback: %s", e)
        except queue.Empty:
            pass
        except Exception:
            pass

        if not self._is_destroyed:
            self._queue_after_id = super().after(50, self._process_queue)

    def after(self, delay, callback, *args):
        if getattr(self, "_is_destroyed", False):
            return None
        if threading.current_thread() is threading.main_thread():
            return super().after(delay, callback, *args)
        else:
            if delay == 0:
                self.queue.put(lambda: callback(*args))
            else:
                self.queue.put(lambda: self.after(delay, callback, *args))

    # ── UI Architecture ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.main_container = tkinter.Frame(self, bg=BG)
        self.main_container.pack(fill="both", expand=True)

        # ── 1. Top Modern Header Navigation Bar ───────────────────────────────
        self.header = ctk.CTkFrame(self.main_container, fg_color=CARD, height=52, corner_radius=0)
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        # Brand / Logo
        brand_frame = tkinter.Frame(self.header, bg=CARD)
        brand_frame.pack(side="left", padx=16, pady=8)

        ctk.CTkLabel(
            brand_frame,
            text="⚡ HEXLAUNCHER",
            font=("Segoe UI", 14, "bold"),
            text_color=CYAN,
        ).pack(side="left", padx=(0, 8))

        Badge(
            brand_frame,
            text="v0.7.0-beta.1",
            fg_color=CARD_LIGHT,
            text_color=MUTED_LIGHT,
            font_size=9,
            height=20,
        ).pack(side="left")

        # Center Navigation Tabs
        nav_frame = tkinter.Frame(self.header, bg=CARD)
        nav_frame.pack(side="left", expand=True, pady=8)

        self.nav_tabs: dict[str, NavTabButton] = {}
        self.nav_tabs["home"] = NavTabButton(
            nav_frame,
            text="Inicio",
            icon="🚀",
            command=lambda: self.switch_view("home"),
            is_active=True,
        )
        self.nav_tabs["home"].pack(side="left", padx=4)

        self.nav_tabs["mods"] = NavTabButton(
            nav_frame,
            text="Modrinth & Mods",
            icon="🧩",
            command=lambda: self.switch_view("mods"),
            is_active=False,
        )
        self.nav_tabs["mods"].pack(side="left", padx=4)

        self.nav_tabs["settings"] = NavTabButton(
            nav_frame,
            text="Ajustes",
            icon="⚙️",
            command=lambda: self.switch_view("settings"),
            is_active=False,
        )
        self.nav_tabs["settings"].pack(side="left", padx=4)

        # Header Right Quick Utility Icons
        right_header = tkinter.Frame(self.header, bg=CARD)
        right_header.pack(side="right", padx=16, pady=8)

        ctk.CTkButton(
            right_header,
            text="📂 .minecraft",
            command=lambda: self._open_dir(self._game_directory()),
            width=100,
            height=30,
            corner_radius=8,
            fg_color=CARD_LIGHT,
            hover_color=CYAN_DIM,
            text_color=TEXT_MAIN,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=(0, 6))

        # ── 2. Bottom TLauncher-Style Action Bar ───────────────────────────────
        self.bottom_bar = BottomBar(self.main_container, launcher=self)
        self.bottom_bar.pack(side="bottom", fill="x")

        # ── 3. Main Center Views Container ────────────────────────────────────
        self.views_container = tkinter.Frame(self.main_container, bg=BG)
        self.views_container.pack(fill="both", expand=True, side="top")

        # Initialize Views
        self.home_view = HomeView(self.views_container, launcher=self)
        self.modrinth_view = ModrinthView(self.views_container, launcher=self)
        self.settings_view = SettingsView(self.views_container, launcher=self)

        self.views: dict[str, ctk.CTkFrame] = {
            "home": self.home_view,
            "mods": self.modrinth_view,
            "settings": self.settings_view,
        }
        self.current_view = "home"
        self.home_view.pack(fill="both", expand=True)

    def switch_view(self, view_name: str):
        if view_name == self.current_view:
            return

        for name, btn in self.nav_tabs.items():
            btn.set_active(name == view_name)

        for v in self.views.values():
            v.pack_forget()

        self.views[view_name].pack(fill="both", expand=True)
        self.current_view = view_name

        if view_name == "home":
            self.home_view.refresh_stats()
        elif view_name == "mods":
            self.modrinth_view.update_filter_badge()
        refresh_language(self.main_container)

    def change_language(self, language: str) -> bool:
        previous = self.settings.get("language")
        self.settings.set("language", language)
        if not self.settings.save():
            self.settings.set("language", previous)
            return False
        set_language(language)
        self.settings_view.language_var.set(language)
        self.modrinth_view.refresh_instances()
        self.version_var.set(translate_displayed(self.version_var.get()))
        refresh_language(self.main_container)
        return True

    def _open_dir(self, path: str):
        os.makedirs(path, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass

    # ── Versions & Loaders ────────────────────────────────────────────────────

    def _refresh_versions(self):
        """Capture refresh order on Tk's thread, then perform network work off-thread."""
        self._versions_request_id += 1
        request_id = self._versions_request_id
        threading.Thread(target=self._fetch_versions, args=(request_id,), daemon=True).start()

    def _fetch_versions(self, request_id=None):
        request_id = self._versions_request_id if request_id is None else request_id
        try:
            all_versions = minecraft_launcher_lib.utils.get_version_list()
            releases = [version["id"] for version in all_versions if version["type"] == "release"]

            def apply():
                if request_id != self._versions_request_id:
                    return
                self._releases = releases
                self._update_version_list()

            self.after(0, apply)
        except Exception as exc:
            message = str(exc)
            self.after(
                0,
                lambda: (
                    self.bottom_bar.status_label.configure(text=f"Error obteniendo versiones: {message}")
                    if request_id == self._versions_request_id
                    else None
                ),
            )

    def _update_version_list(self):
        """Ignore results from an earlier loader/filter/instance selection."""
        self._filter_request_id += 1
        request_id = self._filter_request_id
        loader_name = self.loader_var.get().lower()
        instance = self.settings.get("active_instance_dir") or ""
        releases = list(self._releases)
        self.bottom_bar.status_label.configure(
            text=tr("Filtrando versiones para {loader}…").format(loader=loader_name.capitalize())
        )

        def task():
            try:
                versions = releases
                if loader_name != "vanilla":
                    from minecraft_launcher_lib import mod_loader

                    supported = mod_loader.get_mod_loader(loader_name).get_minecraft_versions(True)
                    versions = [version for version in versions if version in supported]

                def apply():
                    if (
                        request_id != self._filter_request_id
                        or self.loader_var.get().lower() != loader_name
                        or (self.settings.get("active_instance_dir") or "") != instance
                    ):
                        return
                    self._populate_menu(versions)
                    message = (
                        "Listo para jugar" if versions else f"No hay versiones compatibles con {loader_name}."
                    )
                    if not self._is_launching and self._mc_process is None:
                        self.bottom_bar.status_label.configure(text=message)

                self.after(0, apply)
            except Exception as exc:
                message = str(exc)
                self.after(
                    0,
                    lambda: (
                        self.bottom_bar.status_label.configure(text=f"Error en filtro: {message}")
                        if request_id == self._filter_request_id
                        else None
                    ),
                )

        threading.Thread(target=task, daemon=True).start()

    def _populate_menu(self, versions: list[str]):
        self.bottom_bar.version_combo.configure(values=versions or [tr("No se encontraron versiones")])
        if not versions:
            self.version_var.set(tr("No se encontraron versiones"))
        if versions:
            saved = self.settings.get("last_version") or ""
            chosen = saved if saved in versions else versions[0]
            self.bottom_bar.version_combo.set(chosen)
            self._check_installed(chosen)

        active = self.settings.get("active_instance_dir")
        if active:
            try:
                with open(os.path.join(active, ".hexpack.json"), encoding="utf-8") as source:
                    self.modrinth_view._activate_pack(active, json.load(source))
            except (OSError, ValueError, KeyError):
                logger.warning("Active pack metadata could not be restored", exc_info=True)

        if hasattr(self, "home_view"):
            self.home_view.refresh_stats()
        if hasattr(self, "modrinth_view"):
            self.modrinth_view.update_filter_badge()

    def _get_installed(self) -> list[str]:
        vdir = os.path.join(self._game_directory(), "versions")
        if not os.path.isdir(vdir):
            return []
        found = []
        for name in os.listdir(vdir):
            if os.path.exists(os.path.join(vdir, name, f"{name}.jar")) and os.path.exists(
                os.path.join(vdir, name, f"{name}.json")
            ):
                found.append(name)
        return found

    def _check_installed(self, version_id: str):
        is_installed = version_id in self._get_installed()
        self.bottom_bar.update_installed_status(is_installed, version_id)

    def _sync_mods(self, loader_type: str, mc_version: str):
        """Publish a staged mod set; any failure aborts launch with the old set intact."""
        from src.hexlauncher.core.filesystem import sync_mods
        from src.hexlauncher.core.modrinth import safe_path

        folder = LOADER_FOLDERS.get(loader_type.lower(), loader_type.capitalize())
        source_dir = safe_path(MODS_DIR, f"{folder}/{mc_version}")
        copied = sync_mods(source_dir, os.path.join(MC_DIR, "mods"))
        return copied, 0

    def _game_directory(self):
        """Canonical game directory for the selected instance."""
        from pathlib import Path

        active = self.settings.get("active_instance_dir") or ""
        if not active:
            return MC_DIR
        root = Path(BASE_PATH, "HexInstances").resolve()
        directory = Path(active).resolve()
        if (
            directory == root
            or not directory.is_relative_to(root)
            or not (directory / ".hexpack.json").is_file()
        ):
            raise ValueError("Instancia seleccionada inválida o ausente. Selecciona otra instancia.")
        return str(directory)

    def _mods_folder_for(self, loader: str, version: str) -> str:
        from pathlib import Path

        from src.hexlauncher.core.modrinth import safe_path

        if self.settings.get("active_instance_dir"):
            path = Path(self._game_directory(), "mods")
            path.mkdir(parents=True, exist_ok=True)
            return str(path)
        if loader == "Vanilla" or version in (
            "Cargando…", "Loading…", "No se encontraron versiones", "No versions found", ""
        ):
            return MODS_DIR
        folder = LOADER_FOLDERS.get(loader.lower(), loader)
        path = safe_path(MODS_DIR, f"{folder}/{version}")
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _update_mods_count(self):
        if hasattr(self, "home_view"):
            self.home_view.refresh_stats()

    def _open_mods_folder(self):
        loader = self.loader_var.get()
        version = self.version_var.get()
        path = self._mods_folder_for(loader, version)
        self._open_dir(path)

    # ── JDK Management ────────────────────────────────────────────────────────

    def _download_jdk(self, custom_java=None):
        from src.hexlauncher.core.jdk import install_jdk

        if custom_java is None:
            custom_java = self.settings.get("custom_java_path") or ""
        custom_java = custom_java.strip()
        if custom_java:
            if not os.path.isfile(custom_java):
                raise RuntimeError("El ejecutable Java personalizado no existe.")
            return

        def progress(done, total):
            self.after(0, lambda value=done / total if total else 0: self.bottom_bar.progress_bar.set(value))

        def status(message):
            self.after(0, lambda: self.bottom_bar.status_label.configure(text=message))

        install_jdk(JAVA_DIR, progress, status)
        self.after(0, lambda: self.bottom_bar.progress_bar.set(0))

    def _start_launch_thread(self):
        if self._is_launching or self._mc_process is not None or self.modrinth_view._busy:
            self.bottom_bar.status_label.configure(text=tr("Espera a que termine la operación actual."))
            return
        if not self.bottom_bar._validate_username():
            self.bottom_bar.status_label.configure(
                text=tr("⚠ Ingresa un apodo válido (3-16 caracteres alfanuméricos).")
            )
            return

        user = self.bottom_bar.username_input.get().strip()
        version = self.version_var.get()
        if version in ("Cargando…", "Loading…", "No se encontraron versiones", "No versions found", ""):
            self.bottom_bar.status_label.configure(text=tr("⚠ Selecciona una versión válida."))
            return

        loader = self.loader_var.get().lower()
        instance = self.settings.get("active_instance_dir") or ""
        runtime_options = {
            "custom_java_path": (self.settings.get("custom_java_path") or "").strip(),
            "jvm_args": self.settings.get_effective_jvm_args(),
            "close_on_launch": self.settings.get("close_on_launch"),
        }
        self.bottom_bar.set_play_enabled(False)
        self._is_launching = True
        self._stop_requested = False
        threading.Thread(
            target=self._launch_game, args=(user, version, loader, instance, runtime_options), daemon=True
        ).start()

    def _launch_game(
        self, username: str, version: str, selected_loader: str, instance: str = "", runtime_options=None
    ):
        error_message = None
        try:
            game_dir = MC_DIR
            pack = None
            if instance:
                from pathlib import Path

                root = Path(BASE_PATH, "HexInstances").resolve()
                directory = Path(instance).resolve()
                if not directory.is_relative_to(root) or directory == root:
                    raise ValueError("Ruta de instancia inválida.")
                pack = json.loads((directory / ".hexpack.json").read_text(encoding="utf-8"))
                deps = pack["dependencies"]
                version = deps["minecraft"]
                selected_loader = next(
                    (
                        loader
                        for key, loader in (
                            ("fabric-loader", "fabric"),
                            ("forge", "forge"),
                            ("neoforge", "neoforge"),
                        )
                        if key in deps
                    ),
                    "vanilla",
                )
                game_dir = str(directory)
            if runtime_options is None:
                self._download_jdk()
            else:
                self._download_jdk(runtime_options["custom_java_path"])
            os.makedirs(game_dir, exist_ok=True)

            def set_status(t):
                self.after(0, lambda _t=t: self.bottom_bar.status_label.configure(text=_t))

            def set_progress(v):
                self.after(
                    0,
                    lambda _v=v: self.bottom_bar.progress_bar.set(_v / max(self._max_progress, 1)),
                )

            def set_max(v):
                self._max_progress = v or 1

            self._max_progress = 1
            set_status(f"Instalando archivos de Minecraft {version}…")
            minecraft_launcher_lib.install.install_minecraft_version(
                version,
                game_dir,
                callback={"setStatus": set_status, "setProgress": set_progress, "setMax": set_max},
            )

            launch_version = version

            # Resolve effective Java binary
            custom_java = (
                runtime_options["custom_java_path"]
                if runtime_options is not None
                else (self.settings.get("custom_java_path") or "").strip()
            )
            effective_java = custom_java if (custom_java and os.path.exists(custom_java)) else JAVA_BIN

            if selected_loader != "vanilla":
                from minecraft_launcher_lib import mod_loader

                try:
                    ml = mod_loader.get_mod_loader(selected_loader)
                except Exception as e:
                    raise RuntimeError(f"Error cargando loader: {e}") from e

                if not ml.is_minecraft_version_supported(version):
                    raise RuntimeError(f"{selected_loader.capitalize()} no soporta MC {version}.")

                try:
                    set_status(f"Instalando {selected_loader.capitalize()} para MC {version}…")
                    if pack:
                        key = {"fabric": "fabric-loader", "forge": "forge", "neoforge": "neoforge"}[
                            selected_loader
                        ]
                        loader_ver = pack["dependencies"][key]
                    else:
                        loader_ver = ml.get_latest_loader_version(version)
                    launch_version = ml.install(
                        version,
                        game_dir,
                        loader_version=loader_ver,
                        callback={"setStatus": set_status, "setProgress": set_progress, "setMax": set_max},
                        java=effective_java,
                    )

                    set_status(f"Sincronizando mods para {version}…")
                    copied, failed = (0, 0) if pack else self._sync_mods(selected_loader, version)
                    if failed > 0:
                        raise RuntimeError(
                            f"{failed} mod(s) no pudieron sincronizarse. El juego no se inició."
                        )
                except Exception as e:
                    raise RuntimeError(f"Error en instalación de modloader: {e}") from e

            self.after(0, lambda: self.bottom_bar.progress_bar.set(1))
            set_status(f"Iniciando {launch_version}…")

            jvm_args = (
                runtime_options["jvm_args"]
                if runtime_options is not None
                else self.settings.get_effective_jvm_args()
            )

            cmd = minecraft_launcher_lib.command.get_minecraft_command(
                launch_version,
                game_dir,
                {
                    "username": username,
                    "uuid": str(
                        uuid.UUID(bytes=hashlib.md5(f"OfflinePlayer:{username}".encode()).digest(), version=3)
                    ),
                    "token": "0",
                    "executablePath": effective_java,
                    "jvmArguments": jvm_args,
                },
            )

            self._mc_process = subprocess.Popen(
                cmd,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )

            close_on_launch = bool(
                runtime_options["close_on_launch"]
                if runtime_options is not None
                else self.settings.get("close_on_launch")
            )
            if close_on_launch:
                self.after(0, self.withdraw)

            # Switch button to STOP state
            self.after(0, lambda: self.bottom_bar.set_running_state(True))
            set_status(f"Minecraft {version} en ejecución.")

            try:
                exit_code = self._mc_process.wait()
                if exit_code and not getattr(self, "_stop_requested", False):
                    raise RuntimeError(f"Minecraft terminó con código {exit_code}. Revisa el log del juego.")
            finally:
                self._mc_process = None
                if close_on_launch:
                    self.after(0, self.deiconify)
                self.after(0, lambda: self.bottom_bar.set_running_state(False))

        except Exception as err:
            error_message = str(err)
            logger.error("Error launching game: %s", err, exc_info=True)
            self.after(
                0,
                lambda e=str(err): self.bottom_bar.status_label.configure(text=f"Error: {e}"),
            )
        finally:
            self._is_launching = False
            self.after(0, lambda: self.bottom_bar.progress_bar.set(0))
            self.after(
                0,
                lambda message=error_message: self.bottom_bar.status_label.configure(
                    text=f"Error: {message}" if message else "Listo para jugar"
                ),
            )
            self.after(0, lambda: self.bottom_bar.set_play_enabled(True))
            self.after(0, lambda v=version: self._check_installed(v))

    def _kill_game(self):
        process = self._mc_process
        if process is None or process.poll() is not None:
            return
        self._stop_requested = True
        self.bottom_bar.status_label.configure(text=tr("Deteniendo Minecraft…"))

        def stop():
            try:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.error("Failed to stop Minecraft: %s", exc)
                self.after(
                    0,
                    lambda message=str(exc): self.bottom_bar.status_label.configure(
                        text=f"No se pudo detener Minecraft: {message}"
                    ),
                )

        threading.Thread(target=stop, daemon=True).start()

    def _on_close(self):
        try:
            self.settings.set("username", self.bottom_bar.username_input.get().strip())
            self.settings.set("last_version", self.version_var.get())
            self.settings.set("last_loader", self.loader_var.get())
            self.settings.set("window_geometry", self.geometry())
            self.settings.save()
        except Exception:
            logger.debug("Failed to persist settings on close", exc_info=True)
        self.destroy()

    def destroy(self):
        self._is_destroyed = True
        if hasattr(self, "_queue_after_id") and self._queue_after_id:
            try:
                self.after_cancel(self._queue_after_id)
            except Exception:
                pass
            self._queue_after_id = None
        super().destroy()


def run():
    """Shared source/frozen entry point, with a hidden offline startup check."""
    ctk.set_appearance_mode("dark")
    app = HexLauncher()
    if "--smoke-test" in sys.argv:
        app.after_cancel(app._initial_refresh_after_id)
        app.withdraw()
        if not os.path.isfile(ICON_NAME):
            app.destroy()
            raise RuntimeError("El paquete no incluye el icono Hex.ico.")
        app.after(100, app.destroy)
        # CTk's Windows titlebar setup pumps events before entering its loop.
        # A hidden short-lived smoke window must not destroy itself during that setup.
        tkinter.Tk.mainloop(app)
        return
    app.mainloop()


def _relaunch_without_console():
    """Exit the console parent and run the same script as a windowed process."""
    if (
        sys.platform != "win32"
        or getattr(sys, "frozen", False)
        or "--smoke-test" in sys.argv
        or "--hex-windowed" in sys.argv
        or os.path.basename(sys.executable).lower() == "pythonw.exe"
    ):
        return False
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    executable = pythonw if os.path.isfile(pythonw) else sys.executable
    subprocess.Popen(
        [executable, os.path.abspath(__file__), "--hex-windowed", *sys.argv[1:]],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return True


if __name__ == "__main__":
    if _relaunch_without_console():
        raise SystemExit(0)
    run()
