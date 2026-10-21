"""Opt-in real Setup tests; all shortcuts and payloads stay in temporary folders.

Set HEX_ISCC and HEX_PACKAGED_TEST_EXE to enable. The test compiles the production
script with a unique test AppId and redirects desktop/Start menu icons into its
sandbox, so it never overwrites a player's shortcuts or installation registration.
"""

import configparser
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from src.hexlauncher.utils.settings import Settings
from src.hexlauncher.version import VERSION

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("HEX_ISCC") or not os.environ.get("HEX_PACKAGED_TEST_EXE"),
    reason="Requires Windows, HEX_ISCC and HEX_PACKAGED_TEST_EXE",
)


@pytest.fixture(scope="module")
def setup_sandbox(tmp_path_factory):
    root = tmp_path_factory.mktemp("setup")
    project = Path(__file__).resolve().parents[1]
    (root / "dist").mkdir()
    shutil.copy2(os.environ["HEX_PACKAGED_TEST_EXE"], root / "dist" / "HexLauncher.exe")
    shutil.copy2(project / "Hex.ico", root / "Hex.ico")
    shutil.copy2(project / "LICENSE", root / "LICENSE")
    private = root / "dist" / "HexFiles" / "private-player-file.txt"
    private.parent.mkdir()
    private.write_text("must never be packaged")
    desktop, programs = root / "desktop", root / "programs"
    desktop.mkdir()
    programs.mkdir()
    source = (project / "installer" / "HexLauncher.iss").read_text(encoding="utf-8")
    source = source.replace(
        "AppId={{2D188C74-33D6-4986-B173-461D356A6854}", f"AppId=HexLauncher.SetupTest.{uuid.uuid4().hex}"
    ).replace("{userdesktop}", str(desktop)).replace("{userprograms}", str(programs))
    script = root / "Test.iss"
    script.write_text(source, encoding="utf-8-sig")
    subprocess.run([
        os.environ["HEX_ISCC"], f"/DProjectRoot={root}", f"/DAppVersion={VERSION}",
        f"/DNumericVersion={VERSION.split('-')[0]}.0", str(script),
    ], check=True, capture_output=True)
    return root, root / "dist" / f"HexLauncher-Setup-v{VERSION}-windows-x64.exe"


@pytest.mark.parametrize("desktop_shortcut,language", [(True, "spanish"), (False, "english")])
def test_install_shortcuts_and_uninstall_preserve_player_data(setup_sandbox, tmp_path, desktop_shortcut, language):
    root, setup = setup_sandbox
    target = tmp_path / "Instalación del jugador con espacios"
    saved = tmp_path / "choices.ini"
    arguments = [
        str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        f"/DIR={target}", f"/SAVEINF={saved}", f"/LOG={tmp_path / 'setup.log'}", f"/LANG={language}",
    ]
    if not desktop_shortcut:
        arguments.append("/TASKS=!desktopicon")
    subprocess.run(arguments, check=True, timeout=60)
    link = root / "desktop" / "HexLauncher.lnk"
    try:
        assert (target / "HexLauncher.exe").read_bytes() == (root / "dist" / "HexLauncher.exe").read_bytes()
        assert not (target / "HexFiles" / "private-player-file.txt").exists()
        assert link.exists() == desktop_shortcut
        expected_language = "es" if language == "spanish" else "en"
        assert Settings(str(target)).get("language") == expected_language
        metadata = (target / "installation.ini").read_bytes()
        if desktop_shortcut:
            # A desktop shortcut starts outside the app folder; verify that the
            # packaged application can initialize from the chosen Unicode path.
            subprocess.run(
                [str(target / "HexLauncher.exe"), "--smoke-test"], cwd=tmp_path,
                creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=30,
            )
        choices = configparser.ConfigParser()
        # Inno's SAVEINF uses the Windows ANSI code page, including accented paths.
        choices.read(saved, encoding="mbcs")
        assert ("desktopicon" in choices["Setup"]["Tasks"]) == desktop_shortcut
        if desktop_shortcut:
            # Inspect the actual Windows shortcut, including its working directory.
            reader = tmp_path / "read-shortcut.ps1"
            reader.write_text(
                'param([string]$Link)\n'
                '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n'
                '$shell = New-Object -ComObject WScript.Shell\n'
                '$shortcut = $shell.CreateShortcut($Link)\n'
                '@{Target=$shortcut.TargetPath; Directory=$shortcut.WorkingDirectory} | ConvertTo-Json\n',
                encoding="utf-8-sig",
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-File", str(reader), str(link)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            shortcut = json.loads(result.stdout)
            assert Path(shortcut["Target"]) == target / "HexLauncher.exe"
            assert Path(shortcut["Directory"]) == target
        user_files = [
            "settings.json", "HexFiles/saves/My World/level.dat", "HexFiles/resourcepacks/textures.zip",
            "HexMods/Fabric/1.21/example.jar", "HexInstances/pack/mods/keep.jar", "HexServer/world/level.dat",
        ]
        for relative in user_files:
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"player data")
        # Installing over the same directory must preserve existing player files.
        subprocess.run(arguments, check=True, timeout=60)
        assert all((target / name).read_bytes() == b"player data" for name in user_files)
    finally:
        subprocess.run([
            str(target / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        ], check=True, timeout=60)
    deadline = time.monotonic() + 10
    while (target / "HexLauncher.exe").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not (target / "HexLauncher.exe").exists()
    assert not link.exists()
    assert all((target / name).read_bytes() == b"player data" for name in user_files)
    assert (target / "installation.ini").read_bytes() == metadata
