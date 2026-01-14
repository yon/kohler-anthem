#!/usr/bin/env python3
"""Generate kohler-credentials.yaml for Kohler Anthem integration.

Reads extracted secrets from APK and Frida capture, updates the credentials
file while preserving any user-entered values (username/password).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
BUILD_DIR = PROJECT_DIR / ".build"
CREDENTIALS_FILE = PROJECT_DIR / "kohler-credentials.yaml"
EXAMPLE_FILE = PROJECT_DIR / "kohler-credentials.yaml.example"
SECRETS_FILE = BUILD_DIR / "secrets.json"
CAPTURED_FILE = BUILD_DIR / "captured_apim_key.json"

# Placeholder for user to fill in
PLACEHOLDER = "YOUR_VALUE_HERE"


def load_extracted_secrets() -> dict:
    """Load secrets extracted from APK."""
    if SECRETS_FILE.exists():
        try:
            return json.loads(SECRETS_FILE.read_text())
        except Exception:
            pass
    return {}


def load_captured_secrets() -> dict:
    """Load secrets captured via Frida."""
    if CAPTURED_FILE.exists():
        try:
            return json.loads(CAPTURED_FILE.read_text())
        except Exception:
            pass
    return {}


def load_existing_credentials() -> dict:
    """Load existing credentials file to preserve user values."""
    if CREDENTIALS_FILE.exists():
        try:
            creds = {}
            for line in CREDENTIALS_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and ":" in line:
                    key, value = line.split(":", 1)
                    creds[key.strip()] = value.strip()
            return creds
        except Exception:
            pass
    return {}


def main() -> int:
    print()
    print("=" * 60)
    print("Kohler Anthem Credentials Generator")
    print("=" * 60)
    print()

    # Copy from example if credentials file doesn't exist
    if not CREDENTIALS_FILE.exists():
        if EXAMPLE_FILE.exists():
            shutil.copy(EXAMPLE_FILE, CREDENTIALS_FILE)
            os.chmod(CREDENTIALS_FILE, 0o600)
            print(f"  Created {CREDENTIALS_FILE.name} from example")
            print()
        else:
            print(f"  ERROR: {EXAMPLE_FILE.name} not found")
            return 1

    # Load existing credentials (preserves user-entered values)
    existing = load_existing_credentials()

    # Load extracted/captured secrets
    extracted = load_extracted_secrets()
    captured = load_captured_secrets()

    credentials = {}
    missing = []

    # APK secrets
    if extracted.get("client_id"):
        credentials["kohler_client_id"] = extracted["client_id"]
        print(f"  [OK] kohler_client_id: {extracted['client_id'][:8]}...")
    else:
        credentials["kohler_client_id"] = existing.get("kohler_client_id", PLACEHOLDER)
        if credentials["kohler_client_id"] == PLACEHOLDER:
            missing.append("kohler_client_id")
            print("  [MISSING] kohler_client_id - run 'make credentials-extract'")
        else:
            print(f"  [OK] kohler_client_id: {credentials['kohler_client_id'][:8]}...")

    if extracted.get("api_resource"):
        credentials["kohler_api_resource"] = extracted["api_resource"]
        print(f"  [OK] kohler_api_resource: {extracted['api_resource'][:8]}...")
    else:
        credentials["kohler_api_resource"] = existing.get("kohler_api_resource", PLACEHOLDER)
        if credentials["kohler_api_resource"] == PLACEHOLDER:
            missing.append("kohler_api_resource")
            print("  [MISSING] kohler_api_resource - run 'make credentials-extract'")
        else:
            print(f"  [OK] kohler_api_resource: {credentials['kohler_api_resource'][:8]}...")

    # APIM key (captured via Frida)
    if captured.get("apim_key"):
        credentials["kohler_apim_key"] = captured["apim_key"]
        print(f"  [OK] kohler_apim_key: {captured['apim_key'][:8]}...")
    else:
        credentials["kohler_apim_key"] = existing.get("kohler_apim_key", PLACEHOLDER)
        if credentials["kohler_apim_key"] == PLACEHOLDER:
            missing.append("kohler_apim_key")
            print("  [MISSING] kohler_apim_key - run 'make emulator-apim-capture'")
        else:
            print(f"  [OK] kohler_apim_key: {credentials['kohler_apim_key'][:8]}...")

    # User credentials (preserve existing or use placeholder)
    credentials["kohler_username"] = existing.get("kohler_username", PLACEHOLDER)
    credentials["kohler_password"] = existing.get("kohler_password", PLACEHOLDER)

    if credentials["kohler_username"] == PLACEHOLDER:
        print(f"  [TODO] kohler_username: {PLACEHOLDER}")
    else:
        print(f"  [OK] kohler_username: {credentials['kohler_username']}")

    if credentials["kohler_password"] == PLACEHOLDER:
        print(f"  [TODO] kohler_password: {PLACEHOLDER}")
    else:
        print("  [OK] kohler_password: ********")

    print()

    # Write YAML (alphabetized keys)
    yaml_content = "# Kohler Anthem Credentials\n"
    yaml_content += "#\n"
    yaml_content += "# KEEP THIS FILE SECRET - it contains your credentials!\n"
    yaml_content += "# This file is gitignored and should never be committed.\n\n"

    for key in sorted(credentials.keys()):
        yaml_content += f"{key}: {credentials[key]}\n"

    CREDENTIALS_FILE.write_text(yaml_content)
    os.chmod(CREDENTIALS_FILE, 0o600)

    print(f"  Updated: {CREDENTIALS_FILE.name}")
    print()

    if missing:
        print(f"  {len(missing)} value(s) still need extraction")
        print()

    missing_user_creds = (
        credentials["kohler_username"] == PLACEHOLDER
        or credentials["kohler_password"] == PLACEHOLDER
    )
    if missing_user_creds:
        print("  Edit kohler-credentials.yaml to fill in:")
        if credentials["kohler_username"] == PLACEHOLDER:
            print("    - kohler_username (your Kohler account email)")
        if credentials["kohler_password"] == PLACEHOLDER:
            print("    - kohler_password (your Kohler account password)")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
