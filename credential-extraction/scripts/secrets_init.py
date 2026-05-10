#!/usr/bin/env python3
"""Scaffold the harness secrets file.

Copies `credential-extraction/env.example` to `/Volumes/ring/env/kohler.env`
if it doesn't already exist. Sets 0600 perms. Refuses to overwrite an
existing file unless `--force` is set.

After this, run `make secrets-link` to create the in-repo `.env` symlink and
edit the env file to fill in the YOUR_VALUE_HERE blanks.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import EXAMPLE_ENV_FILE, chmod_owner_only, secure_mkdir

DEFAULT_ENV_TARGET = Path("/Volumes/ring/env/kohler.env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=str(DEFAULT_ENV_TARGET),
        help=f"Where to write the env file (default: {DEFAULT_ENV_TARGET}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing env file (dangerous — destroys real secrets).",
    )
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()

    print()
    print("=" * 60)
    print("Secrets init")
    print("=" * 60)
    print()

    if not EXAMPLE_ENV_FILE.exists():
        print(f"  ERROR: example file missing: {EXAMPLE_ENV_FILE}")
        return 1

    if target.exists() and not args.force:
        print(f"  Env file already exists: {target}")
        print("  Skipping write. Use --force to overwrite (you almost certainly")
        print("  don't want to — that destroys real secrets).")
        return 0

    parent = target.parent
    if not parent.exists():
        print(f"  ERROR: parent directory doesn't exist: {parent}")
        if str(parent).startswith("/Volumes/"):
            print(
                "  Make sure the volume is mounted. /Volumes/ring/ is the user's "
                "secrets volume; mount it via the usual mechanism before re-running."
            )
        return 1

    print(f"  Copying {EXAMPLE_ENV_FILE} → {target}")
    shutil.copy2(EXAMPLE_ENV_FILE, target)
    chmod_owner_only(target, 0o600)
    secure_mkdir(parent, 0o700)
    print(f"  Wrote {target} (mode 0600)")
    print()
    print("  Next step: edit it to fill in YOUR_VALUE_HERE values, then")
    print("    make secrets-link")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
