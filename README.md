# HexLauncher

> A lightweight, open-source Minecraft launcher with a cyberpunk aesthetic
> and first-class mod loader support.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078d4.svg)](https://www.microsoft.com/windows)
[![Version: 0.7.0-beta.1](https://img.shields.io/badge/version-0.7.0--beta.1_beta-orange.svg)](#)

---

<img width="1000" height="711" alt="image" src="https://github.com/user-attachments/assets/4f0dc7d8-ee6f-4918-ae45-acdcde66c5e1" />

---

## ✨ Features

- 🎮 **One-click Minecraft launch** — pick a version, enter a username, hit PLAY
- 🔌 **Mod loader support** — Fabric, Forge, NeoForge out of the box
- 📁 **Mod management** — drop `.jar` files into per-loader, per-version folders
- 🎨 **Cyberpunk UI** — dark theme with neon cyan accents
- 📦 **Standalone `.exe`** — no Python install required for end users
- 🔓 **Free & open source** — GPL v3, no telemetry, no ads

## 📥 Download

Download **HexLauncher-Setup-v…-windows-x64.exe** from the [**Releases**](../../releases)
page for the guided installation. A portable ZIP is also available.

> **Windows security note:** a new or unsigned executable may show a SmartScreen
> warning. See [Windows signing and security](ANTIVIRUS.md) for publisher signing,
> application reputation and reporting incorrect antivirus detections.

## 🚀 Quick start

1. Download and run **HexLauncher-Setup-v…-windows-x64.exe**.
2. Select the installer language and installation folder. The launcher adopts that
   language on first launch. The default folder is `%LOCALAPPDATA%\Programs\HexLauncher`.
3. Leave **Create a desktop shortcut** checked, or uncheck it if you prefer.
4. Finish installation and launch HexLauncher from its shortcut or the Start menu.
   The executable and all game data stay inside the chosen folder, including:
   - `HexFiles/` — Minecraft installation
   - `HexMods/` — your mod library
   - `HexJDK/` — bundled Java runtime (auto-downloaded)
5. Enter a username, pick a version, hit **PLAY**.

For an existing portable installation, select its current folder in Setup to keep
using the same worlds, mods and settings. Reinstalling replaces the application
files; uninstalling removes the launcher and shortcuts while preserving player data.
The portable ZIP can still be extracted into a dedicated folder and run directly.
You can change the launcher language later in **Settings**. Selecting a different
language during a later Setup run applies that new language without resetting other settings.

## 🧩 Adding mods

1. In **Mods & modpacks**, choose Fabric, Forge or NeoForge. Select your Minecraft
   version in the bottom bar.
2. Search by name, or use **Add .jar files…** to select
   one or several downloaded mods. Use files compatible with your loader and version.
3. Check **Installed mods**, then press **PLAY** to load them.

The destination selector in the section follows your selected installation or modpack.
Local imports validate every JAR before publishing the selection together. Existing
filenames are preserved; remove an old file from **Installed mods** before replacing it.
The mods folder shortcut remains available for manual file management.

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

## Texture / resource packs

Open the separate **Textures** tab to search Modrinth by name, or leave the search
empty and press **Search** to explore. Results match the Minecraft version selected
in the bottom bar, independently of the mod loader. Choose the destination installation
in the tab and click **Install**. Downloads are checked against the published hashes,
size and ZIP metadata before being copied into that installation's `resourcepacks/`.
**My textures** lists its installed ZIPs. **Add local ZIP…** also imports downloaded packs.

Local resource-pack ZIPs must include `pack.mcmeta` at their root and are copied, without extraction,
into the selected installation's `resourcepacks/` folder. Existing packs are
preserved; duplicate names get a numbered suffix. The installed ZIPs appear in
**My textures**, and **Open textures folder** opens that
same directory. An active modpack uses its own folder; the usual installation
uses `HexFiles/resourcepacks/`.

Enable the pack inside Minecraft under **Options > Resource Packs**. Choose a
pack compatible with your Minecraft version. Imports run in the background and
require Minecraft and other installation/update operations to be idle.

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

## Local server with Playit.gg

Open **Local Server**, choose a Minecraft version and **Paper** (recommended),
**Fabric**, **Vanilla**, **Forge**, or **NeoForge**, then allocate 2–8 GB of RAM. The safe limit keeps at
least 2 GB available for Windows and the client and caps the server at half the
system RAM. Server files, worlds, and Playit credentials stay in the ignored
`HexServer/` directory, separate from client instances.

**Start Local Server** downloads the server and the official Playit agent and
starts both without console windows. Starting accepts the Minecraft EULA. The
initial properties use port 25565, loopback binding, `online-mode=false`, and
`motd=Servidor de HexLauncher`; subsequent starts preserve your settings/world.

On first use, select **Link Playit.gg Tunnel** and create a **Minecraft Java**
tunnel in the Playit dashboard pointing to `127.0.0.1:25565`. **Configure Tunnel**
opens that dashboard. Once Playit reports this mapping, **Copy Address** copies
the address for friends. You can join locally using `localhost:25565`.

**Stop Server** sends `stop` and waits for world saving. Closing the launcher
also waits for preparation/stop without blocking the interface. If Java fails
to respond within 60 seconds, the manager logs the forced shutdown fallback.
The console is collapsible and keeps a bounded log history.

Paper downloads use the official [Fill v3 API](https://docs.papermc.io/misc/downloads-service/)
and stable builds only, with SHA-256 verification. Vanilla uses Mojang's
published SHA-1. Fabric's generated launcher endpoint does not publish a hash;
the download uses official HTTPS and JAR manifest/CRC validation. The internal
Java 21 runtime supports versions requiring Java 17–21; incompatible versions
are rejected before downloading a server. To change an existing server's version
or type, back up and move `HexServer/` first; existing worlds are never migrated
automatically.

The integration pins the official standalone [Playit v0.17.1](https://github.com/playit-cloud/playit-agent/releases/tag/v0.17.1)
and verifies its published SHA-256. Playit's newer daemon has a different
lifecycle; it is not interchangeable with the stdout-based agent used here.

Forge and NeoForge use their official Maven installers with published checksums.
The installer runs in a temporary directory with `--installServer`; the manager
launches Java using the generated `win_args.txt` instead of executing `.bat`
scripts. Installer output appears in the console and installation can be
cancelled when closing the launcher. Compatible server mods belong in
`HexServer/mods`; players need matching loader/mod versions. **Server Folder**
opens the server directory.

## Automatic updates and Windows signing

The Windows executable checks stable GitHub Releases on startup. In **Settings**,
use **Check for updates** and **Update and restart**, or disable startup checks.
Downloads require GitHub's SHA-256 digest and are installed after the launcher
closes. Minecraft and the local server must be stopped first. User data stays in
place and the previous executable is kept for recovery. See [BUILD.md](BUILD.md)
for the release asset requirements.

Trusted code signing with timestamps is supported by `build.py --sign`.
SmartScreen warnings can still appear until reputation develops; an EV certificate
does not guarantee an immediate bypass. See [ANTIVIRUS.md](ANTIVIRUS.md) for the
signing workflow and Microsoft Store/MSIX option.

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
- [x] Auto-updater for stable Windows releases
- [x] Local server management with Playit.gg
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
