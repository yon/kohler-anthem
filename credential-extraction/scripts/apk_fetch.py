#!/usr/bin/env python3
"""Manage the Kohler Konnect APK that the harness installs.

Modes:

  --verify  (default)
        Confirm `credential-extraction/konnect-apk/` exists, the APK
        files are real (not LFS pointers), and each file's SHA-256
        matches the manifest. Exits 0 if everything checks out, 1
        otherwise — with a clear hint like "run git lfs pull".

  --update
        Download the latest XAPK from APKPure into the harness cache,
        verify it includes the same ABIs as the currently-checked-in
        APK (so we don't regress, e.g. APKPure serving an armeabi-v7a-
        only bundle to an arm64 device), and replace the checked-in
        APKs + manifest atomically. The user should review with
        `git diff credential-extraction/konnect-apk/manifest.json`
        and `git lfs ls-files` before committing.

The harness depends on `credential-extraction/konnect-apk/manifest.json`
as a Make file target. The APK is git-LFS tracked so cloning + running
`git lfs pull` is the only way for a new user to get it.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import (
    EXTRACTION_DIR,
    HarnessError,
    atomic_write_text,
    chmod_owner_only,
    load_env,
    secure_mkdir,
)

PACKAGE = "com.kohler.hermoth"
APP_SLUG = "kohler-konnect"

# In-repo (LFS) APK location — this is the canonical source the harness uses.
REPO_APK_DIR = EXTRACTION_DIR / "konnect-apk"
REPO_MANIFEST = REPO_APK_DIR / "manifest.json"

APKPURE_PAGE_URL = f"https://apkpure.com/{APP_SLUG}/{PACKAGE}"
APKPURE_XAPK_URL = f"https://d.apkpure.com/b/XAPK/{PACKAGE}?version=latest"
APKPURE_APK_URL = f"https://d.apkpure.com/b/APK/{PACKAGE}?version=latest"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+){0,2}$")
MIN_APK_BYTES = 5 * 1024 * 1024
CHUNK = 64 * 1024

LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec"

ABI_FROM_SPLIT_NAME = {
    "arm64_v8a": "arm64-v8a",
    "armeabi_v7a": "armeabi-v7a",
    "x86_64": "x86_64",
    "x86": "x86",
}


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    version: str
    notes: list[str]


# --- shared helpers ---------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def _abis_in_dir(apk_dir: Path) -> list[str]:
    """Return the list of ABIs covered by split_config.<abi>.apk files in apk_dir."""
    out = []
    for apk in apk_dir.glob("split_config.*.apk"):
        # split_config.<abi>.apk — also matches split_config.<density>.apk and
        # split_config.<lang>.apk, but only the ABI ones map to entries in
        # ABI_FROM_SPLIT_NAME.
        suffix = apk.stem.removeprefix("split_config.")
        if suffix in ABI_FROM_SPLIT_NAME:
            out.append(ABI_FROM_SPLIT_NAME[suffix])
    # APKPure-style splits use `config.<abi>.apk` (no `split_` prefix)
    for apk in apk_dir.glob("config.*.apk"):
        suffix = apk.stem.removeprefix("config.")
        if suffix in ABI_FROM_SPLIT_NAME:
            out.append(ABI_FROM_SPLIT_NAME[suffix])
    return sorted(set(out))


# --- verify mode ------------------------------------------------------------

def load_manifest(path: Path = REPO_MANIFEST) -> dict:
    if not path.exists():
        raise HarnessError(
            f"manifest missing: {path}\n"
            f"  The checked-in APK is git-LFS tracked. Run:\n"
            f"    git lfs pull --include='credential-extraction/konnect-apk/'"
        )
    return json.loads(path.read_text())


def verify_repo_apk(*, apk_dir: Path = REPO_APK_DIR) -> VerifyResult:
    """Check that the in-repo APK is intact and matches its manifest."""
    manifest = load_manifest(apk_dir / "manifest.json")
    notes: list[str] = []
    ok = True

    for filename, expected in manifest.get("apks", {}).items():
        path = apk_dir / filename
        if not path.exists():
            notes.append(f"MISSING: {filename}")
            ok = False
            continue
        if _is_lfs_pointer(path):
            notes.append(
                f"LFS POINTER (not pulled): {filename} — "
                f"run `git lfs pull --include='credential-extraction/konnect-apk/'`"
            )
            ok = False
            continue
        if not expected.startswith("sha256:"):
            notes.append(f"manifest entry for {filename} has unknown digest format")
            ok = False
            continue
        expected_sha = expected.split(":", 1)[1]
        actual_sha = _sha256(path)
        if actual_sha != expected_sha:
            notes.append(
                f"HASH MISMATCH: {filename}\n"
                f"  expected sha256: {expected_sha}\n"
                f"  actual   sha256: {actual_sha}"
            )
            ok = False
        else:
            notes.append(f"OK: {filename} ({path.stat().st_size} bytes)")

    abis = _abis_in_dir(apk_dir)
    notes.append(f"ABIs present: {', '.join(abis) if abis else '(none — base APK only)'}")
    return VerifyResult(ok=ok, version=manifest.get("version", "unknown"), notes=notes)


# --- update mode (download from APKPure) -----------------------------------

def _fetch_bytes(url: str, *, timeout: int = 60) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.geturl()


def _stream_download(url: str, dest: Path, *, timeout: int = 300) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers=HEADERS)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            total_bytes = 0
            with tmp.open("wb") as fh:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    total_bytes += len(chunk)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"    download failed: {exc}")
        tmp.unlink(missing_ok=True)
        return False, ""

    if total_bytes < MIN_APK_BYTES:
        preview = tmp.read_bytes()[:200].decode("utf-8", errors="replace")
        print(
            f"    response too small ({total_bytes} bytes, ct={content_type!r}); "
            f"preview: {preview!r}"
        )
        tmp.unlink(missing_ok=True)
        return False, final_url

    with tmp.open("rb") as fh:
        magic = fh.read(4)
    if magic != b"PK\x03\x04":
        print(f"    file does not look like a ZIP/APK (magic: {magic!r}); discarding")
        tmp.unlink(missing_ok=True)
        return False, final_url

    os.replace(tmp, dest)
    chmod_owner_only(dest, 0o600)
    print(f"  Saved {total_bytes} bytes → {dest}")
    return True, final_url


def _download_with_retries(url: str, dest: Path, *, attempts: int = 3) -> tuple[bool, str]:
    for attempt in range(1, attempts + 1):
        print(f"  Attempt {attempt}/{attempts}: {url}")
        ok, final = _stream_download(url, dest)
        if ok:
            return True, final
        time.sleep(min(2 ** attempt, 30))
    return False, ""


def _version_from_url(url: str) -> str | None:
    if not url:
        return None
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    fn = params.get("_fn", [""])[0]
    if not fn:
        return None
    candidates = [fn]
    try:
        padded = fn + "=" * (-len(fn) % 4)
        decoded = base64.b64decode(padded, validate=False).decode("utf-8", errors="ignore")
        candidates.append(decoded)
    except (binascii.Error, ValueError):
        pass
    for candidate in candidates:
        match = re.search(r"_([0-9]+\.[0-9]+(?:\.[0-9]+){0,2})_", candidate)
        if match and VERSION_RE.match(match.group(1)):
            return match.group(1)
    return None


def _extract_bundle(bundle_path: Path, out_dir: Path) -> bool:
    secure_mkdir(out_dir)
    try:
        with zipfile.ZipFile(bundle_path) as zf:
            apk_names = [n for n in zf.namelist() if n.endswith(".apk")]
            if not apk_names:
                print("  ERROR: bundle contains no .apk files")
                return False
            for name in apk_names:
                target = out_dir / Path(name).name
                with zf.open(name) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                chmod_owner_only(target, 0o600)
            print(f"  Extracted {len(apk_names)} APK(s) into {out_dir}")
            return True
    except zipfile.BadZipFile:
        magic = bundle_path.read_bytes()[:4]
        if magic != b"PK\x03\x04":
            print(f"  ERROR: bundle is not a ZIP (magic: {magic!r})")
            return False
        target = out_dir / "base.apk"
        shutil.copy2(bundle_path, target)
        chmod_owner_only(target, 0o600)
        return True


def update_from_apkpure(*, force_abi_regression: bool = False) -> int:
    """Download latest from APKPure, ABI-check, replace the in-repo APK."""
    env = load_env()
    staging = env.cache_subdir("konnect-apk-staging")
    download_dir = staging / "download"
    extract_dir = staging / "extract"
    secure_mkdir(download_dir)
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    secure_mkdir(extract_dir)

    bundle = download_dir / "konnect-bundle.zip"
    bundle.unlink(missing_ok=True)

    success = False
    detected_version = None
    for url in (APKPURE_XAPK_URL, APKPURE_APK_URL):
        ok, final_url = _download_with_retries(url, bundle, attempts=3)
        if ok:
            success = True
            detected_version = _version_from_url(final_url)
            break

    if not success:
        print("  ERROR: APKPure download failed for both XAPK and APK URLs.")
        return 1

    if not _extract_bundle(bundle, extract_dir):
        return 1

    # ABI sanity-check vs current in-repo APK
    new_abis = _abis_in_dir(extract_dir)
    try:
        current_manifest = load_manifest()
        current_abis = current_manifest.get("abis_present", _abis_in_dir(REPO_APK_DIR))
    except HarnessError:
        current_manifest = {}
        current_abis = []
    missing = sorted(set(current_abis) - set(new_abis))
    if missing and not force_abi_regression:
        print()
        print(f"  REFUSING TO UPDATE: new bundle is missing ABI splits {missing}")
        print(f"  Current in-repo APK covers: {sorted(current_abis)}")
        print(f"  New APKPure bundle covers:  {sorted(new_abis)}")
        print()
        print("  APKPure sometimes serves architecture-narrowed bundles based on")
        print("  request fingerprinting. Either retry later or grab a complete")
        print("  XAPK manually (APKMirror's 'all variants' has historically had")
        print("  arm64-v8a + armeabi-v7a + x86_64), unzip it into:")
        print(f"    {extract_dir}")
        print("  then re-run with --force-abi-regression to proceed anyway.")
        return 1

    # Build new manifest
    version = detected_version or "unknown"
    if version != "unknown" and not VERSION_RE.match(version):
        version = "unknown"
    new_manifest = {
        "package": PACKAGE,
        "version": version,
        "source": "apkpure",
        "fetched_at": time.strftime("%Y-%m-%d"),
        "abis_present": new_abis,
        "apks": {
            apk.name: "sha256:" + _sha256(apk)
            for apk in sorted(extract_dir.glob("*.apk"))
        },
    }

    # Atomically replace the in-repo dir
    print()
    print(f"  Replacing {REPO_APK_DIR} with new APK files...")
    # Don't clobber manifest.json until everything else is in place
    for apk in REPO_APK_DIR.glob("*.apk"):
        apk.unlink()
    for apk in extract_dir.glob("*.apk"):
        shutil.copy2(apk, REPO_APK_DIR / apk.name)
    atomic_write_text(
        REPO_APK_DIR / "manifest.json",
        json.dumps(new_manifest, indent=2) + "\n",
        mode=0o644,
    )
    bundle.unlink(missing_ok=True)

    print()
    print("  Update complete. Review with:")
    print("    git status credential-extraction/konnect-apk/")
    print("    git diff credential-extraction/konnect-apk/manifest.json")
    print("    git lfs ls-files credential-extraction/konnect-apk/")
    print()
    print(f"  New version: {version}")
    print(f"  ABIs: {', '.join(new_abis) or '(none)'}")
    return 0


# --- main -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--verify",
        action="store_true",
        help="(default) Check that the in-repo APK matches its manifest.",
    )
    mode.add_argument(
        "--update",
        action="store_true",
        help="Refresh the in-repo APK from APKPure.",
    )
    parser.add_argument(
        "--force-abi-regression",
        action="store_true",
        help="With --update: accept a new bundle that has fewer ABIs than the current one.",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Konnect APK")
    print("=" * 60)
    print()

    if args.update:
        try:
            return update_from_apkpure(force_abi_regression=args.force_abi_regression)
        except HarnessError as exc:
            print(f"ERROR: {exc}")
            return 1

    # Default: verify
    try:
        result = verify_repo_apk()
    except HarnessError as exc:
        print(f"ERROR: {exc}")
        return 1
    for note in result.notes:
        print(f"  {note}")
    print()
    if result.ok:
        print(f"  ✓ Konnect APK ready (version {result.version})")
        return 0
    print(f"  ✗ Konnect APK verification failed (version {result.version})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
