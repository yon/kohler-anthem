#!/usr/bin/env python3
"""Download and install frida-server on the Android emulator.

What this does:
  1. Detect the device ABI via `getprop ro.product.cpu.abi`.
  2. Look up the GitHub release whose tag matches the installed `frida-tools`
     version (so the agent and server are version-locked — major-version
     drift between the two is the #1 historical failure mode).
  3. Compute the SHA-256 of the matching `frida-server-<ver>-android-<abi>`
     binary. If a binary with that hash is already pushed to the device, skip
     the re-push.
  4. Otherwise download, decompress (xz), push to `/data/local/tmp/frida-server`,
     chmod 755, start it detached with `nohup … &`.
  5. Verify it's actually running.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import find_adb, find_frida, run

GITHUB_API = "https://api.github.com/repos/frida/frida"
USER_AGENT = "kohler-anthem-harness"
REMOTE_PATH = "/data/local/tmp/frida-server"

ABI_MAP = {
    "arm64-v8a": "arm64",
    "armeabi-v7a": "arm",
    "x86_64": "x86_64",
    "x86": "x86",
}


def check_device_connected(adb: str) -> bool:
    result = run([adb, "devices"])
    if result.returncode != 0:
        return False
    return any("\tdevice" in line for line in result.stdout.strip().splitlines()[1:])


def device_abi(adb: str) -> str | None:
    result = run([adb, "shell", "getprop", "ro.product.cpu.abi"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def installed_frida_version(frida_cli: str) -> str | None:
    """Return the frida-tools version on the host (drives which server we want)."""
    result = run([frida_cli, "--version"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def github_release_for_version(version: str) -> dict:
    """Look up the GitHub release for the given frida version (`16.x.y` style)."""
    url = f"{GITHUB_API}/releases/tags/{version}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def github_latest_release() -> dict:
    url = f"{GITHUB_API}/releases/latest"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def find_asset(release: dict, abi: str) -> tuple[str, str] | None:
    """Return (download_url, asset_name) for the frida-server matching the given Android ABI."""
    frida_arch = ABI_MAP.get(abi)
    if not frida_arch:
        return None
    target = f"frida-server-{release['tag_name'].lstrip('v')}-android-{frida_arch}.xz"
    for asset in release.get("assets", []):
        if asset["name"] == target:
            return asset["browser_download_url"], target
    return None


def download_and_decompress(url: str, dest: Path) -> bool:
    print(f"  Downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            compressed = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  ERROR: download failed: {exc}")
        return False
    print(f"  Decompressing ({len(compressed)} bytes)...")
    dest.write_bytes(lzma.decompress(compressed))
    return True


def remote_md5(adb: str, path: str) -> str | None:
    result = run([adb, "shell", "md5sum", path])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().split()[0]


def local_md5(path: Path) -> str:
    h = hashlib.md5()  # md5 not for security — matches `adb shell md5sum`
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def push_frida_server(adb: str, local_path: Path) -> bool:
    print(f"  Pushing → {REMOTE_PATH}")
    result = run([adb, "push", str(local_path), REMOTE_PATH])
    if result.returncode != 0:
        print(f"  ERROR: adb push failed: {result.stderr.strip()}")
        return False
    chmod = run([adb, "shell", "chmod", "755", REMOTE_PATH])
    if chmod.returncode != 0:
        print(f"  WARNING: chmod failed: {chmod.stderr.strip()}")
    return True


def start_frida_server(adb: str) -> bool:
    """Start frida-server detached, using setsid + nohup so it survives the adb shell."""
    print("  Starting frida-server...")
    run([adb, "shell", "pkill", "-9", "frida-server"])
    run([adb, "root"])
    time.sleep(1)
    # The literal `&` argv to adb shell doesn't background. Use setsid + nohup so the
    # frida-server process detaches and isn't killed when this adb shell exits.
    run(
        [
            adb,
            "shell",
            "nohup setsid " + REMOTE_PATH + " >/dev/null 2>&1 </dev/null &",
        ]
    )

    # Poll a few times — the server takes ~1-2s to bind
    for _ in range(10):
        time.sleep(0.5)
        result = run([adb, "shell", "pgrep", "-x", "frida-server"])
        if result.returncode == 0 and result.stdout.strip():
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download/push even if the device already has the right server.",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Frida Server Setup")
    print("=" * 60)
    print()

    adb = find_adb()
    if not adb:
        print("  ERROR: adb not found. Run `make deps`.")
        return 1

    if not check_device_connected(adb):
        print("  ERROR: No device connected. Run `make emulator-setup` first.")
        return 1

    abi = device_abi(adb)
    if not abi:
        print("  ERROR: Could not determine device ABI.")
        return 1
    print(f"  Device ABI: {abi}")

    frida_cli = find_frida()
    if not frida_cli:
        print("  ERROR: frida-tools not installed. Run `make deps`.")
        return 1
    version = installed_frida_version(frida_cli)
    if not version:
        print("  ERROR: could not determine installed frida-tools version")
        return 1
    print(f"  frida-tools version: {version}")

    # Try to get the matching server release; if exact-tag fetch 404s, fall back to "latest"
    try:
        release = github_release_for_version(version)
        print(f"  Found matching GitHub release: {release['tag_name']}")
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"  WARNING: no exact-match release for {version} ({exc}); using 'latest'")
        try:
            release = github_latest_release()
        except (urllib.error.URLError, TimeoutError) as exc2:
            print(f"  ERROR: GitHub lookup failed: {exc2}")
            return 1

    asset = find_asset(release, abi)
    if not asset:
        tag = release['tag_name']
        print(f"  ERROR: no frida-server-android-* asset for ABI {abi} in release {tag}")
        return 1
    url, asset_name = asset
    print(f"  Asset: {asset_name}")

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / "frida-server"
        if not download_and_decompress(url, local_path):
            return 1

        local_hash = local_md5(local_path)
        existing_hash = remote_md5(adb, REMOTE_PATH)
        if existing_hash and existing_hash == local_hash and not args.force:
            print("  frida-server on device matches local hash; skipping push.")
        else:
            if not push_frida_server(adb, local_path):
                return 1

    if not start_frida_server(adb):
        print("  ERROR: frida-server did not start. Check `adb shell pgrep -x frida-server`.")
        return 1

    print()
    print("  frida-server is running.")
    print()
    print("  Next step: make emulator-apk-install")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
