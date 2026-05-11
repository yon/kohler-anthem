#!/usr/bin/env python3
"""Create + start the KohlerExtraction Android Virtual Device.

The harness needs a rooted Android 11 device with a writable /system partition
(to drop the mitmproxy CA into /system/etc/security/cacerts/). The Google APIs
system image gives us `adb root` for free; Android 11 matches the version
Konnect was last verified against; arm64-v8a matches the in-repo APK splits.

Idempotent:
  * SDK component install is a no-op when components already exist.
  * AVD creation is a no-op if the AVD already exists.
  * Emulator launch is a no-op if a device is already on adb.

Required SDK components (auto-installed via sdkmanager if missing):
  * platform-tools
  * emulator
  * system-images;android-30;google_apis;arm64-v8a
  * build-tools;35.0.0
  * platforms;android-30

The script never prompts. License acceptance is piped non-interactively.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import HarnessError, adb_device_connected, find_adb, run

DEVICE_NAME = "KohlerExtraction"

# Pixel 5 hardware profile + Android 11 / Google APIs / arm64
DEVICE_HARDWARE = "pixel_5"
ANDROID_API = "30"
SYSTEM_IMAGE = f"system-images;android-{ANDROID_API};google_apis;arm64-v8a"
PLATFORM = f"platforms;android-{ANDROID_API}"
BUILD_TOOLS = "build-tools;35.0.0"
REQUIRED_COMPONENTS = (
    "platform-tools",
    "emulator",
    SYSTEM_IMAGE,
    BUILD_TOOLS,
)

# Standard brew-cask install path. If the user installed the SDK elsewhere,
# they can set $ANDROID_HOME / $ANDROID_SDK_ROOT and we'll honor it.
DEFAULT_SDK_ROOT = Path("/opt/homebrew/share/android-commandlinetools")
DEFAULT_JAVA_HOME = Path("/opt/homebrew/opt/openjdk")


def _resolve_sdk_root() -> Path:
    for candidate in (
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        str(DEFAULT_SDK_ROOT),
    ):
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    raise HarnessError(
        "Android SDK not found. Install with:\n"
        "  brew install --cask android-commandlinetools\n"
        "Or export ANDROID_HOME to point at an existing install."
    )


def _resolve_java_home() -> Path:
    for candidate in (os.environ.get("JAVA_HOME"), str(DEFAULT_JAVA_HOME)):
        if candidate and (Path(candidate) / "bin" / "java").is_file():
            return Path(candidate)
    raise HarnessError(
        "JDK not found. Install with:\n"
        "  brew install openjdk\n"
        "Or export JAVA_HOME to point at an existing JDK."
    )


def _sdk_env(sdk_root: Path, java_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ANDROID_HOME"] = str(sdk_root)
    env["ANDROID_SDK_ROOT"] = str(sdk_root)
    env["JAVA_HOME"] = str(java_home)
    env["PATH"] = (
        f"{java_home}/bin:"
        f"{sdk_root}/cmdline-tools/latest/bin:"
        f"{sdk_root}/platform-tools:"
        f"{sdk_root}/emulator:"
        + env.get("PATH", "")
    )
    return env


def _sdkmanager(sdk_root: Path) -> Path:
    path = sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    if not path.is_file():
        raise HarnessError(f"sdkmanager not found at {path}")
    return path


def _avdmanager(sdk_root: Path) -> Path:
    path = sdk_root / "cmdline-tools" / "latest" / "bin" / "avdmanager"
    if not path.is_file():
        raise HarnessError(f"avdmanager not found at {path}")
    return path


def _emulator(sdk_root: Path) -> Path:
    path = sdk_root / "emulator" / "emulator"
    if not path.is_file():
        raise HarnessError(
            f"emulator binary not found at {path}. "
            "It should appear after `sdkmanager 'emulator'`."
        )
    return path


def _component_installed(sdk_root: Path, component: str) -> bool:
    """Heuristic: check the on-disk layout instead of shelling out to sdkmanager."""
    rel = component.replace(";", "/")
    return (sdk_root / rel).is_dir()


def install_sdk_components(sdk_root: Path, env: dict[str, str]) -> None:
    """Install only the components that aren't already on disk."""
    missing = [c for c in REQUIRED_COMPONENTS if not _component_installed(sdk_root, c)]
    if not missing:
        print("  ✓ All required SDK components already installed")
        return

    sdkmanager = _sdkmanager(sdk_root)
    print(f"  Installing missing SDK components: {', '.join(missing)}")
    # Accept all licenses non-interactively first.
    yes_stream = "y\n" * 20
    accept = subprocess.run(
        [str(sdkmanager), "--licenses"],
        input=yes_stream,
        text=True,
        env=env,
        capture_output=True,
        timeout=300,
    )
    if accept.returncode != 0:
        print(f"  WARNING: license acceptance returned {accept.returncode}: "
              f"{(accept.stderr or accept.stdout)[:200]}")

    result = subprocess.run(
        [str(sdkmanager), "--install", *missing],
        input=yes_stream,
        text=True,
        env=env,
        capture_output=True,
        timeout=1800,
    )
    if result.returncode != 0:
        raise HarnessError(
            "sdkmanager --install failed:\n"
            f"  stdout: {result.stdout[-400:]}\n"
            f"  stderr: {result.stderr[-400:]}"
        )
    print("  ✓ SDK components installed")


