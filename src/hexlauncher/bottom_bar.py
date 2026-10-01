"""TLauncher-style bottom action bar and launcher controls for HexLauncher."""

from __future__ import annotations

import re
import tkinter

import customtkinter as ctk

from src.hexlauncher.i18n import tr
from src.hexlauncher.palette import (
    BG,
    BORDER,
    CARD,
    CARD_LIGHT,
    CYAN,
    CYAN_DIM,
    CYAN_H,
    DANGER,
    DANGER_H,
    MUTED,
    MUTED_LIGHT,
    SUCCESS,
    TEXT_MAIN,
    WARN,
    WHITE,
)
from src.hexlauncher.widgets import AvatarWidget, Badge, VersionSelector


class BottomBar(ctk.CTkFrame):
    """The central bottom dock containing the user profile, version selection, and play button."""

    USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")

    def __init__(self, parent, launcher, **kwargs):
        super().__init__(
            parent,
            fg_color=CARD,
            border_color=BORDER,
            border_width=1,
            corner_radius=0,
            **kwargs,
        )
        self.launcher = launcher
        self._build_bar()

    def _build_bar(self):
        # ── 1. Top progress bar & status line ─────────────────────────────────
        status_row = tkinter.Frame(self, bg=CARD)
        status_row.pack(fill="x", padx=16, pady=(6, 2))

        self.progress_bar = ctk.CTkProgressBar(
            status_row,
            height=3,
            corner_radius=2,
            fg_color=BORDER,
            progress_color=CYAN,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(0, 3))

        self.status_label = ctk.CTkLabel(
            status_row,
            text=tr("Iniciando…"),
            font=("Segoe UI", 10),
            text_color=MUTED_LIGHT,
            anchor="w",
        )
        self.status_label.pack(fill="x")

        # ── 2. Main Controls Bar (Horizontal Dock) ────────────────────────────
        dock = tkinter.Frame(self, bg=CARD)
        dock.pack(fill="x", padx=16, pady=(4, 12))

        # Left Section: Profile / Username
        profile_frame = tkinter.Frame(dock, bg=CARD)
        profile_frame.pack(side="left", padx=(0, 16))

        self.avatar = AvatarWidget(profile_frame, size=38)
        self.avatar.pack(side="left", padx=(0, 8))

        user_input_frame = tkinter.Frame(profile_frame, bg=CARD)
        user_input_frame.pack(side="left")

        user_top = tkinter.Frame(user_input_frame, bg=CARD)
        user_top.pack(fill="x", anchor="w")

        ctk.CTkLabel(
            user_top,
            text=tr("CUENTA / APODO"),
            font=("Segoe UI", 9, "bold"),
            text_color=MUTED,
        ).pack(side="left")

        self.user_feedback = ctk.CTkLabel(
            user_top,
            text="",
            font=("Segoe UI", 9),
            text_color=MUTED,
        )
        self.user_feedback.pack(side="left", padx=(6, 0))

        self.username_var = ctk.StringVar()
        self.username_input = ctk.CTkEntry(
            user_input_frame,
            placeholder_text=tr("Tu nickname…"),
            textvariable=self.username_var,
            width=160,
            height=32,
            corner_radius=8,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_MAIN,
            font=("Segoe UI", 12),
        )
        self.username_input.pack(fill="x", pady=(2, 0))

        # Restore saved username
        saved_user = self.launcher.settings.get("username") or ""
        if saved_user:
            self.username_input.insert(0, saved_user)

        self.username_var.trace_add("write", lambda *_: self._validate_username())

        # Middle Section: Version & Mod Loader Selector
        mid_frame = tkinter.Frame(dock, bg=CARD)
        mid_frame.pack(side="left", fill="x", expand=True, padx=(0, 16))

        mid_top = tkinter.Frame(mid_frame, bg=CARD)
        mid_top.pack(fill="x", anchor="w")

        ctk.CTkLabel(
            mid_top,
            text=tr("MOD LOADER & VERSIÓN"),
            font=("Segoe UI", 9, "bold"),
            text_color=MUTED,
        ).pack(side="left", padx=(0, 10))

        self.installed_badge = Badge(
            mid_top,
            text=tr("Verificando…"),
            fg_color=BG,
            text_color=MUTED,
            font_size=9,
            height=18,
        )
        self.installed_badge.pack(side="left")

        # Dropdowns row
        combo_row = tkinter.Frame(mid_frame, bg=CARD)
        combo_row.pack(fill="x", pady=(2, 0))

        self.loader_menu = ctk.CTkOptionMenu(
            combo_row,
            variable=self.launcher.loader_var,
            values=["Vanilla", "Fabric", "Forge", "NeoForge"],
            command=self._on_loader_changed,
            width=110,
            height=32,
            corner_radius=8,
            fg_color=BG,
            button_color=CYAN,
            button_hover_color=CYAN_H,
            dropdown_fg_color=CARD,
            dropdown_hover_color=CYAN_DIM,
            text_color=WHITE,
            font=("Segoe UI", 11, "bold"),
            dropdown_font=("Segoe UI", 11),
        )
        self.loader_menu.pack(side="left", padx=(0, 6))

        self.version_combo = VersionSelector(
            combo_row,
            variable=self.launcher.version_var,
            values=[tr("Cargando…")],
            command=self._on_version_changed,
            height=32,
        )
        self.version_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))

        # Quick utility buttons
        self.btn_refresh = ctk.CTkButton(
            combo_row,
            text="🔄",
            command=self.launcher._refresh_versions,
            width=32,
            height=32,
            corner_radius=8,
            fg_color=CARD_LIGHT,
            hover_color=CYAN_DIM,
            text_color=WHITE,
            font=("Segoe UI", 12),
        )
        self.btn_refresh.pack(side="left")

        # Right Section: Big Prominent Play / Stop Button
        right_frame = tkinter.Frame(dock, bg=CARD)
        right_frame.pack(side="right")

        self.play_button = ctk.CTkButton(
            right_frame,
            text=tr("▶   ENTRAR AL JUEGO"),
            command=self.launcher._start_launch_thread,
            fg_color=CYAN,
            hover_color=CYAN_H,
            text_color=BG,
            font=("Segoe UI", 13, "bold"),
            width=200,
            height=42,
            corner_radius=10,
            state="disabled",
        )
        self.play_button.pack(side="right")

        self._validate_username()

    def _on_loader_changed(self, loader_value: str):
        self.launcher._update_version_list()
        self.launcher._update_mods_count()
        if hasattr(self.launcher, "modrinth_view"):
            self.launcher.modrinth_view.update_filter_badge()

    def _on_version_changed(self, version_value: str):
        self.launcher._check_installed(version_value)
        self.launcher._update_mods_count()
        if hasattr(self.launcher, "modrinth_view"):
            self.launcher.modrinth_view.update_filter_badge()

    def _validate_username(self) -> bool:
        name = self.username_var.get().strip()
        if not name:
            self.user_feedback.configure(text="", text_color=MUTED)
            self.avatar.load_avatar("")
            self.set_play_enabled(False)
            return False
        if not self.USERNAME_RE.match(name):
            self.user_feedback.configure(text=tr("✗ 3-16 caracteres válidos"), text_color=WARN)
            self.set_play_enabled(False)
            return False

        self.user_feedback.configure(text=tr("✓ Listo"), text_color=SUCCESS)
        self.avatar.load_avatar(name)
        self.set_play_enabled(True)
        return True

    def set_play_enabled(self, enabled: bool):
        if self.launcher._mc_process is not None:
            self.set_running_state(True)
            return
        if getattr(self.launcher, "_is_launching", False):
            enabled = False
        self.play_button.configure(
            state="normal" if enabled else "disabled",
            fg_color=CYAN if enabled else BORDER,
            text_color=BG if enabled else MUTED,
        )

    def set_running_state(self, is_running: bool):
        """Keep the stop action accessible while Minecraft is running."""
        if is_running:
            self.play_button.configure(
                text=tr("■   DETENER"),
                command=self.launcher._kill_game,
                fg_color=DANGER,
                hover_color=DANGER_H,
                text_color=WHITE,
                state="normal",
            )
        else:
            self.play_button.configure(
                text=tr("▶   ENTRAR AL JUEGO"),
                command=self.launcher._start_launch_thread,
                fg_color=CYAN,
                hover_color=CYAN_H,
                text_color=BG,
                state="normal",
            )
            self._validate_username()

    def update_installed_status(self, is_installed: bool, version_id: str):
        if is_installed:
            self.installed_badge.configure_badge(
                text=tr("✔ Instalado"),
                fg_color=CARD_LIGHT,
                text_color=SUCCESS,
            )
            if self.launcher._mc_process is None:
                self.play_button.configure(text=tr("▶   ENTRAR AL JUEGO"))
        else:
            self.installed_badge.configure_badge(
                text=tr("⬇ Descarga requerida"),
                fg_color=CARD_LIGHT,
                text_color=WARN,
            )
            if self.launcher._mc_process is None:
                self.play_button.configure(text=tr("⬇   INSTALAR Y JUGAR"))
