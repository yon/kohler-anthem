#!/usr/bin/env python3
"""Install Kohler Konnect APK on Android emulator.

By default, reads from `credential-extraction/konnect-apk/` — the canonical
git-LFS-tracked APK that ships with the repo. Override with `--apk-dir` if
you want to install something else (e.g. a freshly-downloaded update that
hasn't been promoted yet).

Pre-flight checks the device's ABI against the APKs in the source dir and
fails fast if an ABI-specific split is missing (Genymotion devices are
arm64-v8a on Apple Silicon, x86_64 on Intel — installing an armeabi-v7a-only
bundle would fail with INSTALL_FAILED_NO_MATCHING_ABIS).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import EXTRACTION_DIR, find_adb, run

REPO_APK_DIR = EXTRACTION_DIR / "konnect-apk"
PACKAGE_NAME = "com.kohler.hermoth"

# ABI suffix mapping for the typical Konnect split-APK names
ABI_SPLIT_SUFFIX = {
    "arm64-v8a": "arm64_v8a",
    "armeabi-v7a": "armeabi_v7a",
    "x86_64": "x86_64",
    "x86": "x86",
}


def resolve_apk_dir(override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return REPO_APK_DIR


def run_adb(adb: str, args: list[str]):
    return run([adb, *args])


def check_device_connected(adb: str) -> bool:
    result = run_adb(adb, ["devices"])
    if result.returncode != 0:
        return False
    return any("\tdevice" in line for line in result.stdout.strip().splitlines()[1:])


def device_abi(adb: str) -> str | None:
    result = run_adb(adb, ["shell", "getprop", "ro.product.cpu.abi"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def get_installed_version(adb: str) -> str | None:
    result = run_adb(adb, ["shell", "dumpsys", "package", PACKAGE_NAME])
    if result.returncode != 0:
        return None
    for line in result.stdout.split("\n"):
        if "versionName=" in line:
            return line.split("versionName=")[1].strip()
    return None


def uninstall_app(adb: str) -> bool:
    return run_adb(adb, ["uninstall", PACKAGE_NAME]).returncode == 0


def check_abi_match(apk_dir: Path, abi: str | None) -> tuple[bool, str]:
    """Return (ok, message)."""
    if not abi:
        return True, "device ABI unknown — skipping check"
    suffix = ABI_SPLIT_SUFFIX.get(abi)
    if not suffix:
        return True, f"unknown ABI {abi!r} — skipping check"
    apks = list(apk_dir.glob("*.apk"))
    if not apks:
        return False, f"no APKs in {apk_dir}"
    # Two naming conventions are common:
    #   - APKPure XAPK bundles use `config.<abi>.apk`
    #   - Google Play / Aurora bundles use `split_config.<abi>.apk` (our checked-in one)
    abi_splits = [
        p for p in apks
        if (p.name.startswith("config.") or p.name.startswith("split_config."))
        and "_" in p.stem
    ]
    if not abi_splits:
        # No ABI-specific splits found at all — base APK probably contains all ABIs
        return True, "no ABI-specific splits found; assuming base APK is universal"
    matching = [p for p in abi_splits if suffix in p.name]
    if not matching:
        names = ", ".join(sorted(p.name for p in abi_splits))
        return False, f"device ABI is {abi} but bundle has only: {names}"
    return True, f"device ABI {abi} matches {matching[0].name}"


def install_split_apks(adb: str, apk_dir: Path) -> bool:
    apk_files = sorted(apk_dir.glob("*.apk"))
    if not apk_files:
        print(f"  ERROR: No APK files found in {apk_dir}")
        return False

    print("  Installing split APKs:")
    for apk in apk_files:
        print(f"    - {apk.name}")

    cmd = ["install-multiple"] + [str(apk) for apk in apk_files]
    result = run_adb(adb, cmd)

    if result.returncode != 0 and "INSTALL_FAILED_VERSION_DOWNGRADE" in result.stderr:
        print()
        print("  Version downgrade detected. Uninstalling existing app...")
        if uninstall_app(adb):
            print("  Retrying install...")
            result = run_adb(adb, cmd)
        else:
            print("  ERROR: Failed to uninstall existing app")
            return False

    if (
        result.returncode != 0
        and "INSTALL_FAILED_NO_MATCHING_ABIS" in result.stderr
    ):
        abi = device_abi(adb)
        print(f"  ERROR: ABI mismatch. Device ABI: {abi}.")
        print(f"  The fetched APK doesn't include a split for {abi}.")
        print("  Consider --apk-dir pointing at a build with the right ABI split.")
        return False

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apk-dir",
        default=None,
        help="Directory containing split APKs (defaults to <cache>/konnect-apk/latest).",
    )
    args = parser.parse_args(argv)

    adb = find_adb()
    if not adb:
        print("  ERROR: adb not found. Run `make deps`.")
        return 1

    apk_dir = resolve_apk_dir(args.apk_dir)

    print()
    print("=" * 60)
    print("Kohler Konnect APK Installation")
    print("=" * 60)
    print()
    print(f"  APK source: {apk_dir}")

    if not check_device_connected(adb):
        print("  ERROR: No device connected.")
        print("  Run 'make emulator-check' to verify connection.")
        return 1

    abi = device_abi(adb)
    print(f"  Device ABI: {abi or 'unknown'}")
    ok, msg = check_abi_match(apk_dir, abi)
    if not ok:
        print(f"  ERROR: {msg}")
        return 1
    print(f"  ABI check: {msg}")

    installed_version = get_installed_version(adb)
    if installed_version:
        print(f"  Currently installed: v{installed_version}")
    print()

    if not install_split_apks(adb, apk_dir):
        return 1

    print()
    print("  APK installed successfully!")
    new_version = get_installed_version(adb)
    if new_version:
        print(f"  Installed version: v{new_version}")
    print()
    print("  Next step: make emulator-mitmproxy-setup")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
