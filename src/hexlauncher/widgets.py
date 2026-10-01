"""HexLauncher custom UI widgets.

Contains:
- CTkScrollableDropdown: Compact, searchable, scrollable dropdown popup with auto-direction (up/down).
- VersionSelector: Modern unified clickable version selector box with dropdown arrow.
- StatCard: Modern metric/status card for dashboard.
- Badge: Pill-style tag badge.
- NavTabButton: Top navigation button with active indicator.
- AvatarWidget: Interactive avatar widget with Minecraft skin loading.
"""

from __future__ import annotations

import io
import os
import threading
import tkinter
from collections.abc import Callable

import customtkinter as ctk
import requests
from PIL import Image

from src.hexlauncher.i18n import tr
from src.hexlauncher.palette import (
    BG,
    BORDER,
    BORDER_FOCUS,
    CARD,
    CARD_LIGHT,
    CYAN,
    CYAN_DIM,
    CYAN_GLOW,
    CYAN_H,
    MUTED,
    MUTED_LIGHT,
    TEXT_MAIN,
    WHITE,
)
from src.hexlauncher.paths import LOGS_DIR


class CTkScrollableDropdown(ctk.CTkFrame):
    """Modern in-window scrollable dropdown popover with instant search filter."""

    def __init__(
        self,
        attach_to,
        values: list[str] | None = None,
        command: Callable[[str], None] | None = None,
        current_value: str = "",
        width: int | None = None,
        height: int = 270,
        **kwargs,
    ):
        self.attach_to = attach_to
        self.all_values = list(values or [])
        self.command = command
        self.current_value = current_value
        self.master_root = self.attach_to.winfo_toplevel()

        # 1. Full-window transparent click-catcher backdrop
        self.backdrop = ctk.CTkFrame(self.master_root, fg_color="transparent")
        self.backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.backdrop.bind("<Button-1>", lambda e: self.destroy())

        # 2. Main Popover Container
        pop_width = max(width or self.attach_to.winfo_width(), 260)
        pop_height = height

        super().__init__(
            self.master_root,
            width=pop_width,
            height=pop_height,
            corner_radius=10,
            border_width=1,
            border_color=BORDER_FOCUS,
            fg_color=CARD,
            **kwargs,
        )
        self.pack_propagate(False)

        # Calculate position relative to root
        self.attach_to.update_idletasks()
        try:
            combo_x = self.attach_to.winfo_rootx() - self.master_root.winfo_rootx()
            combo_y = self.attach_to.winfo_rooty() - self.master_root.winfo_rooty()
            combo_h = self.attach_to.winfo_height()
            root_w = self.master_root.winfo_width()
        except Exception:
            combo_x, combo_y, combo_h, root_w = 20, 200, 32, 960

        # Position above or below attach_to
        if combo_y > pop_height + 20:
            pop_y = max(56, combo_y - pop_height - 6)
        else:
            pop_y = combo_y + combo_h + 6

        pop_x = max(10, min(combo_x, max(10, root_w - pop_width - 10)))
        self.place(x=pop_x, y=pop_y)
        self.lift()

        # 3. Top search bar
        search_frame = tkinter.Frame(self, bg=CARD)
        search_frame.pack(fill="x", padx=8, pady=(8, 4))

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text=tr("🔍 Filtrar versión…"),
            textvariable=self.search_var,
            height=28,
            corner_radius=6,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_MAIN,
            font=("Segoe UI", 11),
        )
        self.search_entry.pack(fill="x")
        self.search_var.trace_add("write", lambda *_: self._filter_items())

        # 4. Meta info row
        meta_row = tkinter.Frame(self, bg=CARD)
        meta_row.pack(fill="x", padx=10, pady=(2, 2))

        self.count_label = ctk.CTkLabel(
            meta_row,
            text=tr("{count} versiones").format(count=len(self.all_values)),
            font=("Segoe UI", 9),
            text_color=MUTED,
            anchor="w",
        )
        self.count_label.pack(side="left")

        # 5. Scrollable list of version options
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=CYAN,
            scrollbar_button_hover_color=CYAN_H,
        )
        self.scroll.pack(fill="both", expand=True, padx=4, pady=(0, 6))

        self.buttons: list[ctk.CTkButton] = []
        self._populate_items(self.all_values)

        # Focus & Escape bindings
        self.search_entry.focus_set()
        try:
            self._esc_bind = self.master_root.bind("<Escape>", lambda _: self.destroy(), add="+")
        except Exception:
            self._esc_bind = None

    def _populate_items(self, values: list[str]):
        if hasattr(self, "_render_task") and self._render_task:
            self.after_cancel(self._render_task)
            self._render_task = None

        for w in self.scroll.winfo_children():
            w.destroy()
        self.buttons = []

        self._current_values = values

        if not values:
            ctk.CTkLabel(
                self.scroll,
                text=tr("No hay versiones coincidentes"),
                font=("Segoe UI", 10),
                text_color=MUTED,
            ).pack(pady=20)
            return

        def render_chunk(start_idx: int, current_values: list):
            if not self.winfo_exists() or not self.scroll.winfo_exists():
                return
            if current_values is not self._current_values:
                return

            chunk = current_values[start_idx : start_idx + 25]
            for value in chunk:
                is_selected = value == self.current_value
                btn = ctk.CTkButton(
                    self.scroll,
                    text=f"  ✔  {value}" if is_selected else f"     {value}",
                    anchor="w",
                    height=26,
                    corner_radius=6,
                    fg_color=CYAN_GLOW if is_selected else BG,
                    text_color=CYAN if is_selected else WHITE,
                    hover_color=CYAN_DIM if is_selected else CARD_LIGHT,
                    border_width=1 if is_selected else 0,
                    border_color=BORDER_FOCUS if is_selected else CARD,
                    font=("Segoe UI", 11, "bold" if is_selected else "normal"),
                    command=lambda val=value: self._on_select(val),
                )
                btn.pack(fill="x", pady=1, padx=2)
                self.buttons.append(btn)

            if start_idx + 25 < len(current_values):
                self._render_task = self.after(5, lambda: render_chunk(start_idx + 25, current_values))

        render_chunk(0, values)

    def _filter_items(self):
        query = self.search_var.get().strip().lower()
        if not query:
            self.count_label.configure(text=tr("{count} versiones").format(count=len(self.all_values)))
            self._populate_items(self.all_values)
        else:
            filtered = [v for v in self.all_values if query in v.lower()]
            self.count_label.configure(
                text=tr("{count} de {total} versiones").format(
                    count=len(filtered), total=len(self.all_values)
                )
            )
            self._populate_items(filtered)

    def _on_select(self, value: str):
        if self.command:
            self.command(value)
        self.destroy()

    def destroy(self):
        try:
            if hasattr(self, "_esc_bind") and self._esc_bind:
                self.master_root.unbind("<Escape>", self._esc_bind)
        except Exception:
            pass
        try:
            if hasattr(self, "backdrop") and self.backdrop and self.backdrop.winfo_exists():
                self.backdrop.destroy()
        except Exception:
            pass
        super().destroy()
        if hasattr(self.attach_to, "_on_popover_closed"):
            self.attach_to._on_popover_closed()


