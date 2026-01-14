#!/usr/bin/env python3
"""Check if an Android emulator is connected via adb.

Usage:
    python3 emulator_check.py
"""

from __future__ import annotations

import subprocess
import sys


def run_adb(args: list[str]) -> subprocess.CompletedProcess:
    """Run an adb command."""
    return subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
    )


def get_connected_devices() -> list[dict]:
    """Get list of connected devices."""
    result = run_adb(["devices", "-l"])
    if result.returncode != 0:
        return []

    devices = []
    for line in result.stdout.strip().split("\n")[1:]:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            device = {"serial": parts[0]}
            # Parse additional info
            for part in parts[2:]:
                if ":" in part:
                    key, value = part.split(":", 1)
                    device[key] = value
            devices.append(device)
    return devices


def main() -> int:
    """Check for connected emulator."""
    print()
    print("=" * 60)
    print("Emulator Connection Check")
    print("=" * 60)
    print()

    devices = get_connected_devices()

    if not devices:
        print("  [ERROR] No devices connected.")
        print()
        print("  Make sure Genymotion is running with an Android device.")
        print("  Run 'adb devices' to verify.")
        print()
        return 1

    print(f"  Found {len(devices)} device(s):")
    print()
    for device in devices:
        serial = device["serial"]
        model = device.get("model", "unknown")
        print(f"    {serial} ({model})")
    print()

    # Check if frida-server is running
    print("  Checking frida-server...")
    result = run_adb(["shell", "pgrep", "-x", "frida-server"])
    if result.returncode == 0 and result.stdout.strip():
        print("    [OK] frida-server is running")
    else:
        print("    [NOT RUNNING] frida-server")
        print("    Run 'make emulator-frida-setup' to install and start it")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
