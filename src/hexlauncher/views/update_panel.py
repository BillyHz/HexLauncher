"""Background release checks and verified, user-triggered update installation."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import customtkinter as ctk

from src.hexlauncher.core.updater import check_update, download_update, start_update
from src.hexlauncher.i18n import tr
from src.hexlauncher.palette import CARD, CYAN, TEXT_MAIN
from src.hexlauncher.version import VERSION

logger = logging.getLogger(__name__)


class UpdatePanel(ctk.CTkFrame):
    def __init__(self, parent, launcher):
        super().__init__(parent, fg_color=CARD, corner_radius=12)
        self.launcher = launcher
        self.release = None
        self._busy = False
        self.enabled = sys.platform == "win32" and bool(getattr(sys, "frozen", False))
        ctk.CTkLabel(self, text=tr("Actualizaciones"), text_color=CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self.automatic = ctk.BooleanVar(value=launcher.settings.get("auto_check_updates"))
        ctk.CTkSwitch(
            self,
            text=tr("Buscar actualizaciones al iniciar"),
            variable=self.automatic,
            command=self._save_preference,
            text_color=TEXT_MAIN,
        ).pack(anchor="w", padx=16, pady=6)
        self.status = ctk.CTkLabel(
            self,
            text=f"HexLauncher {VERSION}" if self.enabled else tr("Disponible en el ejecutable de Windows."),
            wraplength=820,
            anchor="w",
            justify="left",
        )
        self.status.pack(fill="x", padx=16, pady=6)
        self.check_button = ctk.CTkButton(
            self,
            text=tr("Buscar actualizaciones"),
            command=self.check,
            state="normal" if self.enabled else "disabled",
        )
        self.check_button.pack(side="left", padx=16, pady=(4, 12))
        self.install_button = ctk.CTkButton(
            self,
            text=tr("Actualizar y reiniciar"),
            command=self.install,
            state="disabled",
        )
        self.install_button.pack(side="right", padx=16, pady=(4, 12))

    def _save_preference(self):
        previous = self.launcher.settings.get("auto_check_updates")
        self.launcher.settings.set("auto_check_updates", self.automatic.get())
        if not self.launcher.settings.save():
            self.launcher.settings.set("auto_check_updates", previous)
            self.automatic.set(previous)
            self.status.configure(text=tr("No se pudieron guardar los ajustes."))

    def check(self, automatic=False):
        if not self.enabled or self._busy or (automatic and not self.automatic.get()):
            return
        self._busy = True
        self.check_button.configure(state="disabled")
        self.install_button.configure(state="disabled")
        self.status.configure(text=tr("Buscando actualizaciones..."))

        def worker():
            try:
                release = check_update()
                self.launcher.after(0, lambda: self._checked(release))
            except Exception as exc:
                logger.warning("Update check failed: %s", exc)
                self.launcher.after(0, lambda message=str(exc): self._failed(message))

        threading.Thread(target=worker, daemon=True).start()

    def _checked(self, release):
        self._busy = False
        self.release = release
        self.check_button.configure(state="normal")
        message = (
            tr("Version disponible: {version}").format(version=release.version)
            if release
            else tr("No hay una version estable mas reciente.")
        )
        self.status.configure(text=message)
        self.install_button.configure(state="normal" if release else "disabled")
        if release:
            self.launcher.bottom_bar.status_label.configure(text=message)

    def _failed(self, message):
        self._busy = False
        self.launcher._updating = False
        self.status.configure(text=tr("Error de actualizacion: {message}").format(message=message))
        self.check_button.configure(state="normal")
        self.install_button.configure(state="normal" if self.release else "disabled")

    def _idle(self):
        app = self.launcher
        return not (
            app._is_launching
            or app._mc_process is not None
            or app.modrinth_view._busy
            or app.server_view.active
            or app.server_view._closing
        )

    def install(self):
        if not self.enabled or self._busy or self.release is None:
            return
        if not self._idle():
            self.status.configure(text=tr("Deten Minecraft y el servidor antes de actualizar."))
            return
        self._busy = True
        self.launcher._updating = True
        self.check_button.configure(state="disabled")
        self.install_button.configure(state="disabled")
        release = self.release

        def progress(value):
            self.launcher.after(
                0,
                lambda: self.status.configure(
                    text=tr("Descargando actualizacion: {percent}%").format(percent=int(value * 100))
                ),
            )

        def worker():
            try:
                pending = download_update(release, Path(sys.executable).resolve(), progress)
                self.launcher.after(0, lambda: self._apply(pending, release.sha256))
            except Exception as exc:
                logger.exception("Update download failed")
                self.launcher.after(0, lambda message=str(exc): self._failed(message))

        threading.Thread(target=worker, daemon=True).start()

    def _apply(self, pending, digest):
        try:
            if not self._idle():
                raise RuntimeError(tr("Deten Minecraft y el servidor antes de actualizar."))
            if not self.launcher.settings.save():
                raise RuntimeError(tr("No se pudieron guardar los ajustes."))
            start_update(pending, Path(sys.executable).resolve(), digest)
            self._busy = False
            self.launcher._on_close()
        except Exception as exc:
            logger.exception("Update installation failed")
            self._failed(str(exc))
