import pytest


@pytest.fixture(scope="module")
def launcher_app(app_root):
    return app_root


def test_launcher_initialization(launcher_app):
    assert launcher_app.winfo_exists()
    assert launcher_app.title() == "HexLauncher"
    assert "home" in launcher_app.views
    assert "mods" in launcher_app.views
    assert "settings" in launcher_app.views


def test_view_switching(launcher_app):
    launcher_app.switch_view("mods")
    assert launcher_app.current_view == "mods"
    assert launcher_app.nav_tabs["mods"].is_active
    assert not launcher_app.nav_tabs["home"].is_active

    launcher_app.switch_view("settings")
    assert launcher_app.current_view == "settings"
    assert launcher_app.nav_tabs["settings"].is_active

    launcher_app.switch_view("home")
    assert launcher_app.current_view == "home"
    assert launcher_app.nav_tabs["home"].is_active


def test_bottom_bar_validation(launcher_app):
    bar = launcher_app.bottom_bar

    # Empty username -> invalid
    bar.username_var.set("")
    assert not bar._validate_username()
    assert bar.play_button.cget("state") == "disabled"

    # Valid username -> valid
    bar.username_var.set("Alex_Pro")
    assert bar._validate_username()
    assert bar.play_button.cget("state") == "normal"

    # Invalid characters -> invalid
    bar.username_var.set("invalid#user!")
    assert not bar._validate_username()
    assert bar.play_button.cget("state") == "disabled"


def test_bottom_bar_running_state_toggle(launcher_app):
    bar = launcher_app.bottom_bar
    bar.set_running_state(True)
    assert "DETENER" in bar.play_button.cget("text")
    assert bar.play_button.cget("state") == "normal"

    bar.set_running_state(False)
    assert "ENTRAR AL JUEGO" in bar.play_button.cget("text") or "JUGAR" in bar.play_button.cget("text")


def test_installed_status_update(launcher_app):
    bar = launcher_app.bottom_bar
    bar.update_installed_status(True, "1.21")
    assert "Instalado" in bar.installed_badge.label.cget("text")

    bar.update_installed_status(False, "1.21.4")
    assert "Descarga" in bar.installed_badge.label.cget("text")