class VersionSelector(ctk.CTkOptionMenu):
    """Modern version selector matching CTkOptionMenu visuals with searchable scrollable popup."""

    def __init__(
        self,
        parent,
        variable: ctk.StringVar,
        values: list[str] | None = None,
        command: Callable[[str], None] | None = None,
        width: int = 170,
        height: int = 32,
        **kwargs,
    ):
        self._user_command = command
        super().__init__(
            parent,
            variable=variable,
            values=values or [tr("Cargando…")],
            command=self._on_selected,
            width=width,
            height=height,
            corner_radius=8,
            fg_color=BG,
            button_color=CYAN,
            button_hover_color=CYAN_H,
            dropdown_fg_color=CARD,
            dropdown_hover_color=CYAN_DIM,
            text_color=WHITE,
            font=("Segoe UI", 11),
            **kwargs,
        )
        self._active_dropdown: CTkScrollableDropdown | None = None

    def _open_dropdown_menu(self):
        if self._active_dropdown and self._active_dropdown.winfo_exists():
            self._active_dropdown.destroy()
            self._active_dropdown = None
            return

        values = self._values
        if not values or values in (["Cargando…"], ["Loading…"]):
            return

        self._active_dropdown = CTkScrollableDropdown(
            attach_to=self,
            values=values,
            current_value=self.get(),
            command=self._on_selected,
            width=max(self.winfo_width(), 260),
        )

    def _on_selected(self, val: str):
        self.set(val)
        self._active_dropdown = None
        if self._user_command:
            self._user_command(val)

    def _on_popover_closed(self):
        self._active_dropdown = None

    def toggle_dropdown(self):
        self._open_dropdown_menu()

    def configure(self, require_redraw=False, **kwargs):
        if "command" in kwargs:
            self._user_command = kwargs.pop("command")
        super().configure(require_redraw=require_redraw, **kwargs)


