#!/usr/bin/env python3
"""Extract the APIM mTLS client cert from Konnect's APK.

Konnect bundles `res/raw/app_certificate.p12` as the client cert it presents
via mTLS to Kohler's APIM gateway (`*.kohlerkonnect-apim.azure-api.net`).
Without this cert, the gateway returns 403 "Invalid client certificate" and
the app's sign-in flow refuses to advance.

The PKCS#12 password is `d6jaqQ1nJxFAuXs` — captured at runtime via Frida
hooks on `KeyStore.load(InputStream, char[])` and
`KeyManagerFactory.init(KeyStore, char[])` in a live run on 2026-05-10.

This script:
  1. Reads the password from `KOHLER_APIM_CLIENT_CERT_PASSWORD` in the env
  2. Extracts `res/raw/app_certificate.p12` from `konnect-apk/base.apk`
  3. Decrypts with OpenSSL using the legacy provider (the PKCS12 uses
     RC2-40-CBC encryption, which modern OpenSSL disables by default)
  4. Writes a PEM (cert + key) to the path in `KOHLER_APIM_CLIENT_CERT_PEM`
  5. Sets the file to mode 0o600

The output PEM is then passed to mitmdump as `--set client_certs=<path>` so
mitmproxy can present it upstream when intercepting traffic destined for
Kohler's APIM gateway.

NOTE: the password we have unlocks `app_certificate.p12`, NOT
`auth_certificate.pfx`. The latter has a different (still-unknown) password
and is probably for a separate purpose (per-device provisioning?). Not
needed for the harness today.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import (
    EXTRACTION_DIR,
    HarnessError,
    chmod_owner_only,
    find_openssl,
    load_env,
)

REPO_APK_BASE = EXTRACTION_DIR / "konnect-apk" / "base.apk"
CERT_ENTRY = "res/raw/app_certificate.p12"


def extract_pkcs12_from_apk(apk_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(apk_path) as zf, zf.open(CERT_ENTRY) as src, dest.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    chmod_owner_only(dest, 0o600)


def pkcs12_to_pem(pkcs12_path: Path, password: str, pem_out: Path) -> None:
    openssl = find_openssl()
    if not openssl:
        raise HarnessError("openssl not found")
    # The PKCS12 uses RC2-40-CBC — modern OpenSSL 3.x needs `-provider legacy`.
    result = subprocess.run(
        [
            openssl, "pkcs12",
            "-in", str(pkcs12_path),
            "-password", f"pass:{password}",
            "-nodes",
            "-out", str(pem_out),
            "-provider", "legacy",
            "-provider", "default",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HarnessError(
            f"openssl pkcs12 failed: {result.stderr.strip()}\n"
            f"Password may be wrong, or OpenSSL is missing the legacy provider."
        )
    chmod_owner_only(pem_out, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=None,
        help="Output PEM path (defaults to $KOHLER_APIM_CLIENT_CERT_PEM).",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="PKCS12 password (defaults to $KOHLER_APIM_CLIENT_CERT_PASSWORD).",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Extract APIM mTLS client cert from base.apk")
    print("=" * 60)
    print()

    env = load_env()
    password = (args.password or env.get("KOHLER_APIM_CLIENT_CERT_PASSWORD", "")).strip()
    if not password:
        print("  ERROR: KOHLER_APIM_CLIENT_CERT_PASSWORD not set (and --password not given).")
        print(
            "  Either fill it in (/Volumes/ring/env/kohler.env) or run\n"
            "  `make capture-pfx-password` to recover via Frida."
        )
        return 1

    out_path_str = (args.out or env.get("KOHLER_APIM_CLIENT_CERT_PEM", "")).strip()
    if not out_path_str:
        print("  ERROR: KOHLER_APIM_CLIENT_CERT_PEM not set in env.")
        return 1
    out_path = Path(out_path_str).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chmod_owner_only(out_path.parent, 0o700)

    if not REPO_APK_BASE.exists():
        raise SystemExit(f"missing {REPO_APK_BASE} — run `git lfs pull` first")

    with tempfile.TemporaryDirectory() as tmpdir:
        p12 = Path(tmpdir) / "app_certificate.p12"
        extract_pkcs12_from_apk(REPO_APK_BASE, p12)
        try:
            pkcs12_to_pem(p12, password, out_path)
        except HarnessError as exc:
            print(f"ERROR: {exc}")
            return 1

    print(f"  Wrote PEM → {out_path}")
    print()
    print("  This PEM is the upstream client cert for mitmdump. The harness")
    print("  passes it via `--set client_certs=<path>` when starting mitmdump.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
