"""Navigation must preserve content and leave Tk time to process user input."""

import queue
import threading
from types import SimpleNamespace

import customtkinter as ctk
import pytest

import main
from src.hexlauncher.i18n import tr
from src.hexlauncher.utils.ui_tasks import render_in_batches
from src.hexlauncher.widgets import ResponsiveScrollableFrame
from tests.test_modrinth_view import pump


def test_navigation_preserves_pages_results_inputs_and_scroll(app_root, monkeypatch):
    root = app_root
    view = root.modrinth_view
    view._clear()
    for number in range(15):
        ctk.CTkLabel(view.results_scroll, text=f"Result {number}").pack(pady=10)
    view.search_var.set("keep this search")
    root.update_idletasks()
    view._results_viewport._parent_canvas.yview_moveto(0.5)
    original_scroll = view._results_viewport._parent_canvas.yview()
    original_cards = view.results_scroll.winfo_children()
    generation = view._search_generation

    def unnecessary_work(*args, **kwargs):
        pytest.fail("Navigation must not scan/retranslate/rebuild or start background work")

    monkeypatch.setattr(main, "refresh_language", unnecessary_work)
    monkeypatch.setattr(root.home_view, "refresh_stats", unnecessary_work)
    monkeypatch.setattr(root.resource_packs_view, "refresh_context", unnecessary_work)
    monkeypatch.setattr(threading.Thread, "start", unnecessary_work)
    monkeypatch.setattr(main.subprocess, "Popen", unnecessary_work)
    for name in ["home", "mods", "textures", "server", "settings"] * 10:
        root.nav_tabs[name].invoke()
        assert root.current_view == name
        assert sum(button.is_active for button in root.nav_tabs.values()) == 1
    root.update_idletasks()
    assert view.results_scroll.winfo_children() == original_cards
    assert view._results_viewport._parent_canvas.yview() == original_scroll
    assert view.search_var.get() == "keep this search"
    assert view._search_generation == generation
    assert all(page.winfo_manager() == "grid" for page in root.views.values())


def test_repeated_filter_refresh_keeps_results_but_changed_context_invalidates(app_root):
    view = app_root.modrinth_view
    view.update_filter_badge()
    ctk.CTkLabel(view.results_scroll, text="Keep this result").pack()
    cards = view.results_scroll.winfo_children()
    generation = view._search_generation
    view.update_filter_badge()
    assert view.results_scroll.winfo_children() == cards
    assert view._search_generation == generation
    previous = view.kind_var.get()
    try:
        view.kind_var.set("Modpacks" if previous == "Mods" else "Mods")
        view.update_filter_badge()
        assert not view.results_scroll.winfo_children()
        assert view._search_generation == generation + 1
    finally:
        view.kind_var.set(previous)
        view.update_filter_badge()


@pytest.mark.parametrize("section", ["mods", "textures"])
def test_navigation_during_search_keeps_response_and_yields_between_cards(app_root, monkeypatch, section):
    root = app_root
    view = root.views[section]
    monkeypatch.setattr(root.loader_var, "get", lambda: "Fabric")
    monkeypatch.setattr(root.version_var, "get", lambda: "1.21.1")
    gate, entered = threading.Event(), threading.Event()
    rendered, navigation = [], []

    def search(*args, **kwargs):
        entered.set()
        gate.wait(2)
        return [{"title": str(i)} for i in range(20)]

    def render(hit, *args):
        rendered.append(hit["title"])
        if len(rendered) == 1:
            root.after(0, lambda: (root.switch_view("settings"), navigation.append(len(rendered))))

    monkeypatch.setattr(view.client, "search_mods", search)
    renderer = "_render_mod_card" if section == "mods" else "_render_card"
    monkeypatch.setattr(view, renderer, render)
    view.search_var.set("example")
    root.switch_view(section)
    view.do_search()
    try:
        assert entered.wait(1)
        root.switch_view("home")
        root.switch_view(section)
    finally:
        gate.set()
    pump(root, lambda: len(rendered) == 20)
    assert navigation and navigation[0] <= 2
    assert rendered == [str(i) for i in range(20)]


