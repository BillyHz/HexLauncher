"""Local server controls. Network and process work never runs on Tk's thread."""

from __future__ import annotations

import logging
import threading
import webbrowser
from collections import deque
from pathlib import Path

import customtkinter as ctk
import psutil

from src.hexlauncher.core.server_manager import MinecraftServerManager
from src.hexlauncher.i18n import tr, translate_displayed
from src.hexlauncher.palette import BG, CARD, CARD_LIGHT, CYAN, CYAN_H, DANGER, DANGER_H, MUTED_LIGHT, WHITE
from src.hexlauncher.paths import JAVA_DIR, SERVER_DIR

logger = logging.getLogger(__name__)
GIB = 1024**3


def safe_ram_limit() -> int:
    """Leave at least 2 GiB available for Windows and the client."""
    memory = psutil.virtual_memory()
    return max(0, min(8, int(min(memory.available - 2 * GIB, memory.total / 2) / GIB)))


class ServerView(ctk.CTkFrame):
    def __init__(self, parent, launcher, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.launcher = launcher
        self.manager = MinecraftServerManager(base_dir=SERVER_DIR, java_dir=JAVA_DIR)
        self._operation_thread = None
        self._starting = False
        self._stopping = False
        self._closing = False
        self._cancel = threading.Event()
        self._logs = deque(maxlen=2000)
        self._log_lock = threading.Lock()
        self._public_address = ""
        self._claim_url = ""
        self._build_view()
        self._log_timer = self.launcher.after(150, self._flush_logs)

    @property
    def active(self):
        return self._starting or self._stopping or self.manager.is_running

    def _build_view(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=8)
        card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            card, text=tr("SERVIDOR LOCAL CON PLAYIT.GG"), text_color=CYAN, font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            card, text=tr("Juega con amigos sin abrir puertos en el router."), text_color=MUTED_LIGHT
        ).pack(anchor="w", padx=16, pady=(0, 12))
        options = ctk.CTkFrame(card, fg_color="transparent")
        options.pack(fill="x", padx=16, pady=4)
        options.grid_columnconfigure((0, 1, 2), weight=1)
        for column, label in enumerate(("Tipo de servidor", "Versión de Minecraft", "RAM del servidor")):
            ctk.CTkLabel(options, text=tr(label), text_color=MUTED_LIGHT).grid(
                row=0, column=column, sticky="w", padx=(0, 12)
            )
        self.loader_var = ctk.StringVar(
            value={"neoforge": "NeoForge"}.get(
                self.launcher.settings.get("server_loader"),
                (self.launcher.settings.get("server_loader") or "paper").capitalize(),
            )
        )
        self.loader_menu = ctk.CTkOptionMenu(
            options,
            variable=self.loader_var,
            values=["Paper", "Fabric", "Vanilla", "Forge", "NeoForge"],
            fg_color=CARD_LIGHT,
            command=lambda _: self._update_loader_hint(),
        )
        self.loader_menu.grid(row=1, column=0, sticky="ew", padx=(0, 12))
        saved_version = self.launcher.settings.get("server_version") or self.launcher.settings.get(
            "last_version"
        )
        self.version_var = ctk.StringVar(value=saved_version or "1.21.1")
        self.version_menu = ctk.CTkComboBox(
            options,
            variable=self.version_var,
            values=list(self.launcher._releases) or [self.version_var.get()],
            fg_color=BG,
            button_color=CYAN_H,
        )
        self.version_menu.grid(row=1, column=1, sticky="ew", padx=(0, 12))
        limit = safe_ram_limit()
        initial_ram = min(self.launcher.settings.get("server_ram_gb") or 4, max(2, limit))
        self.ram_var = ctk.StringVar(value=f"{initial_ram} GB")
        self.ram_menu = ctk.CTkOptionMenu(
            options,
            variable=self.ram_var,
            values=[f"{ram} GB" for ram in range(2, max(2, limit) + 1)],
            fg_color=CARD_LIGHT,
        )
        self.ram_menu.grid(row=1, column=2, sticky="ew")
        ctk.CTkLabel(
            card, text=tr("Paper recomendado · Java interno · Archivos en HexServer"), text_color=MUTED_LIGHT
        ).pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            card,
            text=tr("Al iniciar aceptas la EULA de Minecraft. Modo sin autenticación habilitado."),
            text_color=MUTED_LIGHT,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))
        self.start_button = ctk.CTkButton(
            card,
            text=tr("Iniciar Servidor Local"),
            command=self.toggle_server,
            fg_color=CYAN,
            hover_color=CYAN_H,
            text_color=BG,
            height=38,
        )
        self.start_button.pack(fill="x", padx=16, pady=(0, 14))
        self.loader_hint = ctk.CTkLabel(
            card,
            text=tr("Mods de servidor: HexServer/mods. Usa el mismo loader y versiones en los clientes."),
            text_color=MUTED_LIGHT,
            wraplength=900,
            justify="left",
        )
        self.loader_hint.pack(anchor="w", padx=16, pady=(0, 8))
        self._update_loader_hint()
        ctk.CTkButton(
            card,
            text=tr("Carpeta del servidor"),
            fg_color=CARD_LIGHT,
            command=lambda: self.launcher._open_dir(str(Path(SERVER_DIR))),
        ).pack(anchor="w", padx=16, pady=(0, 12))
        self.status_label = ctk.CTkLabel(
            scroll,
            text=tr("Servidor detenido."),
            anchor="w",
            wraplength=900,
            justify="left",
            text_color=MUTED_LIGHT,
        )
        self.status_label.pack(fill="x", pady=(0, 8))
        public_card = ctk.CTkFrame(scroll, fg_color=CARD, border_color=CYAN, border_width=1)
        public_card.pack(fill="x", pady=(0, 12))
        self.address_label = ctk.CTkLabel(
            public_card,
            text=tr("Tu IP pública para amigos: pendiente"),
            text_color=CYAN,
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        )
        self.address_label.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            public_card, text=tr("En este PC puedes conectarte a localhost:25565."), text_color=MUTED_LIGHT
        ).pack(anchor="w", padx=16, pady=(0, 8))
        actions = ctk.CTkFrame(public_card, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 12))
        self.copy_button = ctk.CTkButton(
            actions,
            text=tr("Copiar IP"),
            command=self.copy_address,
            fg_color=CYAN,
            text_color=BG,
            state="disabled",
            width=110,
        )
        self.copy_button.pack(side="left", padx=(0, 8))
        self.claim_button = ctk.CTkButton(
            actions,
            text=tr("Vincular Túnel Playit.gg"),
            command=self.open_claim,
            fg_color=CARD_LIGHT,
            state="disabled",
            width=190,
        )
        self.claim_button.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions, text=tr("Configurar túnel"), fg_color=CARD_LIGHT, command=self.open_dashboard, width=150
        ).pack(side="left")
        ctk.CTkLabel(
            public_card,
            text=tr("Vincula el agente y crea un túnel Minecraft Java hacia 127.0.0.1:25565."),
            text_color=MUTED_LIGHT,
            wraplength=900,
        ).pack(anchor="w", padx=16, pady=(0, 12))
        self.console_button = ctk.CTkButton(
            scroll, text=tr("Mostrar consola"), fg_color=CARD_LIGHT, command=self.toggle_console
        )
        self.console_button.pack(fill="x", pady=(0, 6))
        self.console = ctk.CTkTextbox(
            scroll, height=160, fg_color=BG, text_color=WHITE, font=("Consolas", 10), state="disabled"
        )
        self._console_visible = False

    def update_versions(self, versions):
        self.version_menu.configure(values=versions or [self.version_var.get()])

    def _update_loader_hint(self):
        loader = self.loader_var.get().lower()
        text = {
            "paper": "Paper usa plugins en HexServer/plugins.",
            "vanilla": "Vanilla no necesita un loader en los clientes.",
        }.get(loader, "Mods de servidor: HexServer/mods. Usa el mismo loader y versiones en los clientes.")
        self.loader_hint.configure(text=tr(text))

    def _post(self, callback):
        self.launcher.after(0, lambda: callback() if self.winfo_exists() else None)

    def _queue_log(self, line):
        with self._log_lock:
            self._logs.append(str(line))

    def _flush_logs(self):
        with self._log_lock:
            lines = [self._logs.popleft() for _ in range(min(100, len(self._logs)))]
        if lines:
            self.console.configure(state="normal")
            self.console.insert("end", "\n".join(lines) + "\n")
            count = int(self.console.index("end-1c").split(".")[0])
            if count > 2000:
                self.console.delete("1.0", f"{count - 2000}.0")
            self.console.see("end")
            self.console.configure(state="disabled")
        if not self._closing:
            self._log_timer = self.launcher.after(150, self._flush_logs)

    def _status(self, text):
        self.status_label.configure(text=translate_displayed(text))

    def _set_controls(self, running=False, pending=False):
        for control in (self.loader_menu, self.version_menu, self.ram_menu):
            control.configure(state="disabled" if running or pending else "normal")
        self.start_button.configure(
            text=tr("Preparando servidor…")
            if pending
            else tr("Detener Servidor" if running else "Iniciar Servidor Local"),
            state="disabled" if pending or self._closing else "normal",
            fg_color=DANGER if running else CYAN,
            hover_color=DANGER_H if running else CYAN_H,
            text_color=WHITE if running else BG,
        )

    def toggle_server(self):
        if getattr(self.launcher, "_updating", False):
            self._status(tr("Espera a que termine la operación actual."))
            return
        if self._closing or self._starting or self._stopping:
            return
        if self.manager.is_running:
            self._stopping = True
            self.start_button.configure(state="disabled")
            self._status(tr("Guardando mundo y deteniendo servidor…"))
            self._operation_thread = threading.Thread(target=self._stop_worker, daemon=True)
            self._operation_thread.start()
            return
        limit = safe_ram_limit()
        ram = int(self.ram_var.get().split()[0])
        if limit < 2 or ram > limit:
            self.ram_menu.configure(values=[f"{value} GB" for value in range(2, max(2, limit) + 1)])
            self._status(tr("RAM insuficiente. Libera memoria o reduce la asignación del servidor."))
            return
        version, loader = self.version_var.get().strip(), self.loader_var.get().lower()
        if not version:
            self._status(tr("Selecciona una versión de Minecraft."))
            return
        self.launcher.settings.set("server_version", version)
        self.launcher.settings.set("server_loader", loader)
        self.launcher.settings.set("server_ram_gb", ram)
        if not self.launcher.settings.save():
            self._status(tr("No se pudieron guardar los ajustes."))
            return
        self._cancel.clear()
        self._starting = True
        self._public_address = self._claim_url = ""
        self.copy_button.configure(state="disabled")
        self.claim_button.configure(state="disabled")
        self.address_label.configure(text=tr("Tu IP pública para amigos: pendiente"))
        self._status(tr("Descargando y preparando servidor y Playit…"))
        self._set_controls(pending=True)
        self._operation_thread = threading.Thread(
            target=self._start_worker, args=(version, loader, ram), daemon=True
        )
        self._operation_thread.start()

    def _start_worker(self, version, loader, ram):
        error = None
        try:
            self.manager.setup_server(
                version, loader, on_log_callback=self._queue_log, cancel_event=self._cancel
            )
            if not self._cancel.is_set():
                self.manager.ensure_playit_binary()
            if not self._cancel.is_set():
                self.manager.start_server(ram, self._queue_log, self._playit_event)
        except Exception as exc:
            logger.exception("Local server startup failed")
            error = str(exc)
            try:
                self.manager.stop_server()
            except Exception:
                logger.exception("Server startup cleanup failed")
        self._post(lambda message=error: self._finish_start(message))

    def _finish_start(self, error):
        self._starting = False
        self._set_controls(running=self.manager.is_running)
        if error:
            self._status(tr("Error: {message}").format(message=error))
        elif not self._closing:
            self._status(
                tr("Servidor iniciado. Esperando a Minecraft y al túnel Playit…")
                if self.manager.is_running
                else tr("Servidor detenido.")
            )

    def _playit_event(self, kind, value):
        self._post(lambda: self._apply_event(kind, value))

    def _apply_event(self, kind, value):
        if self._closing:
            return
        if kind == "claim":
            self._claim_url = value
            self.claim_button.configure(state="normal")
            self._status(tr("Vincula tu agente Playit para compartir el servidor."))
        elif kind == "address":
            self._public_address = value
            if not value:
                self.address_label.configure(text=tr("Tu IP pública para amigos: pendiente"))
                self.copy_button.configure(state="disabled")
                return
            self.address_label.configure(
                text=tr("Tu IP pública para amigos: {address}").format(address=value)
            )
            self.copy_button.configure(state="normal")
            self._status(tr("Túnel público disponible."))
        elif kind == "ready":
            self._status(tr("Minecraft listo. Conéctate a localhost:25565 o comparte la IP pública."))
        elif kind in {"error", "status"}:
            self._status(tr("Error: {message}").format(message=value) if kind == "error" else value)
        elif kind == "stopped":
            self._set_controls()
            self._public_address = self._claim_url = ""
            self.address_label.configure(text=tr("Tu IP pública para amigos: pendiente"))
            self.claim_button.configure(state="disabled")
            self.copy_button.configure(state="disabled")
            self._status(tr("Servidor detenido.") if not value else value)

    def _stop_worker(self):
        error = None
        try:
            self.manager.stop_server()
        except Exception as exc:
            logger.exception("Local server shutdown failed")
            error = str(exc)
        self._post(lambda message=error: self._finish_stop(message))

    def _finish_stop(self, error):
        self._stopping = False
        self._set_controls(running=self.manager.is_running)
        self.copy_button.configure(state="disabled")
        if not self.manager.is_running:
            self._public_address = self._claim_url = ""
            self.address_label.configure(text=tr("Tu IP pública para amigos: pendiente"))
            self.claim_button.configure(state="disabled")
        self._status(tr("Error: {message}").format(message=error) if error else tr("Servidor detenido."))

    def shutdown(self, on_complete):
        """Keep Tk alive until startup finishes and the world is saved."""
        if self._closing:
            return
        self._closing = True
        self._cancel.set()
        if self._log_timer:
            self.launcher.after_cancel(self._log_timer)
            self._log_timer = None
        self._status(tr("Guardando mundo y deteniendo servidor…"))
        self.start_button.configure(state="disabled")
        operation = self._operation_thread

        def worker():
            if operation is not None and operation.is_alive():
                operation.join()
            try:
                self.manager.stop_server()
            except Exception as exc:
                logger.exception("Launcher close: server shutdown failed")
                self._post(lambda message=str(exc): self._close_failed(message))
                return
            self._post(on_complete)

        threading.Thread(target=worker, daemon=True).start()

    def _close_failed(self, message):
        self._closing = False
        self._starting = self._stopping = False
        self._status(tr("Error: {message}").format(message=message))
        self._set_controls(running=self.manager.is_running)
        self._log_timer = self.launcher.after(150, self._flush_logs)

    def copy_address(self):
        if self._public_address:
            self.clipboard_clear()
            self.clipboard_append(self._public_address)
            self._status(tr("IP copiada."))

    def open_claim(self):
        if self._claim_url:
            threading.Thread(target=webbrowser.open, args=(self._claim_url,), daemon=True).start()

    def open_dashboard(self):
        threading.Thread(
            target=webbrowser.open, args=("https://playit.gg/account/tunnels",), daemon=True
        ).start()

    def toggle_console(self):
        self._console_visible = not self._console_visible
        if self._console_visible:
            self.console.pack(fill="both", expand=True, pady=(0, 8))
        else:
            self.console.pack_forget()
        self.console_button.configure(
            text=tr("Ocultar consola" if self._console_visible else "Mostrar consola")
        )

    def destroy(self):
        if self._log_timer:
            self.launcher.after_cancel(self._log_timer)
        super().destroy()