def avd_exists(sdk_root: Path, env: dict[str, str], name: str) -> bool:
    avdmanager = _avdmanager(sdk_root)
    result = subprocess.run(
        [str(avdmanager), "list", "avd", "-c"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 and name in result.stdout.splitlines()


def create_avd(sdk_root: Path, env: dict[str, str], name: str) -> None:
    avdmanager = _avdmanager(sdk_root)
    print(f"  Creating AVD '{name}' (Pixel 5, Android {ANDROID_API}, google_apis arm64-v8a)")
    result = subprocess.run(
        [
            str(avdmanager), "create", "avd",
            "--force",
            "--name", name,
            "--package", SYSTEM_IMAGE,
            "--device", DEVICE_HARDWARE,
        ],
        input="no\n",  # decline custom hardware profile
        text=True,
        env=env,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise HarnessError(
            f"avdmanager create failed: {(result.stderr or result.stdout).strip()}"
        )

    # Tune the AVD config to be friendly for harness work
    avd_dir = Path.home() / ".android" / "avd" / f"{name}.avd"
    cfg = avd_dir / "config.ini"
    if cfg.exists():
        extras = "\n".join([
            "hw.ramSize=4096",
            "vm.heapSize=512",
            "hw.cpu.ncore=4",
            "disk.dataPartition.size=8192M",
        ]) + "\n"
        with cfg.open("a") as fh:
            fh.write(extras)
    print(f"  ✓ AVD '{name}' created")


def emulator_running() -> bool:
    """True if any adb device is connected. Good enough — we only ever run one AVD."""
    return adb_device_connected()


def start_emulator(sdk_root: Path, env: dict[str, str], name: str) -> subprocess.Popen[bytes]:
    emulator = _emulator(sdk_root)
    print(f"  Starting emulator: {emulator}")
    print("  Flags: -writable-system -no-snapshot-load -no-audio -no-boot-anim")
    log_path = Path.home() / "Library" / "Caches" / "kohler-anthem" / "emulator.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("ab")
    log_fh.write(b"\n==== emulator start ====\n")
    proc = subprocess.Popen(
        [
            str(emulator),
            "-avd", name,
            "-writable-system",
            "-no-snapshot-load",
            "-no-audio",
            "-no-boot-anim",
            "-gpu", "swiftshader_indirect",
        ],
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"  Emulator PID: {proc.pid} (log: {log_path})")
    return proc


def wait_for_boot(timeout: int = 240) -> bool:
    adb = find_adb()
    if not adb:
        raise HarnessError("adb not found on PATH")

    print(f"  Waiting up to {timeout}s for emulator to boot...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if adb_device_connected():
            result = run(
                [adb, "shell", "getprop", "sys.boot_completed"],
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip() == "1":
                print("  ✓ Boot complete")
                return True
        time.sleep(3)
    return False


def root_and_remount() -> bool:
    """adb root + remount so /system is writable for the mitmproxy CA install."""
    adb = find_adb()
    if not adb:
        return False
    print("  adb root + remount")
    run([adb, "root"], timeout=15)
    # adb root races with the new adbd starting up
    time.sleep(2)
    run([adb, "wait-for-device"], timeout=30)
    remount = run([adb, "remount"], timeout=30)
    if remount.returncode != 0:
        print(f"  WARNING: adb remount failed: {(remount.stderr or remount.stdout).strip()}")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate the AVD before starting.",
    )
    parser.add_argument(
        "--no-install-sdk",
        action="store_true",
        help="Skip the sdkmanager-install step (assume components are present).",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print(f"AVD setup ({DEVICE_NAME})")
    print("=" * 60)
    print()

    try:
        sdk_root = _resolve_sdk_root()
        java_home = _resolve_java_home()
    except HarnessError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"  ANDROID_HOME: {sdk_root}")
    print(f"  JAVA_HOME:    {java_home}")
    env = _sdk_env(sdk_root, java_home)

    if not args.no_install_sdk:
        try:
            install_sdk_components(sdk_root, env)
        except HarnessError as exc:
            print(f"ERROR: {exc}")
            return 1

    if args.recreate and avd_exists(sdk_root, env, DEVICE_NAME):
        avdmanager = _avdmanager(sdk_root)
        print(f"  Deleting existing AVD '{DEVICE_NAME}'")
        subprocess.run(
            [str(avdmanager), "delete", "avd", "--name", DEVICE_NAME],
            env=env, capture_output=True, text=True, timeout=60,
        )
        # Also kill any in-flight emulator
        avd_dir = Path.home() / ".android" / "avd" / f"{DEVICE_NAME}.avd"
        if avd_dir.exists():
            shutil.rmtree(avd_dir, ignore_errors=True)

    if not avd_exists(sdk_root, env, DEVICE_NAME):
        try:
            create_avd(sdk_root, env, DEVICE_NAME)
        except HarnessError as exc:
            print(f"ERROR: {exc}")
            return 1
    else:
        print(f"  ✓ AVD '{DEVICE_NAME}' already exists")

    if emulator_running():
        print("  ✓ Emulator already running on adb")
    else:
        start_emulator(sdk_root, env, DEVICE_NAME)
        if not wait_for_boot():
            print("  ERROR: emulator did not finish booting in time.")
            return 1

    root_and_remount()

    print()
    print("  AVD setup complete.")
    print("  Next step: make emulator-frida-setup")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
