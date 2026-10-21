"""Packaging fails early and signs final assets before recording their hashes."""

import hashlib
from pathlib import Path

import pytest

import build


def test_missing_compiler_fails_before_pyinstaller(monkeypatch):
    def missing(*args):
        raise FileNotFoundError("Install Inno Setup")

    monkeypatch.setattr(build, "find_iscc", missing)
    monkeypatch.setattr(build.subprocess, "run", lambda *args, **kwargs: pytest.fail("No build should start"))
    with pytest.raises(FileNotFoundError, match="Inno Setup"):
        build.build()


def test_explicit_compiler_path_with_spaces(tmp_path):
    compiler = tmp_path / "Tools with spaces" / "ISCC.exe"
    compiler.parent.mkdir()
    compiler.write_bytes(b"compiler fixture")
    assert build.find_iscc(compiler) == compiler.resolve()


def test_installer_signing_precedes_checksum(tmp_path, monkeypatch):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "HexLauncher.exe").write_bytes(b"launcher")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "find_iscc", lambda _: Path("ISCC.exe"))
    setup = tmp_path / "dist" / f"HexLauncher-Setup-v{build.VERSION}-windows-x64.exe"

    def compile_setup(command, **kwargs):
        assert f"/DAppVersion={build.VERSION}" in command
        assert f"/DProjectRoot={tmp_path}" in command
        setup.write_bytes(b"unsigned setup")

    def sign(path, thumbprint):
        assert path == setup
        path.write_bytes(b"signed setup")

    monkeypatch.setattr(build.subprocess, "run", compile_setup)
    monkeypatch.setattr(build, "sign_executable", sign)
    assert build.build_installer(sign=True, certificate_thumbprint="certificate") == setup
    expected = hashlib.sha256(b"signed setup").hexdigest()
    assert setup.with_name(setup.name + ".sha256").read_text() == f"{expected}  {setup.name}\n"
