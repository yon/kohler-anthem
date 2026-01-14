#!/usr/bin/env python3
"""Download and install frida-server on Android emulator.

Usage:
    python3 frida_setup.py

This script:
1. Detects the emulator architecture
2. Downloads the matching frida-server from GitHub
3. Pushes it to the emulator and starts it
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# Frida GitHub releases API
FRIDA_RELEASES_URL = "https://api.github.com/repos/frida/frida/releases/latest"

# User agent
USER_AGENT = "kohler-anthem-setup"


def run_adb(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run an adb command."""
    return subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def check_adb_connection() -> bool:
    """Check if adb can connect to a device."""
    result = run_adb(["devices"], check=False)
    if result.returncode != 0:
        return False

    # Parse output to find connected devices
    lines = result.stdout.strip().split("\n")
    return any("\tdevice" in line for line in lines[1:])


def get_device_arch() -> str | None:
    """Get the CPU architecture of the connected device."""
    result = run_adb(["shell", "getprop", "ro.product.cpu.abi"], check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_frida_server_url(arch: str) -> tuple[str, str] | None:
    """Get the download URL for frida-server matching the architecture."""
    # Map Android ABIs to Frida naming
    arch_map = {
        "arm64-v8a": "arm64",
        "armeabi-v7a": "arm",
        "x86_64": "x86_64",
        "x86": "x86",
    }

    frida_arch = arch_map.get(arch)
    if not frida_arch:
        return None

    # Fetch latest release info
    try:
        request = urllib.request.Request(
            FRIDA_RELEASES_URL,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.loads(response.read().decode())
    except Exception as e:
        print(f"  ERROR: Failed to fetch Frida release info: {e}")
        return None

    # Find the frida-server asset for this architecture
    target_name = f"frida-server-{release['tag_name'].lstrip('v')}-android-{frida_arch}.xz"

    for asset in release.get("assets", []):
        if asset["name"] == target_name:
            return asset["browser_download_url"], release["tag_name"]

    return None


def download_and_extract(url: str, output_path: Path) -> bool:
    """Download and extract frida-server."""
    try:
        import lzma

        print(f"  Downloading from: {url}")

        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            compressed_data = response.read()

        print("  Extracting...")
        decompressed_data = lzma.decompress(compressed_data)

        output_path.write_bytes(decompressed_data)
        return True

    except ImportError:
        print("  ERROR: lzma module not available")
        print("  Try: brew install xz && pip3 install backports.lzma")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def install_frida_server(local_path: Path) -> bool:
    """Push frida-server to the emulator and set it up."""
    remote_path = "/data/local/tmp/frida-server"

    print(f"  Pushing to emulator: {remote_path}")
    result = run_adb(["push", str(local_path), remote_path], check=False)
    if result.returncode != 0:
        print(f"  ERROR: Failed to push frida-server: {result.stderr}")
        return False

    print("  Setting permissions...")
    run_adb(["shell", "chmod", "755", remote_path], check=False)

    return True


def start_frida_server() -> bool:
    """Start frida-server on the emulator."""
    print("  Starting frida-server...")

    # Kill any existing instance
    run_adb(["shell", "pkill", "-9", "frida-server"], check=False)

    # Try to get root
    run_adb(["root"], check=False)

    # Start frida-server in background
    # Using shell to run in background
    subprocess.Popen(
        ["adb", "shell", "/data/local/tmp/frida-server", "&"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait a moment and check if it's running
    import time

    time.sleep(2)

    result = run_adb(["shell", "pgrep", "-x", "frida-server"], check=False)
    if result.returncode == 0 and result.stdout.strip():
        return True

    print("  WARNING: frida-server may not have started.")
    print("  Try manually: adb shell /data/local/tmp/frida-server &")
    return False


def main() -> int:
    """Set up frida-server on the emulator."""
    print()
    print("=" * 60)
    print("Frida Server Setup")
    print("=" * 60)
    print()

    # Check adb
    if not shutil.which("adb"):
        print("  ERROR: adb not found. Run 'make deps' to install.")
        return 1

    # Check device connection
    print("  Checking for connected device...")
    if not check_adb_connection():
        print("  ERROR: No device connected.")
        print()
        print("  Make sure Genymotion is running with an Android device.")
        print("  The device should appear in: adb devices")
        return 1

    # Get architecture
    print("  Detecting device architecture...")
    arch = get_device_arch()
    if not arch:
        print("  ERROR: Could not determine device architecture.")
        return 1
    print(f"    Architecture: {arch}")

    # Get download URL
    print("  Finding latest frida-server...")
    url_info = get_frida_server_url(arch)
    if not url_info:
        print(f"  ERROR: No frida-server available for architecture: {arch}")
        return 1

    download_url, version = url_info
    print(f"    Version: {version}")
    print()

    # Download and extract
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / "frida-server"

        if not download_and_extract(download_url, local_path):
            return 1

        # Install on device
        print()
        if not install_frida_server(local_path):
            return 1

    # Start server
    print()
    if not start_frida_server():
        return 1

    print()
    print("  Frida server is running!")
    print()
    print("  Next step: make apim-capture")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
