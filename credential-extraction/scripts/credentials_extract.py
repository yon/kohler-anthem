#!/usr/bin/env python3
"""Extract credentials (client_id, api_resource) from Kohler Konnect APK.

Usage:
    python3 credentials_extract.py

This script:
1. Decompiles the APK using jadx
2. Extracts client_id and api_resource from MSAL config
3. Saves results to .build/secrets.json
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
APK_PATH = PROJECT_DIR / "kohler-konnect-3.0.1-apk" / "base.apk"
BUILD_DIR = PROJECT_DIR / ".build"
DECOMPILED_DIR = BUILD_DIR / "decompiled"
SECRETS_FILE = BUILD_DIR / "secrets.json"

# Import the extraction helper
sys.path.insert(0, str(SCRIPT_DIR))
from credentials_extract_from_apk import find_in_resources, find_msal_config  # noqa: E402


def check_prerequisites() -> bool:
    """Check that required tools and files are available."""
    if not shutil.which("jadx"):
        print("  ERROR: jadx not found. Run 'make deps' to install.")
        return False

    if not APK_PATH.exists():
        print(f"  ERROR: APK not found at {APK_PATH}")
        print("  Run 'make apk-download' first.")
        return False

    return True


def decompile_apk() -> bool:
    """Decompile the APK using jadx."""
    print("  Decompiling APK with jadx...")
    print(f"    Input: {APK_PATH}")
    print(f"    Output: {DECOMPILED_DIR}")
    print()

    # Create build directory
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old decompiled directory if it exists
    if DECOMPILED_DIR.exists():
        shutil.rmtree(DECOMPILED_DIR)

    # Run jadx
    try:
        result = subprocess.run(
            ["jadx", "--quiet", "-d", str(DECOMPILED_DIR), str(APK_PATH)],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        if result.returncode != 0 and not DECOMPILED_DIR.exists():
            print(f"  ERROR: jadx failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("  ERROR: jadx timed out (>5 minutes)")
        return False
    except Exception as e:
        print(f"  ERROR: Failed to run jadx: {e}")
        return False

    return True


def extract_credentials() -> dict:
    """Extract credentials from the decompiled APK."""
    print("  Extracting credentials...")

    # Try resources first (faster)
    results = find_in_resources(DECOMPILED_DIR)

    # Fall back to full search if needed
    if not results["client_id"] or not results["api_resource"]:
        print("    Searching all files (this may take a moment)...")
        full_results = find_msal_config(DECOMPILED_DIR)
        if not results["client_id"]:
            results["client_id"] = full_results["client_id"]
        if not results["api_resource"]:
            results["api_resource"] = full_results["api_resource"]

    return results


def main() -> int:
    """Extract credentials from the APK."""
    print()
    print("=" * 60)
    print("Credential Extraction from APK")
    print("=" * 60)
    print()

    # Check prerequisites
    if not check_prerequisites():
        return 1

    # Decompile APK
    if not decompile_apk():
        return 1

    # Extract credentials
    results = extract_credentials()
    print()

    # Report results
    found_all = True

    if results["client_id"]:
        print(f"  client_id: {results['client_id']}")
    else:
        print("  client_id: NOT FOUND")
        found_all = False

    if results["api_resource"]:
        print(f"  api_resource: {results['api_resource']}")
    else:
        print("  api_resource: NOT FOUND")
        found_all = False

    print()

    # Save results
    SECRETS_FILE.write_text(json.dumps(results, indent=2))
    print(f"  Saved to: {SECRETS_FILE}")
    print()

    if not found_all:
        print("  WARNING: Some credentials were not found.")
        print("  You may need to search the decompiled APK manually:")
        print(f"    grep -r 'client_id' {DECOMPILED_DIR}")
        print()
        return 1

    print("  Next step: make apim-capture")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
