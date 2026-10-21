"""Small, cancellable pieces of Tk work so input can run between cards."""

from __future__ import annotations

import time

import customtkinter as ctk


def render_in_batches(launcher, items, render, is_current, on_complete=None):
    """Call on Tk's thread; stop when a search/context changes or Tk closes."""
    pending = iter(items)

    def batch():
        if launcher._is_destroyed or not is_current():
            return
        deadline = time.perf_counter() + 0.008
        for _ in range(2):
            try:
                item = next(pending)
            except StopIteration:
                if on_complete is not None:
                    on_complete()
                return
            render(item)
            if time.perf_counter() >= deadline:
                break
        launcher.after(10, batch)

    batch()


def replace_results_content(launcher, viewport, previous=None):
    """Detach old results immediately, then release their Tk widgets in batches.

    Keep the scrollable frame itself: recreating it would register more global
    mouse-wheel bindings. The lightweight content frame owns only the cards.
    """
    if previous is not None:
        previous.pack_forget()
    content = ctk.CTkFrame(viewport, fg_color="transparent", corner_radius=0, height=1)
    content.pack(fill="x", expand=True)
    if previous is not None:
        viewport._parent_canvas.yview_moveto(0)
        launcher.after(10, lambda: render_in_batches(
            launcher, previous.winfo_children(), lambda widget: widget.destroy(),
            previous.winfo_exists, on_complete=previous.destroy,
        ) if previous.winfo_exists() else None)
    return content
