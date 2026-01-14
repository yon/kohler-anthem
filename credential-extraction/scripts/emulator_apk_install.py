#!/usr/bin/env python3
"""Install Kohler Konnect APK on Android emulator.

Usage:
    python3 emulator_apk_install.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
APK_DIR = PROJECT_DIR / "kohler-konnect-3.0.1-apk"

# Package name
PACKAGE_NAME = "com.kohler.hermoth"


def run_adb(args: list[str]) -> subprocess.CompletedProcess:
    """Run an adb command."""
    return subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
    )


def check_device_connected() -> bool:
    """Check if any device is connected."""
    result = run_adb(["devices"])
    if result.returncode != 0:
        return False
    lines = result.stdout.strip().split("\n")
    return any("\tdevice" in line for line in lines[1:])


def get_installed_version() -> str | None:
    """Get currently installed version of the app."""
    result = run_adb(["shell", "dumpsys", "package", PACKAGE_NAME])
    if result.returncode != 0:
        return None
    for line in result.stdout.split("\n"):
        if "versionName=" in line:
            return line.split("versionName=")[1].strip()
    return None


def uninstall_app() -> bool:
    """Uninstall the app if it exists."""
    result = run_adb(["uninstall", PACKAGE_NAME])
    return result.returncode == 0


def install_split_apks() -> bool:
    """Install all split APKs."""
    apk_files = sorted(APK_DIR.glob("*.apk"))
    if not apk_files:
        print(f"  ERROR: No APK files found in {APK_DIR}")
        return False

    print("  Installing split APKs:")
    for apk in apk_files:
        print(f"    - {apk.name}")

    # Use install-multiple for split APKs
    cmd = ["install-multiple"] + [str(apk) for apk in apk_files]
    result = run_adb(cmd)

    if result.returncode != 0 and "INSTALL_FAILED_VERSION_DOWNGRADE" in result.stderr:
        print()
        print("  Version downgrade detected. Uninstalling existing app...")
        if uninstall_app():
            print("  Retrying install...")
            result = run_adb(cmd)
        else:
            print("  ERROR: Failed to uninstall existing app")
            return False

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False

    return True


def main() -> int:
    """Install APK on emulator."""
    print()
    print("=" * 60)
    print("Kohler Konnect APK Installation")
    print("=" * 60)
    print()

    # Check device connection
    if not check_device_connected():
        print("  ERROR: No device connected.")
        print("  Run 'make emulator-check' to verify connection.")
        return 1

    # Check if already installed
    installed_version = get_installed_version()
    if installed_version:
        print(f"  Currently installed: v{installed_version}")
        print()

    # Install APKs
    if not install_split_apks():
        return 1

    print()
    print("  APK installed successfully!")
    print()

    # Verify installation
    new_version = get_installed_version()
    if new_version:
        print(f"  Installed version: v{new_version}")
    print()

    print("  Next step: make emulator-apim-capture")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
