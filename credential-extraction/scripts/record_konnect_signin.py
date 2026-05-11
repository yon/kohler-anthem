#!/usr/bin/env python3
"""Record the Konnect sign-in UI flow so it can be replayed.

How it works:
  1. Wait for the emulator to be reachable.
  2. Launch Konnect via `adb shell am start`.
  3. Loop in 2-second intervals: dump the UI hierarchy + take a screenshot.
  4. The user signs in by hand inside the emulator while this runs.
  5. On Ctrl-C, save everything to `<cache>/ui-dumps/recording-<timestamp>/`
     and print a step-list skeleton the user can paste into
     `konnect_signin.py:KONNECT_SIGNIN_STEPS`.

The output isn't fully automatic — taps and key events aren't captured (Android
doesn't expose those without rooted tracing). But the snapshots make it easy
to read off resource-ids and coords for the screens you saw.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import adb_device_connected, find_adb, load_env, run, secure_mkdir

PACKAGE = "com.kohler.hermoth"
ACTIVITY = "com.kohler.hermoth.MainActivity"


def launch_konnect(adb: str) -> None:
    print(f"  Launching {PACKAGE}/{ACTIVITY}")
    run([adb, "shell", "am", "start", "-n", f"{PACKAGE}/{ACTIVITY}"])


def dump_ui(adb: str, label: str, out_dir: Path) -> tuple[Path | None, Path | None]:
    """Return (xml_path, screenshot_path)."""
    remote_xml = f"/sdcard/window_dump_{label}.xml"
    remote_png = f"/sdcard/screen_{label}.png"

    xml_local = out_dir / f"{label}.xml"
    png_local = out_dir / f"{label}.png"

    run([adb, "shell", "uiautomator", "dump", remote_xml])
    run([adb, "pull", remote_xml, str(xml_local)])

    run([adb, "shell", "screencap", "-p", remote_png])
    run([adb, "pull", remote_png, str(png_local)])

    return (xml_local if xml_local.exists() else None,
            png_local if png_local.exists() else None)


def write_skeleton(out_dir: Path, snapshots: list[str]) -> Path:
    """Write a starter KONNECT_SIGNIN_STEPS list referencing the captured snapshots."""
    lines = [
        "# Recorded sign-in skeleton — paste into konnect_signin.py and",
        "# replace the placeholder taps with real (x, y) coords pulled from",
        "# the corresponding XML/PNG files.",
        "",
        "KONNECT_SIGNIN_STEPS: list[Step] = [",
    ]
    for label in snapshots:
        lines.append('    ("wait", 2),')
        lines.append(f'    ("dump", "{label}"),')
        lines.append(f'    # TODO: ("tap", X, Y),    # see {label}.xml / {label}.png')
    lines.append(']')
    skeleton_path = out_dir / "KONNECT_SIGNIN_STEPS_skeleton.py"
    skeleton_path.write_text("\n".join(lines) + "\n")
    return skeleton_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Seconds between UI snapshots (default 3).",
    )
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=30,
        help="Stop after this many snapshots (default 30).",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Konnect sign-in recorder")
    print("=" * 60)
    print()

    adb = find_adb()
    if not adb:
        print("  ERROR: adb not found.")
        return 1
    if not adb_device_connected():
        print("  ERROR: no device connected. Run `make emulator-setup` first.")
        return 1

    env = load_env()
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = env.cache_subdir("ui-dumps") / f"recording-{ts}"
    secure_mkdir(out_dir, 0o700)

    print(f"  Output dir: {out_dir}")
    print()
    print("  Sign in to Konnect manually in the emulator while this runs.")
    print("  Press Ctrl-C when you're done — a step-list skeleton will be saved.")
    print()

    launch_konnect(adb)
    snapshots: list[str] = []

    try:
        for i in range(args.max_snapshots):
            label = f"step{i:02d}"
            xml, png = dump_ui(adb, label, out_dir)
            if xml or png:
                snapshots.append(label)
                marker = []
                if xml:
                    marker.append("xml")
                if png:
                    marker.append("png")
                print(f"  snapshot {i:02d} ({'+'.join(marker)})")
            time.sleep(args.interval)
        print()
        print(f"  Reached max snapshots ({args.max_snapshots}).")
    except KeyboardInterrupt:
        print()
        print(f"  Stopped — captured {len(snapshots)} snapshots.")

    if snapshots:
        skeleton = write_skeleton(out_dir, snapshots)
        print()
        print(f"  Skeleton step list written to: {skeleton}")
        print(f"  Snapshots in: {out_dir}")
        print()
        print("  Next: edit konnect_signin.py, replace KONNECT_SIGNIN_STEPS with")
        print(f"        the contents of {skeleton.name}, and fill in (x, y) taps")
        print("        by reading off coords from the .png / .xml pairs.")
        # Also drop a copy of the current konnect_signin.py for reference
        shutil.copy2(Path(__file__).parent / "konnect_signin.py", out_dir / "konnect_signin.py.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
