"""A quiet launch overview. Content management belongs in its own tabs."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from src.hexlauncher.i18n import tr
from src.hexlauncher.palette import CARD, CYAN, MUTED_LIGHT, PURPLE, SUCCESS, TEXT_MAIN
from src.hexlauncher.widgets import StatCard


class HomeView(ctk.CTkFrame):
    def __init__(self, parent, launcher, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.launcher = launcher
        self._build_view()

    def _build_view(self):
        ctk.CTkLabel(
            self, text=tr("Bienvenido a HexLauncher"), anchor="w",
            font=("Segoe UI", 24, "bold"), text_color=TEXT_MAIN,
        ).pack(fill="x", padx=24, pady=(28, 4))
        ctk.CTkLabel(
            self, text=tr("Elige tu versión y pulsa Jugar en la barra inferior."),
            anchor="w", text_color=MUTED_LIGHT,
        ).pack(fill="x", padx=24, pady=(0, 24))

        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.pack(fill="x", padx=20, pady=(0, 20))
        self.card_version = StatCard(
            summary, icon="🎮", title=tr("Versión Actual"), value=tr("Cargando…"),
            accent_color=CYAN,
        )
        self.card_version.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.card_ram = StatCard(
            summary, icon="⚡", title=tr("Memoria RAM"), value="",
            accent_color=SUCCESS,
        )
        self.card_ram.pack(side="left", fill="both", expand=True, padx=5)
        self.card_mods = StatCard(
            summary, icon="🧩", title=tr("Mods instalados"), value="0 Mods",
            accent_color=PURPLE,
        )
        self.card_mods.pack(side="left", fill="both", expand=True, padx=(5, 0))

        installation = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        installation.pack(fill="x", padx=20)
        ctk.CTkLabel(
            installation, text=tr("Instalación seleccionada"), anchor="w", text_color=MUTED_LIGHT,
        ).pack(fill="x", padx=16, pady=(12, 0))
        self.installation_label = ctk.CTkLabel(
            installation, text="", anchor="w", justify="left", wraplength=900,
            text_color=TEXT_MAIN, font=("Segoe UI", 13, "bold"),
        )
        self.installation_label.pack(fill="x", padx=16, pady=(0, 12))

    def refresh_stats(self):
        app = self.launcher
        version = app.version_var.get()
        loader = app.loader_var.get()
        self.card_version.update_card(
            value=version or tr("Cargando…"), subtitle=f"Loader: {loader}",
        )
        ram = app.settings.get("ram_gb") or 4
        self.card_ram.update_card(
            value=tr("{ram} GB Asignados").format(ram=ram),
            subtitle=tr("Configuración óptima") if 4 <= ram <= 8 else tr("Personalizada"),
        )
        self.installation_label.configure(text=(
            app.modrinth_view.instance_var.get()
            if app.settings.get("active_instance_dir") else tr("Instalación habitual")
        ))
        try:
            directory = Path(app._mods_folder_for(loader, version))
            count = sum(1 for file in directory.iterdir() if file.is_file() and file.suffix.lower() == ".jar")
            self.card_mods.update_card(
                value=f"{count} Mod{'s' if count != 1 else ''}",
                subtitle=tr("En {loader} {version}").format(loader=loader, version=version),
            )
        except (OSError, ValueError):
            self.card_mods.update_card(value="0 Mods", subtitle=tr("Carpeta vacía"))
