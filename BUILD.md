# Building HexLauncher.exe

## Prerequisites

Use Python 3.14 on Windows with Tcl/Tk installed. From the project root:

```powershell
py -3.14 -m pip install -r requirements.txt -r requirements-dev.txt
```

The runtime requirements provide the application dependencies; the development
requirements add test tools and PyInstaller.

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
Rebuild with the same command after changing code or dependencies.

## Output and distribution

The output is `dist/HexLauncher.exe`. Users can run the executable without
installing Python. Minecraft and Java downloads still require network access.

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

**Missing module or asset at runtime**

Inspect the launch logs and update `hiddenimports` or data files in
`hexlauncher.spec`, then rebuild using `build.py`.

**Icon not showing**

Ensure `Hex.ico` exists in the project root and is included by the specification.

**Antivirus flags the executable**

See [ANTIVIRUS.md](ANTIVIRUS.md). Build output and startup behavior depend on the
Python, dependency and Windows versions; measure the resulting executable rather
than assuming a fixed binary size or startup time.
