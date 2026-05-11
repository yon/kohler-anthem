#!/usr/bin/env python3
"""Check if required tools are installed for credential extraction.

Usage:
    python3 tools_check.py

Checks for: adb, frida, jadx, jq, python3
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import (
    find_adb,
    find_frida,
    find_mitmdump,
)

TOOLS = [
    ("adb", "Android Debug Bridge", "brew install --cask android-platform-tools", find_adb),
    ("frida", "Frida instrumentation", ".venv/bin/pip install frida-tools", find_frida),
    ("jadx", "APK decompiler", "brew install jadx", lambda: shutil.which("jadx")),
    ("jq", "JSON processor", "brew install jq", lambda: shutil.which("jq")),
    ("mitmdump", "mitmproxy CLI", "brew install mitmproxy", find_mitmdump),
    ("apktool", "APK patcher", "brew install apktool", lambda: shutil.which("apktool")),
    ("sdkmanager", "Android SDK manager", "brew install --cask android-commandlinetools",
     lambda: shutil.which("sdkmanager")),
    ("openssl", "OpenSSL CLI", "(macOS includes this by default)", lambda: shutil.which("openssl")),
]


def check_python_version() -> bool:
    """Check Python version >= 3.9."""
    return sys.version_info >= (3, 9)


def main() -> int:
    """Check all required tools and report status."""
    print()
    print("=" * 60)
    print("Credential Extraction - Tool Check")
    print("=" * 60)
    print()

    missing = []

    # Check Python version
    if check_python_version():
        print(f"  [OK] Python {sys.version_info.major}.{sys.version_info.minor}")
    else:
        print(f"  [MISSING] Python 3.9+ (found {sys.version_info.major}.{sys.version_info.minor})")
        missing.append(("python3.9+", "Python 3.9 or later", "brew install python@3.11"))

    # Check each tool
    for name, description, install_cmd, finder in TOOLS:
        path = finder()
        if path:
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = result.stdout.strip().split("\n")[0][:40]
                print(f"  [OK] {name}: {version}")
            except Exception:
                print(f"  [OK] {name}")
        else:
            print(f"  [MISSING] {name} - {description}")
            missing.append((name, description, install_cmd))

    print()

    if missing:
        print("-" * 60)
        print("Missing tools - install with:")
        print("-" * 60)
        print()
        print("  make deps")
        print()
        print("Or install individually:")
        print()
        for _name, _desc, install_cmd in missing:
            print(f"  {install_cmd}")
        print()
        return 1

    print("All tools installed!")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
