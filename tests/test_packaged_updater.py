"""Opt-in test of the actual frozen helper, using an isolated Windows executable."""

import hashlib
import os
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("HEX_PACKAGED_TEST_EXE"),
    reason="Requires Windows and HEX_PACKAGED_TEST_EXE pointing to the built launcher",
)
def test_frozen_helper_waits_replaces_and_restarts(tmp_path):
    stage = tmp_path / ".hex-update-test"
    stage.mkdir()
    helper = stage / "helper.exe"
    shutil.copy2(os.environ["HEX_PACKAGED_TEST_EXE"], helper)
    target = tmp_path / "HexLauncher.exe"
    target.write_bytes(b"MZprevious executable fixture")
    pending = stage / "pending.exe"
    # A real, harmless Windows program verifies successful process creation without
    # opening a launcher window or making requests to any online services.
    shutil.copy2(os.path.join(os.environ["SystemRoot"], "System32", "whoami.exe"), pending)
    payload = pending.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    parent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        process = subprocess.Popen(
            [str(helper), "--apply-update", str(parent.pid), str(target), str(pending), digest],
            creationflags=subprocess.CREATE_NO_WINDOW,
            env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
        )
        assert process.wait(timeout=30) == 0, (stage / "error.txt").read_text() if (
            stage / "error.txt"
        ).exists() else "helper failed"
        assert target.read_bytes() == payload
        assert (stage / "previous.exe").read_bytes() == b"MZprevious executable fixture"
        assert not pending.exists()
        assert not (stage / "HexMods").exists()  # GUI/path modules were never imported
        assert not (stage / "logs").exists()
    finally:
        parent.wait(timeout=10)
