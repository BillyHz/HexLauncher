# HexLauncher — Exploración del proyecto y puntos de mejora

> Repositorio: <https://github.com/BillyHz/HexLauncher>
> Clonado en: `C:\Proyectos\HexLauncher\HexLauncher`
> Snapshot del repo: `main` @ `b5104f2` (Fri Jul 24 2026 09:08 -0600)
> Stars / issues: 2 ⭐ · 0 issues abiertos · 0 PRs · licencia GPL-3.0

## 1. Visión general del proyecto

**HexLauncher** es un launcher *no-premium* (cuenta offline) para Minecraft, hecho en Python con GUI CustomTkinter y empaquetado con PyInstaller. Se posiciona como alternativa "ligera y open-source" con estética *cyberpunk cyan* y soporte de primera clase para mod loaders (Fabric / Forge / NeoForge).

### Stack y dependencias

| Capa | Tecnología |
|---|---|
| Lenguaje | Python **3.14** (pinneado en `.python-version`) |
| GUI | `customtkinter==5.2.2`, `darkdetect==0.8.0` |
| Minecraft API | `minecraft-launcher-lib==8.0` |
| HTTP | `requests==2.34.2` |
| Java | Temurin JDK 21.0.2+13 (auto-descargado desde GitHub) |
| Packaging | PyInstaller 6.10.0 |

### Estructura del repo

```
HexLauncher/
├── main.py              # 703 líneas — UI + lógica + I/O + threading
├── build.py             # Wrapper de PyInstaller (26 líneas)
├── hexlauncher.spec     # Configuración de PyInstaller
├── Hex.ico              # Ícono de la app
├── requirements.txt     # Deps runtime
├── requirements-dev.txt # PyInstaller
├── BUILD.md             # Notas de build + troubleshooting
├── README.md            # Onboarding + features + roadmap
├── LICENSE              # GPL-3.0
└── .gitignore
```

**No existe**: carpeta de tests, workflows de CI, archivos `ANTIVIRUS.md`, `MIGRATION.md`, `sign.bat`, `build.bat` que **sí se mencionan** en `BUILD.md` (404s de documentación).

---

## 2. Lo que está bien hecho ✅

- **Licencia clara** (GPL-3.0) y badges visibles — buena higiene para OSS.
- **README completo**: features, quick-start, instrucciones de mods, build, roadmap y contactos.
- **Rutas con `sys._MEIPASS`**: el ejecutable congelado funciona bien con su bundle (`resource_path()`).
- **Aislamiento por carpetas**: `HexFiles/`, `HexMods/`, `HexJDK/` viven al lado del `.exe` — instalación "portable".
- **Organización de mods por loader + versión** (`HexMods/Fabric/1.21/...`) — limpia y descubrible.
- **Cyberpunk UI** con paleta de constantes centralizada y separación de tarjetas.
- **`shim de `after()` cross-thread`** (línea 265) — evita el clásico `RuntimeError: main thread is not in main loop` cuando un callback de worker llama `self.after(...)`.
- **Versión filtrada por loader** — solo muestra versiones de MC compatibles con el loader seleccionado.
- **`.gitignore` muy completo** para repo público (secretos, bytecode, venvs, builds, IDE junk, migración futura a Tauri/Electron).

---

## 3. Puntos de mejora (ordenados por impacto)

### 🔴 Críticos (afectan seguridad, estabilidad o UX de primer uso)

#### 3.1 — Sin verificación de integridad del JDK descargado
`main.py:572-585` descarga `OpenJDK21U-jdk_x64_windows_hotspot_21.0.2_13.zip` directo de GitHub **sin checksum ni firma**. Si el endpoint se compromete (mirror malicioso, MITM en una red corporativa, etc.), el launcher ejecuta binarios arbitrarios como `HexJDK/bin/java.exe` y los lanza como subproceso.

**Mejoras**:
- Verificar SHA-256 del ZIP contra el `.sha256.txt` publicado por Adoptium.
- Verificar la firma GPG de la release (`adoptium/temurin21-binaries` las publica).
- Validar que el ejecutable extraído sea realmente `java.exe` antes de continuar.

#### 3.2 — JDK hardcodeado a una versión puntual
`main.py:573-574` apunta a `jdk-21.0.2+13`. Esa release ya envejece y Adoptium puede mover o renombrar el asset. **El launcher se rompe silenciosamente** cuando eso pase.

**Mejoras**:
- Consultar la API de Adoptium (`/api/v3/binary/latest/...`) o `minecraft_launcher_lib`'s helper para elegir la build LTS actual.
- Cachear la versión resuelta en `settings.json` y permitir override manual.

#### 3.3 — Manejo de excepciones demasiado ancho y silencioso
Hay `except Exception: pass` en lugares críticos:

```python
# main.py:521
try: os.remove(path)
except Exception: pass

# main.py:527
try: shutil.copy2(src, dst)
except Exception: pass

# main.py:244
try: self.iconbitmap(ICON_NAME)
except Exception: pass
```

