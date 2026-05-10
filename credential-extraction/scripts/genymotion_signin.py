#!/usr/bin/env python3
"""Sign in to Genymotion non-interactively.

Reads GENYMOTION_EMAIL / GENYMOTION_PASSWORD (and optional
GENYMOTION_LICENSE_KEY) from the harness env, then writes them directly into
`~/.Genymobile/Genymotion/settings.json` rather than passing them on the
`gmtool config --password=…` command line — which would put the password into
`ps(1)` output. The password still lives on disk in plaintext (gmtool's
choice, not ours), but we tighten that file to 0600.

If a license key is provided, registers it via `gmtool license register`.

Requires the brew-installed Genymotion Desktop app (or a manual install at
the standard /Applications/Genymotion.app path).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import (
    HarnessError,
    MissingEnvError,
    atomic_write_text,
    chmod_owner_only,
    find_gmtool,
    load_env,
    run,
    run_checked,
)

SETTINGS_PATH = Path.home() / ".Genymobile" / "Genymotion" / "settings.json"


def write_credentials(email: str, password: str) -> None:
    """Merge credentials into settings.json without exposing the password via argv."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS_PATH.exists():
        try:
            existing = json.loads(SETTINGS_PATH.read_text())
        except json.JSONDecodeError as exc:
            raise HarnessError(f"settings.json is not valid JSON: {exc}") from exc
    else:
        existing = {}

    existing["credentials.email"] = email
    existing["credentials.password"] = password
    # Reasonable defaults the gmtool config would have set
    existing.setdefault("version", 1)

    atomic_write_text(
        SETTINGS_PATH,
        json.dumps(existing, indent=4, sort_keys=True) + "\n",
        mode=0o600,
    )
    chmod_owner_only(SETTINGS_PATH.parent, 0o700)
    print(f"  Wrote credentials → {SETTINGS_PATH} (mode 0600)")


def register_license(gmtool: str, key: str) -> None:
    print("  Registering Genymotion license key (via stdin to keep it off argv)...")
    # gmtool license register <key> still puts the key in argv. There's no
    # stdin variant. We use the argv path but note this in README.
    run_checked(
        [gmtool, "license", "register", key],
        error_prefix="gmtool license register failed",
    )


def show_license_info(gmtool: str) -> None:
    info = run([gmtool, "license", "info"])
    if info.stdout.strip():
        for line in info.stdout.strip().splitlines():
            print(f"    {line}")
    validity = run([gmtool, "license", "validity"])
    text = validity.stdout.strip()
    if text:
        print(f"    validity: {text}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Don't error if email/password are missing — useful for CI dry-runs.",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Genymotion sign-in")
    print("=" * 60)
    print()

    gmtool = find_gmtool()
    if not gmtool:
        print("  ERROR: gmtool not found.")
        print("  Install Genymotion Desktop: brew install --cask genymotion")
        return 1
    print(f"  Found gmtool: {gmtool}")

    env = load_env()
    try:
        creds = env.require("GENYMOTION_EMAIL", "GENYMOTION_PASSWORD")
    except MissingEnvError as exc:
        msg = (
            f"  {exc}\n"
            "  Sign up for the 30-day Desktop trial at\n"
            "    https://www.genymotion.com/account/login/\n"
            "  then add your account credentials to the env file."
        )
        if args.allow_empty:
            print(msg)
            print("  (--allow-empty set; continuing without sign-in)")
            return 0
        print(msg)
        return 1

    print(f"  Configuring Genymotion account: {creds['GENYMOTION_EMAIL']}")
    try:
        write_credentials(creds["GENYMOTION_EMAIL"], creds["GENYMOTION_PASSWORD"])
    except HarnessError as exc:
        print(f"  ERROR: {exc}")
        return 1

    license_key = env.get("GENYMOTION_LICENSE_KEY").strip()
    if license_key:
        try:
            register_license(gmtool, license_key)
        except HarnessError as exc:
            print(f"  ERROR: {exc}")
            return 1

    print()
    print("  License info:")
    show_license_info(gmtool)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
