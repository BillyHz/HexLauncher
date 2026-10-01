"""English/Spanish UI translations, including already displayed status messages."""

from __future__ import annotations

import re
import string
import tkinter
from functools import lru_cache

from src.hexlauncher.translations_home import EN as HOME
from src.hexlauncher.translations_mods import EN as MODS

EN = {
    "Inicio": "Home",
    "🚀  Inicio": "🚀  Home",
    "⚙️  Ajustes": "⚙️  Settings",
    "Ajustes": "Settings",
    "Idioma": "Language",
    "⚡ ASIGNACIÓN DE MEMORIA RAM": "⚡ RAM ALLOCATION",
    "RAM del Sistema: {ram} GB": "System RAM: {ram} GB",
    "Recomendado: 4 GB a 6 GB para la mayoría de versiones y modpacks.":
        "Recommended: 4–6 GB for most versions and modpacks.",
    "☕ ENTORNO JAVA RUNTIME": "☕ JAVA RUNTIME",
    "Java Integrado: Adoptium OpenJDK 21 (Descarga automática)":
        "Bundled Java: Adoptium OpenJDK 21 (Automatic download)",
    "Examinar…": "Browse…",
    "Si se deja vacío, HexLauncher utiliza automáticamente Java 21 LTS de alto rendimiento.":
        "Leave blank to automatically use Java 21 LTS.",
    "⚙️ ARGUMENTOS JVM ADICIONALES": "⚙️ ADDITIONAL JVM ARGUMENTS",
    "Ejemplo: -XX:+UseG1GC -XX:+ParallelRefProcEnabled": "Example: -XX:+UseG1GC -XX:+ParallelRefProcEnabled",
    "Los argumentos de memoria (-Xmx y -Xms) se configuran automáticamente arriba.":
        "Memory arguments (-Xmx and -Xms) are configured automatically above.",
    "🖥️ COMPORTAMIENTO DEL LANZADOR": "🖥️ LAUNCHER BEHAVIOR",
    "Ocultar el lanzador automáticamente al iniciar Minecraft":
        "Automatically hide the launcher when Minecraft starts",
    "Guardar Cambios": "Save Changes",
    "⚠ Asignación baja: Minecraft moderno puede presentar tirones.":
        "⚠ Low allocation: modern Minecraft may stutter.",
    "✓ Rango ideal para rendimiento fluido y modpacks estándar.":
        "✓ Ideal range for smooth performance and standard modpacks.",
    "Alto: Asegúrate de tener suficiente RAM libre en Windows.": "High: ensure Windows has enough free RAM.",
    "Seleccionar ejecutable java.exe": "Select java.exe executable",
    "No se pudieron guardar los ajustes.": "Could not save settings.",
    "✓ Ajustes guardados correctamente": "✓ Settings saved successfully",
    "Listo para jugar": "Ready to play",
    "Deteniendo Minecraft…": "Stopping Minecraft…",
    "Espera a que termine la operación actual.": "Wait for the current operation to finish.",
    "⚠ Ingresa un apodo válido (3-16 caracteres alfanuméricos).":
        "⚠ Enter a valid nickname (3–16 letters or numbers).",
    "⚠ Selecciona una versión válida.": "⚠ Select a valid version.",
    "No se encontraron versiones": "No versions found",
    "No hay versiones compatibles con {loader}.": "No compatible versions for {loader}.",
    "Instalando archivos de Minecraft {version}…": "Installing Minecraft {version} files…",
    "Instalando {loader} para MC {version}…": "Installing {loader} for MC {version}…",
    "Sincronizando mods para {version}…": "Synchronizing mods for {version}…",
    "Iniciando {version}…": "Starting {version}…",
    "Minecraft {version} en ejecución.": "Minecraft {version} is running.",
    "Descargando Java 21…": "Downloading Java 21…",
    "Extrayendo Java 21…": "Extracting Java 21…",
    "🔍 Filtrar versión…": "🔍 Filter versions…",
    "{count} versiones": "{count} versions",
    "{count} de {total} versiones": "{count} of {total} versions",
    "No hay versiones coincidentes": "No matching versions",
    "Error obteniendo versiones: {message}": "Could not fetch versions: {message}",
    "Filtrando versiones para {loader}…": "Filtering versions for {loader}…",
    "Error en filtro: {message}": "Filter error: {message}",
    "No se pudo detener Minecraft: {message}": "Could not stop Minecraft: {message}",
}
_language = "en"


def set_language(language: str) -> None:
    global _language
    if language not in {"en", "es"}:
        raise ValueError("Unsupported language")
    _language = language
    translate_displayed.cache_clear()


def tr(text: str) -> str:
    if _language == "es":
        return text
    return EN.get(text, HOME.get(text, MODS.get(text, text)))


@lru_cache(maxsize=1024)
def translate_displayed(text: str) -> str:
    """Translate literal or formatted catalog text in either direction."""
    catalog = EN | HOME | MODS
    catalog |= {spanish.upper(): english.upper() for spanish, english in catalog.items()}
    for spanish, english in catalog.items():
        source, target = (spanish, english) if _language == "en" else (english, spanish)
        if text == source:
            return target
    for spanish, english in catalog.items():
        source, target = (spanish, english) if _language == "en" else (english, spanish)
        if "{" not in source:
            continue
        pattern, fields = "", []
        for literal, field, _, _ in string.Formatter().parse(source):
            pattern += re.escape(literal)
            if field is not None:
                fields.append(field)
                pattern += "(.*?)"
        match = re.fullmatch(pattern, text, flags=re.DOTALL)
        if match:
            return target.format(**dict(zip(fields, match.groups(), strict=True)))
    return text


def refresh_language(widget) -> None:
    """Update existing widgets on Tk's thread without losing their state."""
    for option in ("text", "placeholder_text"):
        try:
            value = widget.cget(option)
        except (ValueError, AttributeError, tkinter.TclError):
            continue
        if isinstance(value, str):
            translated = translate_displayed(value)
            if translated != value:
                widget.configure(**{option: translated})
    for child in widget.winfo_children():
        refresh_language(child)