Si `_sync_mods` falla porque el disco está lleno o un mod está bloqueado por otro proceso, **el usuario no se entera** y el juego arranca sin sus mods. Eso es un soporte-ticket esperando a suceder.

**Mejoras**:
- Loggear a `logs/hexlauncher.log` con `logging` (no print/traceback sueltos).
- Mostrar al usuario un dialog modal cuando un sync falla, con la cantidad de mods omitidos.

#### 3.4 — Sin validación de entrada en username
`main.py:604` toma `self.username_input.get().strip()` y lo manda directo a `minecraft_launcher_lib.command.get_minecraft_command`. Mojang rechaza nombres >16 chars o con caracteres no válidos (en modo offline), pero también es vector de:
- inyección de argumentos si se permite newline o `--` (la lib lo sanitiza parcialmente, pero no confíes).
- log de Mojang con tu "username".

**Mejoras**:
- Validar con regex `^[A-Za-z0-9_]{3,16}$` antes de habilitar PLAY.
- Trim + fallback visual si está vacío.

#### 3.5 — `dropdown_error.log` se crea en el cwd (no al lado del exe)
`main.py:353` escribe `dropdown_error.log` con path relativo. Cuando se ejecuta como `.exe` congelado, el cwd puede ser `C:\Windows\System32` (si lo lanzan desde otro proceso) — no se puede escribir ahí → excepción silenciosa, que es lo peor de ambos mundos.

**Mejoras**:
- Usar `BASE_PATH` para todos los logs (`os.path.join(BASE_PATH, "logs", "dropdown_error.log")`).
- Configurar `logging` con `RotatingFileHandler`.

---

### 🟡 Importantes (afectan mantenibilidad y escalabilidad)

#### 3.6 — Monolito de 703 líneas en `main.py`
UI, version-fetching, JDK download, sync de mods, threading, paleta de colores, dropdown custom y subprocess viven en **un solo archivo**. Refactorizar en módulos ayudaría mucho:

```
src/
├── app.py                  # HexLauncher class, glue
├── ui/
│   ├── palette.py          # BG, CYAN, MUTED...
│   ├── widgets.py          # CTkScrollableDropdown, _divider, _field_label
│   └── main_window.py
├── core/
│   ├── versions.py         # _fetch_versions, _update_version_list
│   ├── jdk.py              # _download_jdk (con checksum)
│   ├── mods.py             # _sync_mods, _mods_folder_for, _update_mods_count
│   └── launcher.py         # _launch_game, subprocess
└── utils/
    ├── paths.py            # BASE_PATH, MC_DIR, MODS_DIR, JAVA_DIR, resource_path
    └── logger.py           # logging setup
```

#### 3.7 — `CTkScrollableDropdown` ocupa ~170 líneas (líneas 64-229)
Workaround manual de un bug de `CTkScrollableFrame`. Es un widget reusable que merece su propio archivo + tests. Más importante: **CustomTkinter ya lanzó versiones con el bug arreglado**; valida si todavía es necesario (la versión pinneada es 5.2.2, revisa changelogs).

#### 3.8 — Sin persistencia de configuración
Cada lanzamiento el usuario re-escribe su username y vuelve a elegir version/loader. Un `settings.json` con:
```json
{
  "username": "BillyHz",
  "last_version": "1.21",
  "last_loader": "fabric",
  "jvm_args": ["-Xmx4G", "-Xms2G"],
  "window_geometry": "420x540"
}
```
mejoraría mucho la UX.

#### 3.9 — Subprocess bloqueante para el juego
`main.py:685` con `subprocess.run(cmd)` espera a que Minecraft se cierre. Durante todo ese tiempo el launcher queda "minimizado" (`self.withdraw()`) y no se puede reabrir, no se puede lanzar otro perfil, ni monitorear el juego. Mejor:
- `subprocess.Popen(cmd)` no bloqueante.
- Botón "Stop" para terminar el proceso.
- Mostrar ventana de nuevo otra vez al detectar cierre del proceso.

#### 3.10 — Sin tests ni CI
No existe ni un `tests/` ni un workflow `.github/workflows/ci.yml`. Para una app que descarga binarios externos y manipula el filesystem del usuario, **un test mínimo de `_sync_mods` (copia de mods) y `_mods_folder_for` ya atraparía regresiones futuras**.

#### 3.11 — Pinning a Python 3.14
`.python-version` exige `3.14`. Eso es bleeding-edge y deja fuera al 99% de los contribuidores que aún están en 3.11/3.12. Sugerencia:
- Mínimo `>=3.11` (que ya tiene todas las features que usan: `match`, `tomllib`, etc.).
- `pyproject.toml` con `requires-python = ">=3.11"`.

#### 3.12 — Sin chequeo de versión Mojang para Forge/NeoForge
`main.py:647` llama `get_latest_loader_version(version)` y asume que devuelve algo compatible. Si el loader no soporta esa MC version, `install()` puede lanzar excepción genérica. Mejor:
```python
supported = ml.get_minecraft_versions(supported_only=True)
if version not in supported:
    # mostrar dialog, no lanzar PLAY
```

