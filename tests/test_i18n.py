"""Language persistence and live UI switching regressions."""

import pytest

from src.hexlauncher.i18n import set_language, tr, translate_displayed
from src.hexlauncher.utils.settings import Settings


def test_language_defaults_to_english_and_persists(tmp_path):
    settings = Settings(str(tmp_path))
    assert settings.get("language") == "en"
    settings.set("language", "es")
    assert settings.save()
    assert Settings(str(tmp_path)).get("language") == "es"
    with pytest.raises(ValueError):
        settings.set("language", "fr")


def test_dynamic_translation_round_trip():
    try:
        set_language("en")
        assert tr("Inicio") == "Home"
        english = translate_displayed("Filtrando versiones para Fabric…")
        assert english == "Filtering versions for Fabric…"
        set_language("es")
        assert translate_displayed(english) == "Filtrando versiones para Fabric…"
        assert tr("Inicio") == "Inicio"
    finally:
        set_language("en")


def test_switch_updates_live_ui_without_losing_inputs(app_root):
    root = app_root
    settings_view = root.settings_view
    settings_view.jvm_args_var.set("-Dexample=keep")
    original_version = root.version_var.get()
    try:
        assert root.change_language("es")
        assert settings_view.language_var.get() == "es"
        assert "Inicio" in root.nav_tabs["home"].cget("text")
        assert root.change_language("en")
        assert "Home" in root.nav_tabs["home"].cget("text")
        assert settings_view.jvm_args_var.get() == "-Dexample=keep"
        assert root.version_var.get() == original_version
    finally:
        root.change_language("en")


def test_failed_language_save_preserves_previous_language(app_root, monkeypatch):
    root = app_root
    monkeypatch.setattr(root.settings, "save", lambda: False)
    assert not root.change_language("es")
    assert root.settings.get("language") == "en"
    assert tr("Inicio") == "Home"
