#!/usr/bin/env python3
"""Best-effort Konnect sign-in driver.

Today this script:
  - Pre-grants ACCESS_FINE_LOCATION / ACCESS_COARSE_LOCATION via `adb pm grant`
  - Dumps the UI hierarchy via `uiautomator` for later inspection
  - Optionally types KOHLER_USERNAME + KOHLER_PASSWORD via `adb shell input`
    into whatever's currently focused (only safe if the user has focused the
    username field, and only with passwords containing safe characters —
    see SAFE_TEXT_RE below)
  - Otherwise prints clear manual instructions

The fully automated flow needs view-coordinate or resource-id taps captured
from a real run of the app, which we don't have yet. After the first
successful capture, fill in `KONNECT_SIGNIN_STEPS` below with the recorded
sequence and this script becomes hands-off.

Use `make record-konnect-signin` to walk the recording flow interactively.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Literal, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import find_adb, load_env, run

PACKAGE = "com.kohler.hermoth"

# `adb shell input text` sends the literal string to a shell which then
# interprets metacharacters. To avoid shell injection, the harness only
# auto-types text consisting of these characters. Anything else falls through
# to manual sign-in with a clear message.
#
# Allowed: alphanumerics, common password punctuation that's safe inside
# single-quotes on the device shell. NOT allowed: `'`, backslash, control
# characters, anything outside ASCII.
SAFE_TEXT_RE = re.compile(r"^[A-Za-z0-9!@#%^&*()\-_=+\[\]{};:.,<>?/]+$")

# Typed step format. Each tuple is one of:
TapStep = tuple[Literal["tap"], int, int]
TextStep = tuple[Literal["text"], str]
KeyStep = tuple[Literal["key"], str]
WaitStep = tuple[Literal["wait"], float]
DumpStep = tuple[Literal["dump"], str]
Step = Union[TapStep, TextStep, KeyStep, WaitStep, DumpStep]

# After first successful capture, populate from the recorded UI dumps.
# Example:
#   KONNECT_SIGNIN_STEPS = [
#       ("wait", 3),
#       ("dump", "00_landing"),
#       ("tap", 540, 1200),       # "Sign In" button
#       ("wait", 2),
#       ("dump", "01_login_form"),
#       ("text", "$KOHLER_USERNAME"),
#       ("key", "TAB"),
#       ("text", "$KOHLER_PASSWORD"),
#       ("key", "ENTER"),
#   ]
KONNECT_SIGNIN_STEPS: list[Step] = []


def grant_location(adb: str) -> None:
    print("  Granting location permissions...")
    for perm in ("ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"):
        result = run([adb, "shell", "pm", "grant", PACKAGE, f"android.permission.{perm}"])
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr and "has not requested" not in stderr:
                print(f"    {perm}: {stderr}")


def dump_ui(adb: str, label: str, out_dir: Path) -> Path | None:
    """Use uiautomator to dump the current UI hierarchy as XML."""
    remote = "/sdcard/window_dump.xml"
    run([adb, "shell", "uiautomator", "dump", remote])
    local = out_dir / f"ui_{label}.xml"
    pull = run([adb, "pull", remote, str(local)])
    if pull.returncode != 0:
        return None
    return local


def adb_tap(adb: str, x: int, y: int) -> None:
    run([adb, "shell", "input", "tap", str(x), str(y)])


def adb_text(adb: str, text: str) -> None:
    """Type text via `input text`, with strict input validation.

    Raises ValueError if text contains shell metacharacters that would be
    unsafe to send. `input text` doesn't render spaces, so we substitute
    `%s` per the Android convention.
    """
    if not text:
        return
    if not SAFE_TEXT_RE.match(text):
        offending = [c for c in text if not SAFE_TEXT_RE.match(c)]
        raise ValueError(
            f"text contains characters unsupported by safe auto-type: "
            f"{sorted(set(offending))!r}. Sign in manually instead."
        )
    # `%s` → space inside `input text`; quote for the device shell.
    payload = text.replace(" ", "%s")
    run([adb, "shell", "input", "text", shlex.quote(payload)])


def adb_key(adb: str, key: str) -> None:
    keymap = {"ENTER": "66", "TAB": "61", "BACK": "4"}
    code = keymap.get(key.upper(), key)
    run([adb, "shell", "input", "keyevent", str(code)])


def expand_env_refs(value: str, env_values: dict[str, str]) -> str:
    """Expand `$VAR` references against the harness env (not os.environ)."""
    return re.sub(r"\$([A-Z_][A-Z0-9_]*)", lambda m: env_values.get(m.group(1), m.group(0)), value)


def run_steps(adb: str, steps: list[Step], dump_dir: Path, env_values: dict[str, str]) -> None:
    for index, step in enumerate(steps):
        action = step[0]
        if action == "tap":
            _, x, y = step
            print(f"    step {index}: tap ({x}, {y})")
            adb_tap(adb, int(x), int(y))
        elif action == "text":
            _, value = step
            expanded = expand_env_refs(value, env_values)
            preview = expanded[:8] + "…" if len(expanded) > 8 else expanded
            print(f"    step {index}: text {preview!r}")
            adb_text(adb, expanded)
        elif action == "key":
            _, key = step
            print(f"    step {index}: key {key}")
            adb_key(adb, key)
        elif action == "wait":
            _, seconds = step
            print(f"    step {index}: wait {seconds}s")
            time.sleep(float(seconds))
        elif action == "dump":
            _, label = step
            path = dump_ui(adb, label, dump_dir)
            print(f"    step {index}: dump → {path}")
        else:
            raise ValueError(f"Unknown step action: {action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-dir",
        default=None,
        help="Directory for UI dumps. Defaults to <cache>/ui-dumps/.",
    )
    parser.add_argument(
        "--auto-type",
        action="store_true",
        help=(
            "Type KOHLER_USERNAME / KOHLER_PASSWORD into the currently focused "
            "field. Only safe if you've manually focused the username field. "
            "Refuses to run if the password contains unsupported chars."
        ),
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Konnect sign-in helper")
    print("=" * 60)
    print()

    adb = find_adb()
    if not adb:
        print("  ERROR: adb not found.")
        return 1

    env = load_env()
    dump_dir = Path(args.dump_dir) if args.dump_dir else env.cache_subdir("ui-dumps")
    dump_dir.mkdir(parents=True, exist_ok=True)

    grant_location(adb)

    if KONNECT_SIGNIN_STEPS:
        print()
        print("  Running recorded sign-in step sequence...")
        try:
            run_steps(adb, KONNECT_SIGNIN_STEPS, dump_dir, env.values)
        except ValueError as exc:
            print(f"  ERROR: {exc}")
            return 1
        return 0

    if args.auto_type:
        try:
            creds = env.require("KOHLER_USERNAME", "KOHLER_PASSWORD")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            return 1
        print()
        print("  Auto-typing credentials into the currently focused field.")
        try:
            adb_text(adb, creds["KOHLER_USERNAME"])
            adb_key(adb, "TAB")
            time.sleep(0.5)
            adb_text(adb, creds["KOHLER_PASSWORD"])
        except ValueError as exc:
            print(f"  ERROR: {exc}")
            print("  Sign in manually instead.")
            return 1
        return 0

    print()
    print("  No recorded sign-in sequence yet. Sign in manually in the emulator:")
    print("    1. Wait for the Kohler Konnect app to finish launching")
    print("    2. Tap through any location-permission screen (already granted)")
    print(f"    3. Sign in with {env.get('KOHLER_USERNAME', '<your-username>')}")
    print("    4. Watch the host's terminal for /token captures")
    print()
    print("  To help future-us automate this, capture the UI at each step:")
    print("    make record-konnect-signin")
    print()
    print("  Then fill in KONNECT_SIGNIN_STEPS in this script.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
