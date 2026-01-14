#!/usr/bin/env python3
"""Set up Genymotion emulator for credential extraction.

Creates and starts a Genymotion virtual device with the required specs.
Requires Genymotion Desktop (30-day trial or licensed).

Usage:
    python3 emulator_setup.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time

# Device configuration
DEVICE_NAME = "KohlerExtraction"
DEVICE_TEMPLATE = "Samsung Galaxy S10"
ANDROID_VERSION = "11.0"
DEVICE_RAM = 4096
DEVICE_CPU = 4

# gmtool paths (macOS)
GMTOOL_PATHS = [
    "gmtool",
    "/Applications/Genymotion.app/Contents/MacOS/gmtool",
]


def find_gmtool() -> str | None:
    """Find the gmtool binary."""
    for path in GMTOOL_PATHS:
        if shutil.which(path):
            return path
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return path
        except FileNotFoundError:
            continue
    return None


def run_gmtool(gmtool: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run a gmtool command."""
    return subprocess.run(
        [gmtool, *args],
        capture_output=True,
        text=True,
    )


def device_exists(gmtool: str, name: str) -> bool:
    """Check if a device with the given name exists."""
    result = run_gmtool(gmtool, ["admin", "list"])
    if result.returncode != 0:
        return False
    return name in result.stdout


def device_running(gmtool: str, name: str) -> bool:
    """Check if a device is running."""
    result = run_gmtool(gmtool, ["admin", "list", "--running"])
    if result.returncode != 0:
        return False
    return name in result.stdout


def get_available_templates(gmtool: str) -> list[str]:
    """Get list of available device templates."""
    result = run_gmtool(gmtool, ["admin", "templates"])
    if result.returncode != 0:
        return []
    return result.stdout.strip().split("\n")


def create_device(gmtool: str) -> bool:
    """Create the extraction device."""
    print(f"  Creating device '{DEVICE_NAME}'...")
    print(f"    Template: {DEVICE_TEMPLATE}")
    print(f"    Android: {ANDROID_VERSION}")
    print(f"    RAM: {DEVICE_RAM}MB, CPUs: {DEVICE_CPU}")

    result = run_gmtool(
        gmtool,
        [
            "admin",
            "create",
            DEVICE_TEMPLATE,
            ANDROID_VERSION,
            DEVICE_NAME,
            "--nbcpu",
            str(DEVICE_CPU),
            "--ram",
            str(DEVICE_RAM),
        ],
    )

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        if "not found" in result.stderr.lower():
            print()
            print("  Available templates:")
            for template in get_available_templates(gmtool)[:10]:
                print(f"    - {template}")
        return False

    print("  Device created successfully")
    return True


def start_device(gmtool: str) -> bool:
    """Start the device."""
    print(f"  Starting device '{DEVICE_NAME}'...")

    result = run_gmtool(gmtool, ["admin", "start", DEVICE_NAME])

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False

    print("  Device starting...")
    return True


def wait_for_adb(timeout: int = 60) -> bool:
    """Wait for device to be connected via adb."""
    print("  Waiting for adb connection...")

    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            for line in lines[1:]:
                if "\tdevice" in line:
                    print("  Device connected via adb")
                    return True
        time.sleep(2)

    print("  ERROR: Timed out waiting for adb connection")
    return False


def main() -> int:
    """Set up Genymotion emulator."""
    print()
    print("=" * 60)
    print("Genymotion Emulator Setup")
    print("=" * 60)
    print()

    # Find gmtool
    gmtool = find_gmtool()
    if not gmtool:
        print("  ERROR: gmtool not found")
        print()
        print("  Genymotion Desktop is required for emulator setup.")
        print("  Download from: https://www.genymotion.com/product-desktop/download/")
        print()
        print("  Note: You need Genymotion Desktop (30-day trial), not the free edition.")
        return 1

    print(f"  Found gmtool: {gmtool}")
    print()

    # Check if device exists
    if device_exists(gmtool, DEVICE_NAME):
        print(f"  Device '{DEVICE_NAME}' already exists")

        # Check if running
        if device_running(gmtool, DEVICE_NAME):
            print("  Device is already running")
            print()
            print("  Next step: make emulator-check")
            return 0
    else:
        # Create device
        if not create_device(gmtool):
            return 1
        print()

    # Start device
    if not device_running(gmtool, DEVICE_NAME):
        if not start_device(gmtool):
            return 1

        # Wait for adb
        print()
        if not wait_for_adb():
            return 1

    print()
    print("  Emulator setup complete!")
    print()
    print("  Next step: make emulator-frida-setup")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
