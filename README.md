# HexLauncher

> A lightweight, open-source Minecraft launcher with a cyberpunk aesthetic
> and first-class mod loader support.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078d4.svg)](https://www.microsoft.com/windows)
[![Version: 0.7.0-beta.1](https://img.shields.io/badge/version-0.7.0--beta.1_beta-orange.svg)](#)

---

<img width="1000" height="707" alt="image" src="https://github.com/user-attachments/assets/e2b1ed21-3323-4157-90df-70c8b310892f" />


---

## ✨ Features

- 🎮 **One-click Minecraft launch** — pick a version, enter a username, hit PLAY
- 🔌 **Mod loader support** — Fabric, Forge, NeoForge out of the box
- 📁 **Mod management** — drop `.jar` files into per-loader, per-version folders
- 🎨 **Cyberpunk UI** — dark theme with neon cyan accents
- 📦 **Standalone `.exe`** — no Python install required for end users
- 🔓 **Free & open source** — GPL v3, no telemetry, no ads

## 📥 Download

Grab the latest release from the [**Releases**](../../releases) page.

> **Windows Defender note:** the `.exe` is built with PyInstaller and may
> trigger a SmartScreen warning on first run. See
> [this guide](https://github.com/BillyHz/HexLauncher/wiki/Antivirus) for
> how to add an exclusion.

## 🚀 Quick start

1. Download `HexLauncher.exe` from the latest release
2. Put it in any folder (e.g. `C:\Games\HexLauncher\`)
3. Run it
4. On first launch, the app creates:
   - `HexFiles/` — Minecraft installation
   - `HexMods/` — your mod library
   - `HexJDK/` — bundled Java runtime (auto-downloaded)
5. Enter a username, pick a version, hit **PLAY**

## 🧩 Adding mods

1. Select a mod loader in the dropdown (Fabric, Forge, or NeoForge)
2. Pick a Minecraft version
3. Click **Open folder** in the MODS section
4. Drop your `.jar` mods into the opened folder
5. Hit **PLAY** — the loader is installed and your mods are loaded

Mods are organized by loader and version:
```
HexMods/
├── Fabric/
│   ├── 1.21/
│   │   └── sodium-fabric-1.21.jar
│   └── 1.20.4/
│       └── ...
├── Forge/
└── NeoForge/
```

## Launching and settings

HexLauncher runs one Minecraft process at a time. The play button becomes
**DETENER** while the game is running, including when the username is edited.
The optional launch setting hides the launcher while Minecraft runs and restores
it when the process exits.

Settings validate RAM, Java paths and JVM arguments. Configuration is saved
atomically; invalid input and failed writes are shown in the interface.
Refreshing version lists runs in the background, and outdated search/version
responses are discarded when filters change.

## Mods & Modrinth

Open **Modrinth & Mods**, select a loader and Minecraft version, and search for
**Mods** or **Modpacks**. Mod cards display the icon, author and description.
Installing a mod also installs its required dependencies into
`HexMods/<Loader>/<Version>/`. Downloads are verified against SHA-512 and SHA-1
before replacing files; API and download work runs on background threads.
Installations maintain a `.hexmods.json` registry and publish files transactionally,
restoring the previous installation if publication fails. Updating a registered mod
removes its previous `.jar`, even when the filename changes. Deleting a mod is blocked
when another registered mod requires it. Manually added `.jar` files remain supported.

Use **Importar .mrpack** to install a local pack, or install a pack from search.
Packs are staged and published into a new `HexInstances/<id>/` folder only after
all downloads and overrides succeed. The instance selector switches between
installed packs and the usual installation. Minecraft and the loader use the
versions pinned by the pack; pack mods are never replaced by the global library.
Additional compatible mods install directly into the selected pack's `mods/` folder.
The usual installation uses `HexMods/<Loader>/<Version>/`; pack additions do not
modify that shared library. **Mods instalados** lists and removes files from the
currently selected installation.

Client packs apply `overrides/` followed by `client-overrides/`, skip files marked
client `unsupported`, and include optional client files. Quilt packs are rejected
with an explanatory error because HexLauncher currently supports Fabric, Forge
and NeoForge. Existing instance directories are not overwritten by pack imports.

API reference: [Labrinth v2](https://docs.modrinth.com/api/).
Pack specification: [Modrinth .mrpack format](https://support.modrinth.com/en/articles/8802351-modrinth-modpack-format-mrpack).

## 🛠️ Building from source

```bash
# Clone
git clone https://github.com/BillyHz/HexLauncher.git
cd HexLauncher

# Install deps
py -3.14 -m pip install -r requirements.txt

# Run from source
py -3.14 main.py

# Build standalone .exe
py -3.14 -m pip install -r requirements.txt -r requirements-dev.txt
py -3.14 build.py
# → dist/HexLauncher.exe
```

## Development checks

The interface defaults to English. Use the **EN / ES** switch in **Settings**
to change languages immediately; your selection is saved for the next launch.

Install the development dependencies before running the offline checks:

```powershell
py -3.14 -m pip install -r requirements.txt -r requirements-dev.txt
py -3.14 -m pytest -q
py -3.14 -m ruff check .
py -3.14 -m mypy src/hexlauncher/core src/hexlauncher/utils/settings.py
```

`main.py` es el único punto de entrada. En Windows arranca un proceso sin consola
con `pythonw.exe` y termina el proceso inicial. Si lo
ejecutas desde una terminal existente, esa terminal permanece disponible. Los
errores se registran en `logs/launcher.log`.

Tests replace API requests and game processes with local fixtures; they do not
start Minecraft. Run the UI tests on a desktop environment with Tcl/Tk available.
See [BUILD.md](BUILD.md) for packaging using the shared PyInstaller specification.

## 🧱 Tech stack

| Layer | Tech |
|---|---|
| Language | Python 3.14 |
| GUI | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) |
| Minecraft | [minecraft-launcher-lib](https://codeberg.org/JakobDev/minecraft-launcher-lib) |
| Java | Temurin JDK 21 (auto-downloaded) |
| Packaging | PyInstaller |
| License | GPL v3 |

## 🗺️ Roadmap

- [ ] Linux & macOS support
- [ ] Microsoft account authentication
- [x] Modrinth mod browser, dependencies and modpack installation
- [ ] CurseForge integration
- [ ] Auto-updater
- [ ] Server management
- [ ] Custom themes

## 🤝 Contributing

PRs welcome! For major changes, please open an issue first.

```bash
# Fork the repo, then:
git checkout -b feature/my-feature
git commit -m "Add my feature"
git push origin feature/my-feature
# Open a Pull Request on GitHub
```

## 💖 Sponsorship

If HexLauncher makes your Minecraft life easier, consider supporting
development:

- [**Patreon**](https://www.patreon.com/HexLauncher) — monthly support, early access
- [**Ko-fi**](https://ko-fi.com/HexLauncher) — one-time tip
- ⭐ Star this repo — it helps more than you think

## 📜 License

HexLauncher is released under the **GNU General Public License v3.0**.
See [LICENSE](LICENSE) for the full text.

This means you can:
- ✅ Use it for free
- ✅ Modify it
- ✅ Redistribute it

As long as you:
- 📖 Keep the same GPL v3 license
- 📖 Disclose the source
- 📖 State your changes

## 🙏 Acknowledgments

- [minecraft-launcher-lib](https://codeberg.org/JakobDev/minecraft-launcher-lib) by JakobDev
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) by TomSchimansky
- [Adoptium Temurin](https://adoptium.net/) for the JDK builds
- The Minecraft community for endless modding inspiration

## 📬 Contact

- 🐛 Issues: [GitHub Issues](../../issues)
- 💬 Discussions: [GitHub Discussions](../../discussions)
- 🐦 Twitter: [@HexLauncher](https://twitter.com/HexLauncher)

---

Made with 💙 and a lot of ☕ by [BillyHz](https://github.com/BillyHz)
