import customtkinter as ctk

from src.hexlauncher.palette import CARD, CYAN, SUCCESS
from src.hexlauncher.widgets import (
    AvatarWidget,
    Badge,
    CTkScrollableDropdown,
    NavTabButton,
    StatCard,
    VersionSelector,
)


def test_badge_creation_and_update(app_root):
    badge = Badge(app_root, text="Test Badge", fg_color=CARD, text_color=CYAN)
    assert badge.label.cget("text") == "Test Badge"
    badge.configure_badge(text="Updated", text_color=SUCCESS)
    assert badge.label.cget("text") == "Updated"


def test_stat_card_creation_and_update(app_root):
    card = StatCard(
        app_root,
        icon="🚀",
        title="Status",
        value="Ready",
        subtitle="Minecraft 1.21",
        accent_color=CYAN,
    )
    assert card.title_label.cget("text") == "STATUS"
    assert card.value_label.cget("text") == "Ready"
    assert card.subtitle_label.cget("text") == "Minecraft 1.21"

    card.update_card(value="Running", subtitle="Playing with Fabric")
    assert card.value_label.cget("text") == "Running"
    assert card.subtitle_label.cget("text") == "Playing with Fabric"


def test_nav_tab_button(app_root):
    clicked = []
    btn = NavTabButton(
        app_root,
        text="Inicio",
        icon="🚀",
        command=lambda: clicked.append(True),
        is_active=False,
    )
    assert not btn.is_active
    btn.set_active(True)
    assert btn.is_active
    btn.invoke()
    assert len(clicked) == 1


def test_avatar_widget_offline_default(app_root):
    avatar = AvatarWidget(app_root, size=38)
    assert avatar.size == 38
    avatar.load_avatar("Steve")
    assert avatar.winfo_exists()


def test_scrollable_dropdown_creation_and_filtering(app_root):
    combo = ctk.CTkComboBox(
        app_root, values=["1.21.4", "1.20.1", "1.16.5", "1.12.2", "1.8.9", "1.7.10", "1.21.1"]
    )
    selected = []
    dropdown = CTkScrollableDropdown(
        attach_to=combo,
        values=["1.21.4", "1.20.1", "1.16.5", "1.12.2", "1.8.9", "1.7.10", "1.21.1"],
        command=lambda val: selected.append(val),
    )
    assert dropdown.winfo_exists()
    assert len(dropdown.all_values) == 7
    # Test filter
    dropdown.search_var.set("1.21")
    assert len(dropdown.buttons) == 2  # 1.21.4 and 1.21.1
    dropdown.destroy()


def test_version_selector_interaction(app_root):
    var = ctk.StringVar(value="1.21.4")
    selected = []
    selector = VersionSelector(
        app_root,
        variable=var,
        values=["1.21.4", "1.20.1", "1.16.5"],
        command=lambda val: selected.append(val),
    )
    selector.pack()
    app_root.update_idletasks()

    assert selector.get() == "1.21.4"

    # Toggle open
    selector.toggle_dropdown()
    app_root.update_idletasks()
    assert selector._active_dropdown is not None
    assert selector._active_dropdown.winfo_exists()

    # Select value
    selector._active_dropdown._on_select("1.20.1")
    app_root.update_idletasks()

    assert selector.get() == "1.20.1"
    assert len(selected) == 1
    assert selected[0] == "1.20.1"
    assert selector._active_dropdown is None
