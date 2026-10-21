# Building HexLauncher and Windows Setup

## Prerequisites

Use Python 3.14 on Windows with Tcl/Tk installed. From the project root:

```powershell
py -3.14 -m pip install -r requirements.txt -r requirements-dev.txt
```

The runtime requirements provide the application dependencies; the development
requirements add test tools and PyInstaller.

For the Setup installer, also provide **Inno Setup 6.3+ or 7**. `build.py` finds
`ISCC.exe` on PATH and in the usual per-user/Program Files locations. A portable
compiler works too: pass `--iscc "C:\Tools\Inno Setup\ISCC.exe"` or set `ISCC`.

## Checks and build

```powershell
py -3.14 -m pytest -q
py -3.14 -m ruff check .
py -3.14 -m mypy src/hexlauncher/core src/hexlauncher/utils/settings.py
py -3.14 build.py
```

The tests use local fixtures for networking and game processes. UI tests require
a desktop session with Tcl/Tk available. They do not launch Minecraft.

`build.py` invokes PyInstaller with the project's `hexlauncher.spec`, keeping
entry points, assets, hidden imports and output configuration in one place.
It then compiles `installer/HexLauncher.iss` using the same application version.
Rebuild with the same command after changing code or dependencies.

Build options:

```powershell
py -3.14 build.py --iscc "C:\Tools\Inno Setup\ISCC.exe"
py -3.14 build.py --portable-only
py -3.14 build.py --installer-only --iscc "C:\Tools\Inno Setup\ISCC.exe"
```

`--installer-only` packages the existing EXE; use the full build for a fresh release.
Missing compiler dependencies fail before the full PyInstaller build starts.

## Output and distribution

The primary distribution is `dist/HexLauncher-Setup-v<VERSION>-windows-x64.exe`,
with its `.sha256` checksum. Setup lets the player choose a folder and optionally
create a desktop shortcut (checked by default, including on reinstall). It also
creates a Start menu shortcut and a Windows uninstall entry. Spanish and English
installer messages are included.
Setup writes its chosen language to `installation.ini`. On first launch (including
upgrading an installation made before this metadata existed), the launcher adopts
it without resetting usernames, RAM, instances or other settings. A subsequent
manual language preference is preserved while the installer language stays the same;
choosing another installer language applies the new choice once.

Installation is per-user without elevation. The default directory is
`%LOCALAPPDATA%\Programs\HexLauncher`, which keeps the executable and all runtime
data together in a writable folder compatible with the automatic updater. Players
can choose a different writable folder, including an existing portable installation.
Only `HexLauncher.exe` and `LICENSE.txt` are packaged: local worlds, settings, Java
downloads, screenshots and developer files are never included. Uninstall removes
application files and shortcuts, retaining player-generated data. Close the launcher
before reinstalling or uninstalling; Setup does not force-close running games/servers.

The portable output remains `dist/HexLauncher.exe`. Users can run it without
installing Python. Minecraft and Java downloads still require network access.

The build also generates `HexLauncher.exe.sha256` and a versioned Windows ZIP.
Version metadata comes from `src/hexlauncher/version.py`; keep `pyproject.toml`
and the README version aligned when releasing. Build via `build.py`, which generates
the Windows version resource before invoking the shared PyInstaller specification.

For trusted, timestamped signing, see [ANTIVIRUS.md](ANTIVIRUS.md). With `--sign`,
the launcher is signed before packaging and the Setup is signed before its checksum.

To exercise real packaging and installation locally after building:

```powershell
$env:HEX_ISCC = 'C:\Tools\Inno Setup\ISCC.exe'
$env:HEX_PACKAGED_TEST_EXE = (Resolve-Path 'dist\HexLauncher.exe').Path
py -3.14 -m pytest tests/test_build.py tests/test_installer.py tests/test_packaged_updater.py -q
```

Installer tests use an isolated copy of the production script with a unique test
application ID, redirect both shortcut locations into temporary folders, and verify
custom paths, default/unchecked desktop options, reinstall, and data preservation
after uninstall. They do not alter the real player's shortcuts or registration.

## Automatic updates

The Windows executable checks GitHub's latest **stable** release in the background
on startup. Settings provides a check button, an opt-out switch and **Update and
restart**. Source runs and the offline smoke check do not make update requests.
Prereleases and downgrades are excluded. Users approve installation with the
button; downloads and executable replacement are then automatic.
Historical tags such as `vAlpha0.7.0` are recognized as prereleases even when
GitHub marks them stable. Unrecognized release tags are logged and skipped.

Publish a stable release in `BillyHz/HexLauncher` with a semantic tag such as
`v0.7.0` and upload the final executable with the exact asset name
`HexLauncher.exe`. The ZIP alone is insufficient. GitHub's asset `digest` must
contain a SHA-256; the updater refuses missing digests, corrupt/truncated downloads
and unexpected download URLs. The `.sha256` file is provided for manual verification.

Installation requires Minecraft, server and mod installations to be idle, and
a writable executable directory. It uses no elevation. A copied helper waits for
the launcher to close, verifies the file again, replaces the executable and restarts
it with a fresh PyInstaller environment. Settings, mods and worlds stay in place.
Successful update staging is cleaned after the new launcher opens. A failed update
retains `previous.exe` for manual recovery and `error.txt`. If replacement or spawning the new executable
fails, the previous executable is preserved/restored. A later crash inside the new
application is not automatically detected or rolled back.

Older releases without this updater require one manual installation first.
Publishing a GitHub release and acquiring a signing certificate are separate
steps; a local build does neither.

The launcher stores its data beside the executable:

- `HexFiles/`: usual Minecraft installation.
- `HexMods/<Loader>/<Version>/`: mod library for the usual installation.
- `HexInstances/<id>/`: separate modpacks with pinned Minecraft and loader versions.
- `HexJDK/`: downloaded and verified Java runtime.
- `logs/`: diagnostic logs.
- `settings.json`: validated, atomically saved configuration.

For an active pack, additional mods install directly in that instance's `mods/`
folder. The installed-mods view and folder shortcuts use the selected instance.
The `.hexmods.json` registry tracks managed versions and required dependencies;
updates and deletions publish transactionally with rollback on failure.

The launcher manages one Minecraft process. **DETENER** remains available while
it runs. The hide-on-launch setting restores the launcher when the game exits.

## Troubleshooting

For reproducible navigation profiling with a visible offline window, run
`python scripts/profile_navigation.py --output build/navigation-current`.
Add `--rounds 60 --stress` to exercise 300 tab changes while search results
arrive. See [navigation performance](docs/navigation-performance.md) for the
measured comparison, methodology and remaining limits under concurrent work.

**Missing module or asset at runtime**

Inspect the launch logs and update `hiddenimports` or data files in
`hexlauncher.spec`, then rebuild using `build.py`.

**Icon not showing**

Ensure `Hex.ico` exists in the project root and is included by the specification.

**Antivirus flags the executable**

See [ANTIVIRUS.md](ANTIVIRUS.md). Build output and startup behavior depend on the
Python, dependency and Windows versions; measure the resulting executable rather
than assuming a fixed binary size or startup time.
