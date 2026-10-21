#!/usr/bin/env python3
"""Build HexLauncher.exe and a Windows Setup installer.

Usage:
    py -3.14 build.py
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from src.hexlauncher.version import VERSION

ROOT = Path(__file__).resolve().parent


def find_iscc(explicit=None):
    """Locate Inno Setup 6.3+ (or 7), with an explicit path taking precedence."""
    configured = explicit or os.environ.get("ISCC")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Inno Setup compiler not found: {path}")
        return path
    found = shutil.which("ISCC.exe")
    if found:
        return Path(found)
    for parent in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ):
        for name in ("Inno Setup 7", "Inno Setup 6"):
            candidate = parent / name / "ISCC.exe"
            if candidate.is_file():
                return candidate
    portable = ROOT / "build" / "toolchain" / "inno-portable" / "tools" / "ISCC.exe"
    if portable.is_file():
        return portable
    raise FileNotFoundError(
        "Install Inno Setup 6.3+ or 7, or pass --iscc PATH. "
        "Use --portable-only to build without Setup."
    )


def write_checksum(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")


def sign_executable(executable, certificate_thumbprint):
    if not certificate_thumbprint:
        raise ValueError("--sign requires --certificate-thumbprint")
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-File", str(ROOT / "scripts" / "sign.ps1"),
            "-CertificateThumbprint", certificate_thumbprint, "-Executable", str(executable),
        ], check=True,
    )


def build_installer(iscc=None, sign=False, certificate_thumbprint=None):
    """Package only the launcher and license, never local player data."""
    compiler = find_iscc(iscc)
    executable = ROOT / "dist" / "HexLauncher.exe"
    if not executable.is_file():
        raise FileNotFoundError("Build dist/HexLauncher.exe before using --installer-only.")
    if sign and not certificate_thumbprint:
        raise ValueError("--sign requires --certificate-thumbprint")
    numeric_version = VERSION.split("-")[0] + ".0"
    subprocess.run(
        [
            str(compiler), f"/DAppVersion={VERSION}", f"/DNumericVersion={numeric_version}",
            f"/DProjectRoot={ROOT}", str(ROOT / "installer" / "HexLauncher.iss"),
        ], cwd=ROOT, check=True,
    )
    setup = ROOT / "dist" / f"HexLauncher-Setup-v{VERSION}-windows-x64.exe"
    if sign:
        sign_executable(setup, certificate_thumbprint)
    write_checksum(setup)
    print(f"[OK] Setup complete: {setup}")
    return setup


def build(sign=False, certificate_thumbprint=None, *, portable_only=False, iscc=None):
    """Run PyInstaller to build HexLauncher.exe."""
    if sign and not certificate_thumbprint:
        raise ValueError("--sign requires --certificate-thumbprint")
    compiler = None if portable_only else find_iscc(iscc)
    version_parts = VERSION.split("-")[0].split(".") + ["0"]
    version_tuple = ", ".join(version_parts)
    version_file = ROOT / "build" / "windows-version.txt"
    version_file.parent.mkdir(exist_ok=True)
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo("
        f"filevers=({version_tuple}), prodvers=({version_tuple}), "
        "mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        "StringStruct('FileDescription', 'HexLauncher Minecraft Launcher'), "
        f"StringStruct('FileVersion', '{VERSION}'), "
        "StringStruct('InternalName', 'HexLauncher'), "
        "StringStruct('OriginalFilename', 'HexLauncher.exe'), "
        "StringStruct('ProductName', 'HexLauncher'), "
        f"StringStruct('ProductVersion', '{VERSION}')"
        "])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])",
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(ROOT / "hexlauncher.spec"),
    ]
    print(f"Building in {ROOT}")
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=ROOT, check=True)
    out = ROOT / "dist" / "HexLauncher.exe"
    if sign:
        sign_executable(out, certificate_thumbprint)
    write_checksum(out)
    archive = out.parent / f"HexLauncher-v{VERSION}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.write(out, "HexLauncher.exe")
        package.write(out.parent / "HexLauncher.exe.sha256", "HexLauncher.exe.sha256")
    print(f"\n[OK] Build complete: {out}")
    if out.exists():
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"  Size: {size_mb:.1f} MB")
    if not portable_only:
        build_installer(compiler, sign, certificate_thumbprint)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sign", action="store_true")
    parser.add_argument("--certificate-thumbprint")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--portable-only", action="store_true", help="Skip Setup packaging")
    mode.add_argument("--installer-only", action="store_true", help="Package the existing dist/HexLauncher.exe")
    parser.add_argument("--iscc", help="Path to Inno Setup's ISCC.exe (or set ISCC)")
    options = parser.parse_args()
    if options.sign and not options.certificate_thumbprint:
        parser.error("--sign requires --certificate-thumbprint")
    if options.installer_only:
        build_installer(options.iscc, options.sign, options.certificate_thumbprint)
    else:
        build(options.sign, options.certificate_thumbprint, portable_only=options.portable_only, iscc=options.iscc)