class Badge(ctk.CTkFrame):
    """Pill-style badge for statuses, tags and counts."""

    def __init__(
        self,
        parent,
        text: str = "",
        fg_color: str = CARD_LIGHT,
        text_color: str = MUTED_LIGHT,
        border_color: str = BORDER,
        font_size: int = 10,
        height: int = 22,
        **kwargs,
    ):
        super().__init__(
            parent,
            fg_color=fg_color,
            border_color=border_color,
            border_width=1,
            corner_radius=height // 2,
            height=height,
            **kwargs,
        )
        self.label = ctk.CTkLabel(
            self,
            text=text,
            font=("Segoe UI", font_size, "bold"),
            text_color=text_color,
        )
        self.label.pack(padx=8, pady=1)

    def configure_badge(
        self, text: str | None = None, text_color: str | None = None, fg_color: str | None = None
    ):
        if text is not None:
            self.label.configure(text=text)
        if text_color is not None:
            self.label.configure(text_color=text_color)
        if fg_color is not None:
            self.configure(fg_color=fg_color)


class StatCard(ctk.CTkFrame):
    """Modern metric/status card for dashboard view."""

    def __init__(
        self,
        parent,
        icon: str,
        title: str,
        value: str,
        subtitle: str = "",
        accent_color: str = CYAN,
        **kwargs,
    ):
        super().__init__(
            parent,
            fg_color=CARD,
            border_width=0,
            corner_radius=12,
            **kwargs,
        )
        self.accent_color = accent_color

        top_row = tkinter.Frame(self, bg=CARD)
        top_row.pack(fill="x", padx=16, pady=(14, 4))

        self.icon_label = ctk.CTkLabel(
            top_row,
            text=icon,
            font=("Segoe UI", 16),
            text_color=accent_color,
        )
        self.icon_label.pack(side="left", padx=(0, 8))

        self.title_label = ctk.CTkLabel(
            top_row,
            text=title.upper(),
            font=("Segoe UI", 10, "bold"),
            text_color=MUTED,
        )
        self.title_label.pack(side="left")

        self.value_label = ctk.CTkLabel(
            self,
            text=value,
            font=("Segoe UI", 16, "bold"),
            text_color=TEXT_MAIN,
            anchor="w",
        )
        self.value_label.pack(fill="x", padx=16, pady=(2, 2))

        self.subtitle_label = ctk.CTkLabel(
            self,
            text=subtitle,
            font=("Segoe UI", 10),
            text_color=MUTED_LIGHT,
            anchor="w",
        )
        self.subtitle_label.pack(fill="x", padx=16, pady=(0, 14))

    def update_card(self, value: str | None = None, subtitle: str | None = None, accent: str | None = None):
        if value is not None:
            self.value_label.configure(text=value)
        if subtitle is not None:
            self.subtitle_label.configure(text=subtitle)
        if accent is not None:
            self.icon_label.configure(text_color=accent)


