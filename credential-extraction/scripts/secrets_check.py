#!/usr/bin/env python3
"""Verify the harness env file has all the keys the harness needs.

Exits 0 if all required keys are present + non-empty + not the placeholder
"YOUR_VALUE_HERE". Exits 1 with a clear list of what's missing otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import load_env

REQUIRED_FOR_HARNESS = (
    "GENYMOTION_EMAIL",
    "GENYMOTION_PASSWORD",
    "KOHLER_USERNAME",
    "KOHLER_PASSWORD",
)

REQUIRED_FOR_LIBRARY = (
    "KOHLER_CLIENT_ID",
    "KOHLER_API_RESOURCE",
    "KOHLER_REDIRECT_URI",
    "KOHLER_B2C_AUTHORITY_BASE",
    "KOHLER_B2C_POLICY_SIGNIN",
)

PLACEHOLDER = "YOUR_VALUE_HERE"


def main() -> int:
    print()
    print("=" * 60)
    print("Secrets check")
    print("=" * 60)
    print()

    env = load_env()
    if not env.env_file.exists():
        print(f"  ERROR: env file does not exist: {env.env_file}")
        print("  Run `make secrets-init` then `make secrets-link`.")
        return 1
    if env.env_file.is_symlink() and not env.env_file_resolved.exists():
        print(f"  ERROR: env file symlink is broken: {env.env_file}")
        print("  Is /Volumes/ring/ mounted?")
        return 1
    print(f"  env file: {env.env_file} → {env.env_file_resolved}")

    all_groups = [
        ("required for the capture harness", REQUIRED_FOR_HARNESS),
        ("required by the kohler-anthem library", REQUIRED_FOR_LIBRARY),
    ]

    overall_ok = True
    for group_name, keys in all_groups:
        print(f"\n  {group_name}:")
        for key in keys:
            value = env.get(key, "").strip()
            if not value:
                print(f"    ✗ {key} — MISSING")
                overall_ok = False
            elif value == PLACEHOLDER:
                print(f"    ✗ {key} — placeholder {PLACEHOLDER!r} not replaced")
                overall_ok = False
            else:
                preview = value[:4] + "…" if len(value) > 8 else value
                print(f"    ✓ {key} ({preview})")

    print()
    if overall_ok:
        print("  All required keys present.")
        return 0
    print(f"  Edit {env.env_file_resolved} to fill in missing values.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
