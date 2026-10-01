"""Validated, atomic settings persistence for HexLauncher."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import tempfile
from typing import Any

logger = logging.getLogger(__name__)
DEFAULTS: dict[str, Any] = {
    "language": "en",
    "username": "",
    "last_version": "",
    "last_loader": "Vanilla",
    "ram_gb": 4,
    "jvm_args": ["-Xmx4G", "-Xms2G"],
    "custom_jvm_args": "",
    "custom_java_path": "",
    "close_on_launch": False,
    "active_instance_dir": "",
    "window_geometry": "1000x680",
}


def parse_jvm_args(command: str) -> list[str]:
    """Split Windows command-line arguments, preserving paths and quoted spaces."""
    args: list[str] = []
    current: list[str] = []
    quoted = False
    started = False
    index = 0
    while index < len(command):
        char = command[index]
        if char in " \t" and not quoted:
            if started:
                args.append("".join(current))
                current = []
                started = False
            index += 1
            continue
        started = True
        if char == "\\":
            start = index
            while index < len(command) and command[index] == "\\":
                index += 1
            count = index - start
            if index < len(command) and command[index] == '"':
                current.extend("\\" * (count // 2))
                if count % 2:
                    current.append('"')
                else:
                    quoted = not quoted
                index += 1
            else:
                current.extend("\\" * count)
            continue
        if char == '"':
            quoted = not quoted
        else:
            current.append(char)
        index += 1
    if quoted:
        raise ValueError("Los argumentos JVM contienen comillas sin cerrar")
    if started:
        args.append("".join(current))
    return args


def _valid(key: str, value: Any) -> bool:
    default = DEFAULTS[key]
    if type(value) is not type(default):
        return False
    if isinstance(value, str) and "\x00" in value:
        return False
    if key == "ram_gb":
        return 1 <= value <= 32
    if key == "language":
        return value in {"en", "es"}
    if key == "last_loader":
        return value in {"Vanilla", "Fabric", "Forge", "NeoForge"}
    if key == "window_geometry":
        match = re.fullmatch(r"(\d{3,5})x(\d{3,5})(?:[+-]\d+[+-]\d+)?", value)
        return bool(match and 320 <= int(match[1]) <= 16384 and 240 <= int(match[2]) <= 16384)
    if key == "jvm_args":
        return all(isinstance(arg, str) and "\x00" not in arg for arg in value)
    if key == "custom_jvm_args":
        try:
            parse_jvm_args(value)
        except ValueError:
            return False
    return True


class Settings:
    def __init__(self, base_path: str):
        self.path = os.path.join(base_path, "settings.json")
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        self.data = copy.deepcopy(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as stream:
                stored = json.load(stream)
            if isinstance(stored, dict):
                for key in DEFAULTS:
                    if key in stored and _valid(key, stored[key]):
                        self.data[key] = copy.deepcopy(stored[key])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError):
            logger.warning("Unable to read settings; using defaults", exc_info=True)

    def save(self) -> bool:
        """Replace the saved file only after a complete, flushed write."""
        temporary = None
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=os.path.dirname(self.path),
                prefix=".settings-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(self.data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return True
        except (OSError, TypeError, ValueError):
            logger.error("Unable to save settings", exc_info=True)
            return False
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    logger.warning("Unable to remove temporary settings file", exc_info=True)

    def get(self, key: str) -> Any:
        return copy.deepcopy(self.data.get(key, DEFAULTS.get(key)))

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS or not _valid(key, value):
            raise ValueError(f"Invalid setting: {key}")
        self.data[key] = copy.deepcopy(value)

    def get_effective_jvm_args(self) -> list[str]:
        ram_gb = self.get("ram_gb")
        args = [f"-Xmx{ram_gb}G", f"-Xms{max(1, ram_gb // 2)}G"]
        args.extend(parse_jvm_args(self.get("custom_jvm_args")))
        return args
