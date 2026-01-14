#!/usr/bin/env python3
"""Check if required tools are installed for credential extraction.

Usage:
    python3 tools_check.py

Checks for: adb, frida, jadx, jq, python3
"""

import shutil
import subprocess
import sys

TOOLS = [
    ("adb", "Android Debug Bridge", "brew install --cask android-platform-tools"),
    ("frida", "Frida instrumentation", "pip3 install frida-tools"),
    ("jadx", "APK decompiler", "brew install jadx"),
    ("jq", "JSON processor", "brew install jq"),
]


def check_tool(name: str) -> bool:
    """Check if a tool is available in PATH."""
    return shutil.which(name) is not None


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
    for name, description, install_cmd in TOOLS:
        if check_tool(name):
            # Get version if possible
            try:
                result = subprocess.run(
                    [name, "--version"],
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