---

### 🟢 Nice-to-have (cosméticos, DX, OSS-polish)

#### 3.13 — Docstrings mínimos
Solo `_divider`, `_mods_folder_for` y `CTkScrollableDropdown` tienen docstrings. Para un OSS público, vale la pena docstrings en cada método público, y un `pyproject.toml` con ruff/mypy como dev-deps.

#### 3.14 — Documentos huérfanos en `BUILD.md`
Menciona `ANTIVIRUS.md`, `sign.bat`, `build.bat`, `MIGRATION.md` — ninguno existe en el repo. Para evitar confusión, **publica esos archivos o quítalos del `BUILD.md`**.

#### 3.15 — Roadmap ambicioso pero no priorizado
```
[ ] Linux & macOS support
[ ] Microsoft account authentication
[ ] Mod browser (Modrinth / CurseForge integration)
[ ] Auto-updater
[ ] Server management
[ ] Custom themes
```
- **Mod browser (Modrinth/CurseForge)** es el diferenciador #1 — vale la pena atacarlo primero.
- **MS auth** es requerido por Microsoft; sin él no se puede jugar Minecraft moderno sin tricks.
- Marcar milestones con issues/Projects en GitHub.

#### 3.16 — `darkdetect` declarado pero no usado directamente
`customtkinter` lo usa internamente, pero como dep declarada vale. Está bien, solo quería señalarlo por si se quiere remover (puede ayudar a reducir el tamaño del `.exe`).

#### 3.17 — Internacionalización ausente
GUI 100% en inglés. Para una herramienta de comunidad global (Minecraft), i18n con `gettext`/`babel` bajaría la barrera. **No crítico** pero加分.

#### 3.18 — `from minecraft_launcher_lib import mod_loader` adentro de funciones
`main.py:471` y `main.py:642` importan `mod_loader` dentro de las funciones para evitar costos de import al inicio. OK pero en Python 3.14 el costo es trivial; mover al top mejora legibilidad.

#### 3.19 — Hardcoded `creationflags=0x08000000`
`main.py:685` usa `CREATE_NO_WINDOW`. Bien para evitar flash de consola en Windows, pero **esconde la salida de error de Java**. Para debugging, un toggle `--verbose` o `HEXLAUNCHER_DEBUG=1` que imprima logs sería útil.

#### 3.20 — Sin icono en `mods_frame` ni en el dropdown
Cosmético pero el cyberpunk UI pide coherencia. Una row con icono + count quedaría más pulida.

---

## 4. Comparativa rápida con launchers similares

| Feature | HexLauncher | MultiMC | PrismLauncher | SKLauncher |
|---|:---:|:---:|:---:|:---:|
| Multi-instancia | ❌ | ✅ | ✅ | ✅ |
| Modrinth/CurseForge browser | ❌ | parcial | ✅ | ✅ |
| Java auto-install | ✅ | ❌ | parcial | ✅ |
| Microsoft auth | ❌ | ✅ | ✅ | ✅ |
| Tamaño binario | ~25-30 MB | ~15 MB | ~25 MB | ~30 MB |
| Multiplataforma | ❌ | ✅ | ✅ | ❌ |
| GPL-3.0 | ✅ | ✅ | ✅ | ❌ |

HexLauncher compite en simplicidad y estética, no en features. Si quiere crecer, **Modrinth browser + Microsoft auth** son los dos saltos cualitativos más obvios.

---

## 5. Sugerencias de roadmap priorizado (90 días)

| Sprint | Acción |
|---|---|
| **S1** | SHA-256 + Adoptium API para JDK dinámico; `settings.json`; logging a `logs/`; validación de versión Forge/NeoForge antes de instalar |
| **S2** | Refactor `main.py` → `src/` por capas; `pyproject.toml`; ruff + mypy |
| **S3** | Tests (pytest) sobre `mods.py` y `versions.py`; GitHub Actions CI |
| **S4** | Modrinth API integration (search + download) — feature estrella |
| **S5** | `subprocess.Popen` no bloqueante + botón STOP + ventana re-elevable durante el juego |

---

## 6. Resumen ejecutivo (TL;DR)

**Estado del proyecto**: funcional, visualmente pulido, OSS-clean en términos de licencia y gitignore, pero con deuda técnica importante en seguridad (sin checksum del binario que se ejecuta), robustez (try/except silenciosos), y mantenibilidad (monolito sin tests).

**Tres quick wins** que mejorarían la calidad de un día para otro:
1. Validar el SHA-256 del JDK descargado.
2. Sacar `dropdown_error.log` del cwd y meterlo en `BASE_PATH/logs/`.
3. Validar `username` con regex antes de habilitar el botón PLAY.

**El siguiente paso lógico**: Modrinth browser (es la funcionalidad que la comunidad más pide y la que más diferenciaría a HexLauncher de MultiMC).