"""Pytest configuration and environment setup."""

import os
import sys

import pytest


def _setup_tcl():
    tcl_base = os.path.normpath(os.path.join(sys.base_prefix, "tcl"))
    if os.path.isdir(tcl_base):
        tcl_lib = os.path.normpath(os.path.join(tcl_base, "tcl8.6"))
        tk_lib = os.path.normpath(os.path.join(tcl_base, "tk8.6"))
        if os.path.isdir(tcl_lib):
            os.environ["TCL_LIBRARY"] = tcl_lib
        if os.path.isdir(tk_lib):
            os.environ["TK_LIBRARY"] = tk_lib


_setup_tcl()


def pytest_configure(config):
    _setup_tcl()


@pytest.fixture(scope="session")
def app_root(tmp_path_factory):
    import customtkinter as ctk

    import main
    from main import HexLauncher
    from src.hexlauncher.utils.settings import Settings
    from src.hexlauncher.views import modrinth_view
    from src.hexlauncher.widgets import AvatarWidget

    _setup_tcl()
    ctk.set_appearance_mode("dark")
    temporary = tmp_path_factory.mktemp("launcher")
    patch = pytest.MonkeyPatch()
    patch.setattr(main, "Settings", lambda _: Settings(str(temporary)))
    patch.setattr(main, "MC_DIR", str(temporary / "minecraft"))
    patch.setattr(main, "MODS_DIR", str(temporary / "mods"))
    patch.setattr(main, "BASE_PATH", str(temporary))
    patch.setattr(modrinth_view, "BASE_PATH", str(temporary))
    patch.setattr(HexLauncher, "_fetch_versions", lambda self, *args: None)
    patch.setattr(AvatarWidget, "load_avatar", lambda self, username: None)
    root = None
    try:
        root = HexLauncher()
        root.withdraw()
        yield root
    finally:
        if root is not None:
            root.destroy()
        patch.undo()
