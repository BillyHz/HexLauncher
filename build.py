#!/usr/bin/env python3
"""Build HexLauncher.exe using PyInstaller.

Usage:
    py -3.14 build.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build():
    """Run PyInstaller to build HexLauncher.exe."""
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
    print(f"\n[OK] Build complete: {out}")
    if out.exists():
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"  Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    build()
