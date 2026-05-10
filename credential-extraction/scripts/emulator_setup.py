#!/usr/bin/env python3
"""Set up the Genymotion `KohlerExtraction` emulator.

Creates and starts a Genymotion virtual device with the harness's required
specs. Requires Genymotion Desktop (30-day trial or licensed) — the free
Personal-use tier rejects `gmtool admin create` with "A license is required".

`gmtool admin templates` was removed in Genymotion 3.10, so this script
just attempts `admin create` with the known template names; if the template
isn't recognized, it surfaces the gmtool error verbatim and offers a fallback
list of names that have historically worked.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import adb_device_connected, find_gmtool, run

DEVICE_NAME = "KohlerExtraction"
DEVICE_RAM_MB = 4096
DEVICE_CPU = 4
# (hwprofile, android_version) tried in order
TEMPLATES = [
    ("Samsung Galaxy S10", "11.0"),
    ("Google Pixel 5", "11.0"),
    ("Google Pixel 6", "12.0"),
    ("Samsung Galaxy S9", "10.0"),
]


def run_gmtool(gmtool: str, args: list[str]):
    return run([gmtool, *args], timeout=300)


def device_exists(gmtool: str, name: str) -> bool:
    result = run_gmtool(gmtool, ["admin", "list"])
    return result.returncode == 0 and name in result.stdout


def device_running(gmtool: str, name: str) -> bool:
    result = run_gmtool(gmtool, ["admin", "list", "--running"])
    return result.returncode == 0 and name in result.stdout


def try_create(gmtool: str) -> bool:
    """Try each template until one works. Return True on success."""
    last_err = ""
    for hwprofile, android in TEMPLATES:
        print(f"  Trying template: {hwprofile!r} / Android {android}")
        result = run_gmtool(
            gmtool,
            [
                "admin", "create", hwprofile, android, DEVICE_NAME,
                "--nbcpu", str(DEVICE_CPU),
                "--ram", str(DEVICE_RAM_MB),
            ],
        )
        if result.returncode == 0:
            print("  ✓ Device created")
            return True
        err = (result.stderr or result.stdout).strip()
        print(f"    failed: {err}")
        last_err = err
        if "license is required" in err.lower():
            print()
            print("  Personal-use license cannot create devices. You need the")
            print("  Genymotion Desktop 30-day trial. Sign in at:")
            print("    https://www.genymotion.com/account/login/")
            print("  and put credentials in /Volumes/ring/env/kohler.env.")
            return False
    print()
    print("  All known templates failed.")
    print(f"  Last gmtool error: {last_err}")
    print()
    print("  Open Genymotion.app GUI → '+ Add device' to see what templates")
    print("  your license has access to, then add a matching (hwprofile, android)")
    print("  pair to TEMPLATES in emulator_setup.py.")
    return False


def start_device(gmtool: str) -> bool:
    print(f"  Starting device '{DEVICE_NAME}'...")
    result = run_gmtool(gmtool, ["admin", "start", DEVICE_NAME])
    if result.returncode != 0:
        print(f"  ERROR: {(result.stderr or result.stdout).strip()}")
        return False
    return True


def wait_for_adb(timeout: int = 90) -> bool:
    print("  Waiting for adb connection...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if adb_device_connected():
            print("  ✓ Device connected via adb")
            return True
        time.sleep(2)
    print("  ERROR: Timed out waiting for adb connection")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete the existing KohlerExtraction device and recreate it.",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Genymotion Emulator Setup")
    print("=" * 60)
    print()

    gmtool = find_gmtool()
    if not gmtool:
        print("  ERROR: gmtool not found.")
        print("  Install with: brew install --cask genymotion")
        return 1
    print(f"  Found gmtool: {gmtool}")
    print()

    if args.recreate and device_exists(gmtool, DEVICE_NAME):
        if device_running(gmtool, DEVICE_NAME):
            run_gmtool(gmtool, ["admin", "stop", DEVICE_NAME])
            time.sleep(2)
        print(f"  Deleting existing '{DEVICE_NAME}'...")
        result = run_gmtool(gmtool, ["admin", "delete", DEVICE_NAME])
        if result.returncode != 0:
            print(f"  WARNING: delete failed: {(result.stderr or result.stdout).strip()}")

    if device_exists(gmtool, DEVICE_NAME):
        print(f"  Device '{DEVICE_NAME}' already exists.")
    else:
        if not try_create(gmtool):
            return 1
        print()

    if not device_running(gmtool, DEVICE_NAME):
        if not start_device(gmtool):
            return 1
        print()
        if not wait_for_adb():
            return 1

    print()
    print("  Emulator setup complete.")
    print()
    print("  Next step: make emulator-frida-setup")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
