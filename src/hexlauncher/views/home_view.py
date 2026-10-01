"""Home / Dashboard view for HexLauncher.

Displays modern overview cards, system status, quick tips, and direct shortcut actions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter

import customtkinter as ctk

from src.hexlauncher.palette import (
    BG,
    CARD,
    CARD_LIGHT,
    CYAN,
    CYAN_DIM,
    CYAN_GLOW,
    MUTED_LIGHT,
    PURPLE,
    SUCCESS,
    TEXT_MAIN,
    WHITE,
)
from src.hexlauncher.paths import JAVA_DIR, LOGS_DIR, MC_DIR
from src.hexlauncher.widgets import Badge, StatCard


class HomeView(ctk.CTkFrame):
    def __init__(self, parent, launcher, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.launcher = launcher
        self._build_view()

    def _build_view(self):
        # Top Hero Card (Banner)
        hero = ctk.CTkFrame(
            self,
            fg_color=CARD,
            border_width=0,
            corner_radius=14,
        )
        hero.pack(fill="x", padx=16, pady=(8, 12))

        # Hero content row
        hero_inner = tkinter.Frame(hero, bg=CARD)
        hero_inner.pack(fill="x", padx=20, pady=16)

        left_hero = tkinter.Frame(hero_inner, bg=CARD)
        left_hero.pack(side="left", fill="both", expand=True)

        # Title + tag
        tag_row = tkinter.Frame(left_hero, bg=CARD)
        tag_row.pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(
            tag_row,
            text="HEXLAUNCHER",
            font=("Segoe UI", 20, "bold"),
            text_color=CYAN,
        ).pack(side="left", padx=(0, 10))

        Badge(
            tag_row,
            text="MINECRAFT EDITION",
            fg_color=CYAN_GLOW,
            text_color=CYAN,
            border_color=CYAN_DIM,
            font_size=9,
            height=20,
        ).pack(side="left")

        ctk.CTkLabel(
            left_hero,
            text="Experiencia optimizada, minimalista y de alto rendimiento para Minecraft.",
            font=("Segoe UI", 12),
            text_color=MUTED_LIGHT,
        ).pack(anchor="w", pady=(0, 10))

        # Feature pills
        pills_row = tkinter.Frame(left_hero, bg=CARD)
        pills_row.pack(anchor="w")

        Badge(pills_row, text="⚡ Fabric & Forge Ready", fg_color=CARD_LIGHT, text_color=SUCCESS).pack(
            side="left", padx=(0, 8)
        )
        Badge(pills_row, text="☕ Adoptium Java 21 LTS", fg_color=CARD_LIGHT, text_color=MUTED_LIGHT).pack(
            side="left", padx=(0, 8)
        )
        Badge(pills_row, text="📦 Modrinth Integrado", fg_color=CARD_LIGHT, text_color=PURPLE).pack(
            side="left"
        )

        # ── 3 Stat Cards Row ──────────────────────────────────────────────────
        stats_container = tkinter.Frame(self, bg=BG)
        stats_container.pack(fill="x", padx=16, pady=(0, 12))

        # Card 1: Version & Loader
        self.card_version = StatCard(
            stats_container,
            icon="🎮",
            title="Versión Actual",
            value=self.launcher.version_var.get() or "Cargando…",
            subtitle=f"Loader: {self.launcher.loader_var.get()}",
            accent_color=CYAN,
        )
        self.card_version.pack(side="left", fill="both", expand=True, padx=(0, 4))

        # Card 2: Memory RAM
        ram_gb = self.launcher.settings.get("ram_gb") or 4
        self.card_ram = StatCard(
            stats_container,
            icon="⚡",
            title="Memoria RAM",
            value=f"{ram_gb} GB Asignados",
            subtitle="Auto-configurado para juego suave",
            accent_color=SUCCESS,
        )
        self.card_ram.pack(side="left", fill="both", expand=True, padx=4)

        # Card 3: Mods Count
        self.card_mods = StatCard(
            stats_container,
            icon="🧩",
            title="Mods Activos",
            value="0 Mods",
            subtitle="Haz clic en 'Mods' para buscar",
            accent_color=PURPLE,
        )
        self.card_mods.pack(side="left", fill="both", expand=True, padx=(4, 0))

        # ── Lower Split Grid: Tips & Shortcuts ────────────────────────────────
        bottom_grid = tkinter.Frame(self, bg=BG)
        bottom_grid.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # Left panel: Quick Tips & Recommendations
        tips_card = ctk.CTkFrame(
            bottom_grid,
            fg_color=CARD,
            border_width=0,
            corner_radius=12,
        )
        tips_card.pack(side="left", fill="both", expand=True, padx=(0, 4))

        tips_title_row = tkinter.Frame(tips_card, bg=CARD)
        tips_title_row.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(
            tips_title_row,
            text="💡 CONSEJOS DE RENDIMIENTO",
            font=("Segoe UI", 11, "bold"),
            text_color=CYAN,
        ).pack(side="left")

        tips_text = (
            "• Selecciona Fabric e instala Sodium + Lithium desde la pestaña 'Mods' para mejorar tus FPS.\n"
            "• Para soporte de Shaders: Agrega Iris Shaders (compatible con tus paquetes Sodium favoritos).\n"
            "• Asignación recomendada: 4 a 6 GB de RAM para evitar sobrecargar el recolector de Java.\n"
            "• Auto-descarga: HexLauncher descargará automáticamente Minecraft y Java 21 al pulsar 'JUGAR'."
        )
        ctk.CTkLabel(
            tips_card,
            text=tips_text,
            font=("Segoe UI", 11),
            text_color=MUTED_LIGHT,
            justify="left",
            anchor="nw",
        ).pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # Right panel: Direct Directory Shortcuts
        actions_card = ctk.CTkFrame(
            bottom_grid,
            fg_color=CARD,
            border_width=0,
            corner_radius=12,
        )
        actions_card.pack(side="right", fill="both", expand=True, padx=(4, 0))

        actions_title_row = tkinter.Frame(actions_card, bg=CARD)
        actions_title_row.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(
            actions_title_row,
            text="📁 ACCESOS RÁPIDOS",
            font=("Segoe UI", 11, "bold"),
            text_color=WHITE,
        ).pack(side="left")

        btn_style = {
            "height": 30,
            "corner_radius": 8,
            "fg_color": CARD_LIGHT,
            "hover_color": CYAN_DIM,
            "text_color": TEXT_MAIN,
            "font": ("Segoe UI", 11),
            "anchor": "w",
        }

        ctk.CTkButton(
            actions_card,
            text="📂  Carpeta .minecraft (HexFiles)",
            command=lambda: self._open_path(MC_DIR),
            **btn_style,
        ).pack(fill="x", padx=14, pady=3)

        ctk.CTkButton(
            actions_card,
            text="🧩  Carpeta de Mods",
            command=self.launcher._open_mods_folder,
            **btn_style,
        ).pack(fill="x", padx=14, pady=3)

        ctk.CTkButton(
            actions_card,
            text="☕  Carpeta Java 21 (HexJDK)",
            command=lambda: self._open_path(JAVA_DIR),
            **btn_style,
        ).pack(fill="x", padx=14, pady=3)

        ctk.CTkButton(
            actions_card,
            text="📋  Ver Registros / Logs",
            command=lambda: self._open_path(LOGS_DIR),
            **btn_style,
        ).pack(fill="x", padx=14, pady=3)

    def _open_path(self, path: str):
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

    def refresh_stats(self):
        """Called when version, loader, or settings are changed."""
        v = self.launcher.version_var.get()
        loader = self.launcher.loader_var.get()
        self.card_version.update_card(
            value=v if v else "Cargando…",
            subtitle=f"Loader: {loader}",
        )
        ram = self.launcher.settings.get("ram_gb") or 4
        self.card_ram.update_card(
            value=f"{ram} GB Asignados",
            subtitle="Configuración óptima" if 4 <= ram <= 8 else "Personalizada",
        )

        # Count mods
        path = self.launcher._mods_folder_for(loader, v)
        try:
            count = sum(1 for f in os.listdir(path) if f.lower().endswith(".jar"))
            self.card_mods.update_card(
                value=f"{count} Mod{'s' if count != 1 else ''}",
                subtitle=f"En {loader} {v}",
            )
        except Exception:
            self.card_mods.update_card(value="0 Mods", subtitle="Carpeta vacía")
