#!/usr/bin/env python3
"""Create the .env symlink in the repo root.

Links `<repo>/.env` → `/Volumes/ring/env/kohler.env`. Refuses to overwrite an
existing real file at `.env` (only replaces an existing symlink). Errors
loudly if the target doesn't exist (e.g. /Volumes/ring/ is not mounted).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import DEFAULT_ENV_FILE

DEFAULT_ENV_TARGET = Path("/Volumes/ring/env/kohler.env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=str(DEFAULT_ENV_TARGET),
        help=f"Path the .env symlink should point at (default: {DEFAULT_ENV_TARGET}).",
    )
    parser.add_argument(
        "--link-path",
        default=str(DEFAULT_ENV_FILE),
        help=f"Where to create the symlink (default: {DEFAULT_ENV_FILE}).",
    )
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser()
    link = Path(args.link_path).expanduser()

    print()
    print("=" * 60)
    print("Secrets link")
    print("=" * 60)
    print()

    if not target.exists():
        print(f"  ERROR: link target does not exist: {target}")
        if str(target).startswith("/Volumes/"):
            print(
                "  Is /Volumes/ring/ mounted? If you don't have it set up yet, run "
                "`make secrets-init` first."
            )
        return 1

    if link.is_symlink():
        existing = os.readlink(link)
        if existing == str(target):
            print(f"  Symlink already correct: {link} → {existing}")
            return 0
        print(f"  Replacing existing symlink: {link} → {existing}")
        link.unlink()
    elif link.exists():
        print(f"  ERROR: {link} exists and is not a symlink. Refusing to overwrite.")
        return 1

    link.symlink_to(target)
    print(f"  Created symlink: {link} → {target}")
    print()
    print("  Next step: make secrets-check (verifies required keys are populated)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
