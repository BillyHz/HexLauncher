"""Settings and configuration view for HexLauncher."""

from __future__ import annotations

import tkinter.filedialog

import customtkinter as ctk
import psutil

from src.hexlauncher.i18n import refresh_language, tr
from src.hexlauncher.palette import (
    BG,
    BORDER,
    CARD,
    CARD_LIGHT,
    CYAN,
    CYAN_DIM,
    CYAN_H,
    MUTED,
    MUTED_LIGHT,
    SUCCESS,
    TEXT_MAIN,
    WARN,
    WHITE,
)
from src.hexlauncher.widgets import Badge


class SettingsView(ctk.CTkFrame):
    def __init__(self, parent, launcher, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.launcher = launcher
        self._build_view()

    def _build_view(self):
        scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
        )
        scroll.pack(fill="both", expand=True, padx=16, pady=(8, 8))

        language_card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=12)
        language_card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(language_card, text=tr("Idioma"), text_color=CYAN, font=("Segoe UI", 12, "bold")).pack(
            side="left", padx=16, pady=14
        )
        self.language_var = ctk.StringVar(value=self.launcher.settings.get("language"))
        self.language_switch = ctk.CTkSwitch(
            language_card,
            text="EN / ES",
            variable=self.language_var,
            offvalue="en",
            onvalue="es",
            command=self._change_language,
            progress_color=CYAN,
            button_color=WHITE,
            text_color=TEXT_MAIN,
        )
        self.language_switch.pack(side="right", padx=16, pady=14)

        # ── 1. RAM Allocation Card ────────────────────────────────────────────
        ram_card = ctk.CTkFrame(scroll, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=12)
        ram_card.pack(fill="x", pady=(0, 12))

        ram_header = ctk.CTkFrame(ram_card, fg_color="transparent")
        ram_header.pack(fill="x", padx=16, pady=(14, 6))

        ctk.CTkLabel(
            ram_header,
            text="⚡ ASIGNACIÓN DE MEMORIA RAM",
            font=("Segoe UI", 12, "bold"),
            text_color=CYAN,
        ).pack(side="left")

        try:
            total_ram_gb = round(psutil.virtual_memory().total / (1024**3))
        except Exception:
            total_ram_gb = 16

        Badge(
            ram_header,
            text=tr("RAM del Sistema: {ram} GB").format(ram=total_ram_gb),
            fg_color=CARD_LIGHT,
            text_color=MUTED_LIGHT,
        ).pack(side="right")

        # Current RAM value display
        current_ram = int(self.launcher.settings.get("ram_gb") or 4)

        slider_row = ctk.CTkFrame(ram_card, fg_color="transparent")
        slider_row.pack(fill="x", padx=16, pady=4)

        self.ram_val_label = ctk.CTkLabel(
            slider_row,
            text=f"{current_ram} GB",
            font=("Segoe UI", 18, "bold"),
            text_color=TEXT_MAIN,
            width=60,
        )
        self.ram_val_label.pack(side="left", padx=(0, 12))

        max_slider = min(32, max(8, total_ram_gb - 2))
        self.ram_slider = ctk.CTkSlider(
            slider_row,
            from_=2,
            to=max_slider,
            number_of_steps=max_slider - 2,
            command=self._on_ram_slider_change,
            button_color=CYAN,
            button_hover_color=CYAN_H,
            progress_color=CYAN,
            fg_color=BG,
        )
        self.ram_slider.set(current_ram)
        self.ram_slider.pack(side="left", fill="x", expand=True)

        self.ram_note = ctk.CTkLabel(
            ram_card,
            text="Recomendado: 4 GB a 6 GB para la mayoría de versiones y modpacks.",
            font=("Segoe UI", 10),
            text_color=MUTED,
            anchor="w",
        )
        self.ram_note.pack(fill="x", padx=16, pady=(0, 14))

        # ── 2. Java Runtime Card ──────────────────────────────────────────────
        java_card = ctk.CTkFrame(scroll, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=12)
        java_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            java_card,
            text="☕ ENTORNO JAVA RUNTIME",
            font=("Segoe UI", 12, "bold"),
            text_color=WHITE,
        ).pack(anchor="w", padx=16, pady=(14, 6))

        # Java path info
        java_path_row = ctk.CTkFrame(java_card, fg_color="transparent")
        java_path_row.pack(fill="x", padx=16, pady=(0, 6))

        self.java_path_var = ctk.StringVar(value=self.launcher.settings.get("custom_java_path") or "")
        self.java_entry = ctk.CTkEntry(
            java_path_row,
            placeholder_text="Java Integrado: Adoptium OpenJDK 21 (Descarga automática)",
            textvariable=self.java_path_var,
            height=34,
            corner_radius=8,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_MAIN,
            font=("Segoe UI", 11),
        )
        self.java_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            java_path_row,
            text="Examinar…",
            command=self._pick_java,
            width=90,
            height=34,
            corner_radius=8,
            fg_color=CARD_LIGHT,
            hover_color=CYAN_DIM,
            text_color=TEXT_MAIN,
            font=("Segoe UI", 11),
        ).pack(side="right")

        ctk.CTkLabel(
            java_card,
            text="Si se deja vacío, HexLauncher utiliza automáticamente Java 21 LTS de alto rendimiento.",
            font=("Segoe UI", 10),
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 14))

        # ── 3. JVM Arguments & Advanced ───────────────────────────────────────
        jvm_card = ctk.CTkFrame(scroll, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=12)
        jvm_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            jvm_card,
            text="⚙️ ARGUMENTOS JVM ADICIONALES",
            font=("Segoe UI", 12, "bold"),
            text_color=WHITE,
        ).pack(anchor="w", padx=16, pady=(14, 6))

        self.jvm_args_var = ctk.StringVar(value=self.launcher.settings.get("custom_jvm_args") or "")
        self.jvm_entry = ctk.CTkEntry(
            jvm_card,
            placeholder_text="Ejemplo: -XX:+UseG1GC -XX:+ParallelRefProcEnabled",
            textvariable=self.jvm_args_var,
            height=34,
            corner_radius=8,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_MAIN,
            font=("Segoe UI", 11),
        )
        self.jvm_entry.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkLabel(
            jvm_card,
            text="Los argumentos de memoria (-Xmx y -Xms) se configuran automáticamente arriba.",
            font=("Segoe UI", 10),
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 14))

        # ── 4. Launcher Behavior ──────────────────────────────────────────────
        behav_card = ctk.CTkFrame(
            scroll, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=12
        )
        behav_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            behav_card,
            text="🖥️ COMPORTAMIENTO DEL LANZADOR",
            font=("Segoe UI", 12, "bold"),
            text_color=WHITE,
        ).pack(anchor="w", padx=16, pady=(14, 8))

        self.close_on_launch_var = ctk.BooleanVar(value=bool(self.launcher.settings.get("close_on_launch")))
        self.switch_close = ctk.CTkSwitch(
            behav_card,
            text="Ocultar el lanzador automáticamente al iniciar Minecraft",
            variable=self.close_on_launch_var,
            onvalue=True,
            offvalue=False,
            progress_color=CYAN,
            button_color=WHITE,
            button_hover_color=CYAN_H,
            font=("Segoe UI", 11),
            text_color=TEXT_MAIN,
        )
        self.switch_close.pack(anchor="w", padx=16, pady=(0, 10))

        # ── Bottom Action Save Bar ────────────────────────────────────────────
        save_bar = ctk.CTkFrame(scroll, fg_color="transparent")
        save_bar.pack(fill="x", pady=4)

        self.saved_feedback = ctk.CTkLabel(
            save_bar,
            text="",
            font=("Segoe UI", 11),
            text_color=SUCCESS,
            anchor="w",
        )
        self.saved_feedback.pack(side="left", padx=4)

        ctk.CTkButton(
            save_bar,
            text="Guardar Cambios",
            command=self.save_settings,
            height=34,
            corner_radius=8,
            fg_color=CYAN,
            hover_color=CYAN_H,
            text_color=BG,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="right")

    def _on_ram_slider_change(self, value):
        val_gb = int(value)
        self.ram_val_label.configure(text=f"{val_gb} GB")
        if val_gb < 3:
            self.ram_note.configure(
                text="⚠ Asignación baja: Minecraft moderno puede presentar tirones.", text_color=WARN
            )
        elif 4 <= val_gb <= 8:
            self.ram_note.configure(
                text="✓ Rango ideal para rendimiento fluido y modpacks estándar.", text_color=SUCCESS
            )
        else:
            self.ram_note.configure(
                text="Alto: Asegúrate de tener suficiente RAM libre en Windows.", text_color=MUTED_LIGHT
            )
        refresh_language(self)

    def _change_language(self):
        if not self.launcher.change_language(self.language_var.get()):
            self.language_var.set(self.launcher.settings.get("language"))
            self.saved_feedback.configure(text=tr("No se pudieron guardar los ajustes."), text_color=WARN)

    def _pick_java(self):
        filename = tkinter.filedialog.askopenfilename(
            title=tr("Seleccionar ejecutable java.exe"),
            filetypes=[("Java Executable", "java.exe"), ("All Files", "*.*")],
        )
        if filename:
            self.java_path_var.set(filename)

    def save_settings(self):
        try:
            # Validate JVM input before changing the other settings.
            self.launcher.settings.set("custom_jvm_args", self.jvm_args_var.get().strip())
            self.launcher.settings.set("ram_gb", int(self.ram_slider.get()))
            self.launcher.settings.set("custom_java_path", self.java_path_var.get().strip())
            self.launcher.settings.set("close_on_launch", self.close_on_launch_var.get())
            if not self.launcher.settings.save():
                self.saved_feedback.configure(text=tr("No se pudieron guardar los ajustes."), text_color=WARN)
                return
        except (ValueError, OSError) as exc:
            self.saved_feedback.configure(text=str(exc), text_color=WARN)
            return

        self.saved_feedback.configure(text=tr("✓ Ajustes guardados correctamente"), text_color=SUCCESS)
        self.launcher.after(3000, lambda: self.saved_feedback.configure(text=""))
        self.launcher.home_view.refresh_stats()