class NavTabButton(ctk.CTkButton):
    """Top navigation tab button with active pill indicator."""

    def __init__(
        self,
        parent,
        text: str,
        command: Callable[[], None],
        icon: str = "",
        is_active: bool = False,
        **kwargs,
    ):
        display_text = f"{icon}  {text}" if icon else text
        super().__init__(
            parent,
            text=display_text,
            command=command,
            height=34,
            corner_radius=8,
            font=("Segoe UI", 12, "bold" if is_active else "normal"),
            fg_color=CYAN_GLOW if is_active else "transparent",
            text_color=CYAN if is_active else MUTED_LIGHT,
            hover_color=CARD_LIGHT,
            border_width=1 if is_active else 0,
            border_color=BORDER_FOCUS if is_active else CARD,
            **kwargs,
        )
        self.is_active = is_active

    def set_active(self, active: bool):
        self.is_active = active
        self.configure(
            fg_color=CYAN_GLOW if active else "transparent",
            text_color=CYAN if active else MUTED_LIGHT,
            border_width=1 if active else 0,
            border_color=BORDER_FOCUS if active else CARD,
            font=("Segoe UI", 12, "bold" if active else "normal"),
        )


class AvatarWidget(ctk.CTkFrame):
    """Interactive avatar widget that dynamically fetches Minecraft skin head or renders default."""

    def __init__(self, parent, size: int = 40, **kwargs):
        super().__init__(
            parent,
            width=size,
            height=size,
            fg_color=CARD_LIGHT,
            border_color=BORDER,
            border_width=1,
            corner_radius=8,
            **kwargs,
        )
        self.pack_propagate(False)
        self.size = size
        self._current_user = ""
        self._ui_root = self.winfo_toplevel()
        self._avatar_timer = None
        self._cache_dir = os.path.join(LOGS_DIR, "avatars")
        os.makedirs(self._cache_dir, exist_ok=True)

        self.img_label = ctk.CTkLabel(
            self,
            text="👤",
            font=("Segoe UI", 16),
            text_color=CYAN,
        )
        self.img_label.pack(expand=True, fill="both")

    def load_avatar(self, username: str):
        username = username.strip()
        if username == self._current_user:
            return
        self._current_user = username
        if self._avatar_timer is not None:
            self.after_cancel(self._avatar_timer)
            self._avatar_timer = None
        if not username or len(username) < 3:
            self.img_label.configure(text="👤", image=None)
            return
        self._avatar_timer = self.after(300, lambda: self._fetch_avatar(username))

    def _fetch_avatar(self, username):
        self._avatar_timer = None

        def fetch_task():
            cache_file = os.path.join(self._cache_dir, f"{username}.png")
            try:
                if os.path.exists(cache_file):
                    with Image.open(cache_file) as source:
                        image = source.convert("RGBA")
                else:
                    url = f"https://mc-heads.net/avatar/{username}/{self.size}"
                    with requests.get(url, timeout=(4, 8)) as response:
                        response.raise_for_status()
                        if len(response.content) > 2 * 1024**2:
                            raise ValueError("Avatar too large")
                        with Image.open(io.BytesIO(response.content)) as source:
                            image = source.convert("RGBA")
                        with open(cache_file, "wb") as output:
                            output.write(response.content)
                image = image.resize((self.size - 6, self.size - 6), Image.Resampling.NEAREST)
                self._ui_root.after(0, lambda: self._apply_ctk_image(image, username))
            except Exception:
                self._ui_root.after(0, lambda: self._apply_default_head(username))

        threading.Thread(target=fetch_task, daemon=True).start()

    def _apply_ctk_image(self, pil_image: Image.Image, username=None):
        # Invoked on the root's UI dispatcher: CTkImage creates Tk resources.
        if not self.winfo_exists() or username is not None and username != self._current_user:
            return
        try:
            self._avatar_image = ctk.CTkImage(
                light_image=pil_image, dark_image=pil_image, size=(self.size - 6, self.size - 6)
            )
            self.img_label.configure(text="", image=self._avatar_image)
        except Exception:
            self._apply_default_head(username)

    def _apply_default_head(self, username=None):
        if self.winfo_exists() and (username is None or username == self._current_user):
            self.img_label.configure(text="🎮", image=None)
