#!/usr/bin/env python3
"""Recover the PKCS12 password by hooking KeyStore.load at runtime.

The Konnect app loads `res/raw/app_certificate.p12` via `KeyStore.load(
InputStream, char[] password)`. The frida_bypass.js already includes a
KeyStore hook that logs the password — this script just runs the harness
briefly to trigger the load, then greps the password out of the Frida log.

Use this on the FIRST install of a new Konnect version (or if the password
changes). The captured password lives at `KOHLER_APIM_CLIENT_CERT_PASSWORD`
in `/Volumes/ring/env/kohler.env`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import find_python, load_env

PASSWORD_RE = re.compile(
    r"CAPTURED CRED \["
    r"(?:KeyStore\.load|KeyManagerFactory\.init|PKCS12KeyStore\.engineLoad)"
    r"\]: (.+)"
)


def main() -> int:
    print()
    print("=" * 60)
    print("Capture KeyStore password from Konnect at runtime")
    print("=" * 60)
    print()

    python = find_python()
    cmd = [
        python,
        str(Path(__file__).resolve().parent / "token_capture.py"),
        "--port", "8888",
        "--wait-seconds", "45",
    ]
    print("  Launching capture for 45 seconds...")
    print("  (Konnect's KeyStore.load happens early in startup, so 45s is plenty.)")
    print()
    subprocess.run(cmd, check=False)

    # Find latest capture session
    env = load_env()
    captures = sorted(env.cache_subdir("token-captures").iterdir(), reverse=True)
    if not captures:
        print("  ERROR: no capture session created.")
        return 1
    frida_log = captures[0] / "frida.log"
    if not frida_log.exists():
        print(f"  ERROR: no frida.log in {captures[0]}")
        return 1

    passwords: set[str] = set()
    for line in frida_log.read_text().splitlines():
        m = PASSWORD_RE.search(line)
        if m:
            passwords.add(m.group(1).strip())

    if not passwords:
        print(f"  No password captured. Inspect {frida_log} for clues.")
        print("  The KeyStore hook may have failed to install (check classloader).")
        return 1

    print()
    print("=" * 60)
    print(f"  CAPTURED {len(passwords)} unique PKCS12 password(s):")
    for p in sorted(passwords):
        print(f"    {p}")
    print("=" * 60)
    print()
    print("  Save into /Volumes/ring/env/kohler.env:")
    print("    export KOHLER_APIM_CLIENT_CERT_PASSWORD=<password>")
    print("  Then run: make extract-client-cert")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
