#!/usr/bin/env python3
"""Prepare the emulator to trust mitmproxy + route HTTPS through it.

What this does:
  1. Ensure a mitmproxy CA exists. Persists the **full** `~/.mitmproxy/`
     directory (incl. private key) in the harness cache so the same CA
     survives emulator/repo wipes.
  2. Verify the CA hasn't expired and has at least 30 days of validity left;
     warn loudly otherwise.
  3. Push the CA into `/system/etc/security/cacerts/` on the emulator using
     the Android-format filename (subject hash + `.0`). Requires `adb root` +
     a writable `/system`, which Genymotion provides. Verifies success by
     listing the directory afterward.
  4. Configure the Android system HTTP proxy to point at the host
     (10.0.3.2 from inside Genymotion) on port 8080.

After this, run `mitmdump` (or `make emulator-token-capture`) on the host
and Konnect traffic will flow through it with TLS visible.

Use `--uninstall` to remove the system CA later (security hygiene — the
emulator otherwise stays MITM-trusted indefinitely).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import (
    HarnessError,
    chmod_owner_only,
    find_adb,
    find_mitmdump,
    find_openssl,
    load_env,
    run,
    run_checked,
    secure_mkdir,
)

HOME_MITM_DIR = Path.home() / ".mitmproxy"
HOME_CA_PEM = HOME_MITM_DIR / "mitmproxy-ca-cert.pem"
HOME_CA_KEY = HOME_MITM_DIR / "mitmproxy-ca.pem"  # cert + private key

ANDROID_CACERT_DIR = "/system/etc/security/cacerts"
GENYMOTION_HOST_FROM_GUEST = "10.0.3.2"
DEFAULT_MITM_PORT = "8080"

CA_VALIDITY_WARN_DAYS = 30


def restore_or_generate_ca(mitmdump: str, cache_dir: Path) -> Path:
    """Make sure a complete mitmproxy CA (cert + private key) is in ~/.mitmproxy/.

    Cache restore is the preferred path: it preserves the same CA across
    repo / home wipes. Cache write happens after first successful generation.
    """
    cached_pem = cache_dir / "mitmproxy-ca-cert.pem"
    cached_key = cache_dir / "mitmproxy-ca.pem"
    HOME_MITM_DIR.mkdir(parents=True, exist_ok=True)
    chmod_owner_only(HOME_MITM_DIR, 0o700)

    # If the cache has both cert AND private key, restore both. Without the
    # key, the next mitmdump would generate a *new* CA and silently break
    # trust on the emulator.
    if cached_pem.exists() and cached_key.exists():
        if not HOME_CA_PEM.exists():
            shutil.copy2(cached_pem, HOME_CA_PEM)
            chmod_owner_only(HOME_CA_PEM, 0o600)
        if not HOME_CA_KEY.exists():
            shutil.copy2(cached_key, HOME_CA_KEY)
            chmod_owner_only(HOME_CA_KEY, 0o600)
        print(f"  Restored CA (cert + key) from cache → {HOME_MITM_DIR}")
        return HOME_CA_PEM

    # If the home dir already has a CA but the cache doesn't, persist it.
    if HOME_CA_PEM.exists() and HOME_CA_KEY.exists():
        shutil.copy2(HOME_CA_PEM, cached_pem)
        shutil.copy2(HOME_CA_KEY, cached_key)
        chmod_owner_only(cached_pem, 0o600)
        chmod_owner_only(cached_key, 0o600)
        print(f"  Cached existing CA → {cache_dir}")
        return HOME_CA_PEM

    # Otherwise: boot mitmdump briefly to generate a fresh CA.
    print("  Generating fresh mitmproxy CA...")
    # Use a port unlikely to be in use; mitmdump exits when killed.
    proc = subprocess.Popen(
        [mitmdump, "--listen-port", "8181", "--set", "block_global=false"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        for _ in range(60):
            if HOME_CA_PEM.exists() and HOME_CA_KEY.exists():
                break
            time.sleep(0.5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if not HOME_CA_PEM.exists() or not HOME_CA_KEY.exists():
        raise HarnessError(
            "mitmproxy did not generate a complete CA "
            f"(cert: {HOME_CA_PEM.exists()}, key: {HOME_CA_KEY.exists()})"
        )

    shutil.copy2(HOME_CA_PEM, cached_pem)
    shutil.copy2(HOME_CA_KEY, cached_key)
    chmod_owner_only(cached_pem, 0o600)
    chmod_owner_only(cached_key, 0o600)
    print(f"  Generated CA + cached it → {cache_dir}")
    return HOME_CA_PEM


def verify_ca_validity(pem_path: Path) -> None:
    """Check the CA is still valid; warn (don't fail) if close to expiry."""
    openssl = find_openssl()
    if not openssl:
        print("  WARNING: openssl not found; skipping CA validity check")
        return

    # Hard-fail if expired
    expired = run([openssl, "x509", "-checkend", "0", "-noout", "-in", str(pem_path)])
    if expired.returncode != 0:
        raise HarnessError(
            f"mitmproxy CA has expired ({pem_path}). "
            f"Delete it (and the cached copies) and re-run to regenerate."
        )

    # Warn if expiring within N days
    warn_seconds = CA_VALIDITY_WARN_DAYS * 24 * 3600
    soon = run([openssl, "x509", "-checkend", str(warn_seconds), "-noout", "-in", str(pem_path)])
    if soon.returncode != 0:
        print(f"  WARNING: mitmproxy CA expires within {CA_VALIDITY_WARN_DAYS} days")

    # Print the not-after date for the run log
    info = run([openssl, "x509", "-noout", "-enddate", "-in", str(pem_path)])
    if info.returncode == 0:
        print(f"  CA validity: {info.stdout.strip()}")


def compute_subject_hash(pem_path: Path) -> str:
    """OpenSSL old-style subject hash → Android system-cert filename prefix."""
    openssl = find_openssl()
    if not openssl:
        raise HarnessError("openssl not found")
    result = run_checked(
        [openssl, "x509", "-inform", "PEM", "-subject_hash_old", "-in", str(pem_path)],
        error_prefix="openssl x509 -subject_hash_old failed",
    )
    return result.stdout.strip().splitlines()[0].strip()


def ensure_remount_rw(adb: str) -> None:
    """Acquire root + remount /system rw; raise if it didn't take."""
    print("  Acquiring adb root + remounting /system rw...")
    run([adb, "root"])
    time.sleep(1)

    # `adb remount` works on Genymotion (userdebug builds). Older builds need explicit mount.
    remount = run([adb, "remount"])
    if remount.returncode != 0:
        run([adb, "shell", "mount", "-o", "rw,remount", "/system"])

    # Verify /system is actually writable now
    test_path = f"{ANDROID_CACERT_DIR}/.write-test"
    touch = run([adb, "shell", "sh", "-c", f"touch {test_path} && rm {test_path}"])
    if touch.returncode != 0:
        raise HarnessError(
            "/system is still not writable after adb root + remount.\n"
            "  On Android 10+ images you may need: adb disable-verity && adb reboot\n"
            f"  then re-run mitmproxy-setup.\n  stderr: {touch.stderr.strip()}"
        )


def install_system_cert(adb: str, pem_path: Path, subject_hash: str) -> str:
    """Push the CA into /system/etc/security/cacerts and verify. Returns the remote path."""
    remote_path = f"{ANDROID_CACERT_DIR}/{subject_hash}.0"
    print(f"  Pushing CA → {remote_path}")
    push = run_checked(
        [adb, "push", str(pem_path), remote_path],
        error_prefix="adb push failed",
    )
    chmod = run([adb, "shell", "chmod", "644", remote_path])
    if chmod.returncode != 0:
        print(f"  WARNING: chmod failed: {chmod.stderr.strip()}")

    # Verify the cert is actually there
    ls = run([adb, "shell", "ls", "-l", remote_path])
    if ls.returncode != 0 or remote_path not in ls.stdout:
        raise HarnessError(
            f"CA push appeared to succeed but {remote_path} is not present.\n"
            f"  ls output: {ls.stdout.strip() or ls.stderr.strip()}\n"
            f"  push output: {push.stdout.strip()}"
        )

    # Best-effort: re-mount /system read-only
    run([adb, "shell", "mount", "-o", "ro,remount", "/system"])
    print(f"  Verified CA at {remote_path}")
    return remote_path


def uninstall_system_cert(
    adb: str,
    pem_path: Path | None = None,
    subject_hash: str | None = None,
) -> bool:
    """Remove the mitmproxy CA from /system/etc/security/cacerts/.

    If subject_hash is provided, use that. Otherwise derive it from pem_path.
    """
    if not subject_hash:
        if not pem_path:
            raise HarnessError("uninstall_system_cert needs subject_hash or pem_path")
        subject_hash = compute_subject_hash(pem_path)

    remote_path = f"{ANDROID_CACERT_DIR}/{subject_hash}.0"
    print(f"  Removing CA from emulator: {remote_path}")
    run([adb, "root"])
    time.sleep(1)
    run([adb, "remount"])
    rm = run([adb, "shell", "rm", "-f", remote_path])
    if rm.returncode != 0:
        print(f"  WARNING: rm failed: {rm.stderr.strip()}")
    run([adb, "shell", "mount", "-o", "ro,remount", "/system"])
    # Verify it's gone
    ls = run([adb, "shell", "ls", remote_path])
    return ls.returncode != 0


def configure_proxy(adb: str, host: str, port: str) -> None:
    target = f"{host}:{port}"
    print(f"  Setting Android global http_proxy = {target}")
    result = run([adb, "shell", "settings", "put", "global", "http_proxy", target])
    if result.returncode != 0:
        raise HarnessError(f"settings put global http_proxy failed: {result.stderr.strip()}")

    # Verify by reading back
    read = run([adb, "shell", "settings", "get", "global", "http_proxy"])
    if read.returncode == 0 and target not in read.stdout:
        raise HarnessError(
            f"proxy setting did not persist; got: {read.stdout.strip()!r}"
        )


def clear_proxy(adb: str) -> bool:
    """Remove the Android global http_proxy. Returns True on success."""
    print("  Clearing Android global http_proxy")
    a = run([adb, "shell", "settings", "put", "global", "http_proxy", ":0"])
    b = run([adb, "shell", "settings", "delete", "global", "http_proxy"])
    return a.returncode == 0 and b.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-host", default=GENYMOTION_HOST_FROM_GUEST)
    parser.add_argument("--proxy-port", default=DEFAULT_MITM_PORT)
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Remove the proxy setting (but keep the CA installed).",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the proxy setting AND uninstall the mitmproxy CA from /system.",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("mitmproxy + emulator cert/proxy setup")
    print("=" * 60)
    print()

    adb = find_adb()
    if not adb:
        print("  ERROR: adb not found. Run `make deps`.")
        return 1
    print(f"  Found adb: {adb}")

    if args.clear or args.uninstall:
        clear_proxy(adb)
        if args.uninstall:
            mitmdump = find_mitmdump()
            if not mitmdump:
                print("  WARNING: mitmdump not found — skipping CA uninstall.")
                return 0
            env = load_env()
            cache_dir = env.cache_subdir("mitmproxy-ca")
            pem = restore_or_generate_ca(mitmdump, cache_dir)
            try:
                if uninstall_system_cert(adb, pem):
                    print("  CA removed from /system.")
                else:
                    print("  WARNING: CA may still be present on emulator")
            except HarnessError as exc:
                print(f"  ERROR: {exc}")
                return 1
        return 0

    mitmdump = find_mitmdump()
    if not mitmdump:
        print("  ERROR: mitmdump not found.")
        print("  Install with: brew install mitmproxy   OR   .venv/bin/pip install mitmproxy")
        return 1

    env = load_env()
    cache_dir = env.cache_subdir("mitmproxy-ca")
    secure_mkdir(cache_dir, mode=0o700)

    try:
        pem = restore_or_generate_ca(mitmdump, cache_dir)
        verify_ca_validity(pem)
        subject_hash = compute_subject_hash(pem)
        print(f"  Subject hash: {subject_hash}")
        ensure_remount_rw(adb)
        install_system_cert(adb, pem, subject_hash)
        configure_proxy(adb, args.proxy_host, args.proxy_port)
    except HarnessError as exc:
        print()
        print(f"ERROR: {exc}")
        return 1

    print()
    print("  Emulator now trusts mitmproxy and routes HTTPS through it.")
    print(f"  Start mitmdump on host:  mitmdump --listen-port {args.proxy_port}")
    print("  Or run:                  make emulator-token-capture")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