def test_obsolete_render_batch_is_cancelled(app_root):
    rendered = []
    valid = [True]
    render_in_batches(app_root, range(20), rendered.append, lambda: valid[0])
    assert len(rendered) <= 2
    valid[0] = False
    count = len(rendered)
    finished = []
    app_root.after(30, lambda: finished.append(True))
    pump(app_root, lambda: bool(finished))
    assert len(rendered) == count


@pytest.mark.parametrize("section", ["mods", "textures"])
def test_replaced_results_release_widgets_without_recreating_scroll_bindings(app_root, section):
    view = app_root.views[section]
    previous = view.results_scroll
    for i in range(20):
        ctk.CTkLabel(previous, text=f"Old {i}").pack()
    viewport = view._results_viewport
    bindings = app_root.bind_all("<MouseWheel>")
    view._clear()
    assert view.results_scroll is not previous
    assert previous.winfo_manager() == ""
    assert not view.results_scroll.winfo_children()
    assert view._results_viewport is viewport
    assert app_root.bind_all("<MouseWheel>") == bindings
    pump(app_root, lambda: not previous.winfo_exists())
    assert viewport.winfo_children() == [view.results_scroll]


def test_callback_burst_yields_and_remains_fifo(app_root, monkeypatch):
    root = app_root
    pending = queue.Queue()
    called = []
    clock = [0.0]
    for i in range(30):
        def callback(index=i):
            called.append(index)
            clock[0] += .003  # Deterministic work cost, without a real sleep.
        pending.put(callback)
    monkeypatch.setattr(root, "queue", pending)
    monkeypatch.setattr(main, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    root.after_cancel(root._queue_after_id)
    root._process_queue()
    assert called == [0, 1, 2]
    assert pending.qsize() == 27
    # Let an input event run before the remaining callbacks, then drain in order.
    clicked = []
    root.after(0, lambda: (root.switch_view("textures"), clicked.append(len(called))))
    pump(root, lambda: len(called) == 30)
    # Other already-due timers may drain another bounded slice before this
    # event. The contract is that input runs before the burst is exhausted,
    # not that Tk must choose this event ahead of every other timer.
    assert len(clicked) == 1 and 3 <= clicked[0] < 30
    assert called == list(range(30))


def test_hidden_status_is_translated_without_full_tree_scan(app_root, monkeypatch):
    monkeypatch.setattr(main, "refresh_language", lambda *args: pytest.fail("Unexpected full translation"))
    app_root.modrinth_view._status("Selecciona una versión de Minecraft.")
    app_root.switch_view("mods")
    assert app_root.modrinth_view.status_label.cget("text") == tr("Selecciona una versión de Minecraft.")


def test_scrollbar_coalesces_layout_updates_and_cancels_on_destroy(app_root, monkeypatch):
    frame = ResponsiveScrollableFrame(app_root)
    app_root.update_idletasks()
    idle_events = []
    app_root.after_idle(lambda: idle_events.append(True))
    frame._scrollbar.set(.1, .6)
    assert not idle_events  # Drawing a thumb must not pump the whole Tk tree.
    if frame._scrollbar_after_id is not None:
        frame.after_cancel(frame._scrollbar_after_id)
        frame._scrollbar_after_id = None
    called = []
    monkeypatch.setattr(frame._scrollbar, "set", lambda *values: called.append(values))
    for i in range(30):
        frame._queue_scrollbar(i / 100, .7)
    assert not called  # Never re-enter layout synchronously from yscrollcommand.
    pump(app_root, lambda: bool(called))
    assert called == [(.29, .7)]
    frame._queue_scrollbar(.3, .8)
    pending = frame._scrollbar_after_id
    frame.destroy()
    assert pending not in app_root.tk.call("after", "info")
