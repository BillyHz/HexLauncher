"""HexLauncher filesystem paths.

Resolves the base path for both frozen (.exe via PyInstaller) and
script-mode executions, then defines the canonical HexLauncher directories
(Minecraft data, mods, JDK, logs, icon) and ensures the on-disk layout
is created at import time.
"""

import os
import sys

# Base paths for script and bundled execution.
if getattr(sys, "frozen", False):
    BASE_PATH = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_PATH)
else:
    BASE_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    BUNDLE_DIR = BASE_PATH


def resource_path(rel: str) -> str:
    return os.path.join(BUNDLE_DIR, rel)


# Application directories.
MC_DIR = os.path.join(BASE_PATH, "HexFiles")
MODS_DIR = os.path.join(BASE_PATH, "HexMods")
JAVA_DIR = os.path.join(BASE_PATH, "HexJDK")
JAVA_BIN = os.path.join(JAVA_DIR, "bin", "java.exe")
ICON_NAME = resource_path("Hex.ico")

# Ensure HexMods exists with subfolders for organization
os.makedirs(MODS_DIR, exist_ok=True)
for loader_name in ["Fabric", "Forge", "NeoForge"]:
    os.makedirs(os.path.join(MODS_DIR, loader_name), exist_ok=True)

# Logs directory (next to .exe when frozen, next to .py otherwise)
LOGS_DIR = os.path.join(BASE_PATH, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
