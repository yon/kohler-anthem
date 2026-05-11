#!/usr/bin/env python3
"""Patch the in-repo Konnect APK to remove Kohler's runtime root check.

Konnect 3.0.1 has a class `Is.b` whose method `n()` ORs together several
root-detection checks (`/system/xbin/su` exists, `Build.TAGS == "test-keys"`,
Magisk binary detection, busybox detection, etc.). On a typical AVD or
rooted Android device, several of these naturally return true, so
`n()` returns true and `SplashActivity.onCreate` displays the dialog
"This phone can't be used for Kohler Konnect app." and refuses to advance.

Frida hooks on `Is.b.n()` install successfully but never fire on Android 11
AVD (ART inlines the boolean sub-methods, even after `deoptimizeEverything`).
The reliable fix is to patch the smali bytecode of `n()` to always return
false, then resign the APK.

Steps:
  1. Decompile credential-extraction/konnect-apk/base.apk with apktool
  2. Replace Is.b.n()'s body with `return 0`
  3. Strip the broken `android:resource="@null"` meta-data tag from
     AndroidManifest.xml (apktool rebuild can't handle it)
  4. Rebuild the APK with apktool
  5. zipalign + apksigner sign with ~/.android/debug.keystore
  6. Re-sign the split APKs (they must share the signing cert with base)
  7. Drop everything into credential-extraction/konnect-apk-patched/

The patched APK is installed via:
  adb install-multiple -i com.android.vending base.apk split_config.*.apk

The `-i com.android.vending` is critical — Konnect's Pairip license check
shows "Check that Google Play is enabled" if the installer-package is
anything else (or unset). Frida bypasses the remainder of the Pairip flow.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import EXTRACTION_DIR, HarnessError, atomic_write_text, find_tool, run

REPO_APK_DIR = EXTRACTION_DIR / "konnect-apk"
PATCHED_DIR = EXTRACTION_DIR / "konnect-apk-patched"
PATCH_DIR = EXTRACTION_DIR / "patches"

KEYSTORE = Path.home() / ".android" / "debug.keystore"
KEYSTORE_ALIAS = "androiddebugkey"
KEYSTORE_PASS = "android"

# The exact smali method body that replaces Is.b.n()'s logic
PATCHED_N_METHOD = """.method public n()Z
    .locals 1
    const/4 v0, 0x0
    return v0
.end method
"""


def _find_build_tool(name: str) -> str:
    """Locate apksigner / zipalign — try $PATH then standard Android SDK paths."""
    tool = find_tool(
        name,
        f"/opt/homebrew/share/android-commandlinetools/build-tools/35.0.0/{name}",
        f"/usr/local/share/android-commandlinetools/build-tools/35.0.0/{name}",
    )
    if not tool:
        raise HarnessError(
            f"{name} not found. Install with: sdkmanager 'build-tools;35.0.0'"
        )
    return tool


def _ensure_debug_keystore() -> None:
    if KEYSTORE.exists():
        return
    print(f"  Generating debug keystore at {KEYSTORE}")
    KEYSTORE.parent.mkdir(parents=True, exist_ok=True)
    keytool = find_tool(
        "keytool", "/opt/homebrew/opt/openjdk/bin/keytool"
    )
    if not keytool:
        raise HarnessError("keytool not found (need JDK installed)")
    run(
        [
            keytool, "-genkey", "-v",
            "-keystore", str(KEYSTORE),
            "-alias", KEYSTORE_ALIAS,
            "-storepass", KEYSTORE_PASS,
            "-keypass", KEYSTORE_PASS,
            "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000",
            "-dname", "CN=Android Debug,O=Android,C=US",
        ],
        timeout=60,
    )


def _apktool_decompile(apk_path: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    apktool = find_tool("apktool")
    if not apktool:
        raise HarnessError("apktool not found. Install with: brew install apktool")
    print(f"  apktool d → {dest}")
    run([apktool, "d", "-o", str(dest), str(apk_path)], timeout=600)


def _patch_isb_smali(decompiled_dir: Path) -> None:
    """Replace Is.b.n()'s body with `return false`."""
    smali_path = decompiled_dir / "smali_classes7" / "Is" / "b.smali"
    if not smali_path.exists():
        # Older Konnect builds had Is.b in a different smali_classes dir
        candidates = list(decompiled_dir.glob("smali*/Is/b.smali"))
        if not candidates:
            raise HarnessError(f"Is.b smali not found in {decompiled_dir}")
        smali_path = candidates[0]

    text = smali_path.read_text()
    pattern = re.compile(
        r"^\.method public n\(\)Z\b.*?^\.end method\s*$",
        re.DOTALL | re.MULTILINE,
    )
    new_text, count = pattern.subn(PATCHED_N_METHOD.rstrip() + "\n", text)
    if count == 0:
        raise HarnessError(f"could not locate `.method public n()Z` in {smali_path}")
    smali_path.write_text(new_text)
    print(f"  patched {smali_path} (Is.b.n now returns false)")


def _fix_manifest(decompiled_dir: Path) -> None:
    """Remove the broken `android:resource=\"@null\"` meta-data line."""
    manifest = decompiled_dir / "AndroidManifest.xml"
    if not manifest.exists():
        return
    text = manifest.read_text()
    new_text = re.sub(
        r'^\s*<meta-data[^/>]*default_notification_icon[^/>]*android:resource="@null"\s*/>\s*\n',
        "",
        text,
        flags=re.MULTILINE,
    )
    if new_text != text:
        manifest.write_text(new_text)
        print(f"  patched {manifest} (removed @null resource meta-data)")


def _apktool_build(decompiled_dir: Path, out_apk: Path) -> None:
    apktool = find_tool("apktool")
    print(f"  apktool b → {out_apk}")
    run([apktool, "b", "-o", str(out_apk), str(decompiled_dir)], timeout=600)


def _sign_apk(input_apk: Path, output_apk: Path) -> None:
    """zipalign + apksigner sign."""
    zipalign = _find_build_tool("zipalign")
    apksigner = _find_build_tool("apksigner")
    with tempfile.NamedTemporaryFile(suffix=".aligned.apk", delete=False) as tmp:
        aligned = Path(tmp.name)
    try:
        run([zipalign, "-p", "-f", "4", str(input_apk), str(aligned)], timeout=120)
        run(
            [
                apksigner, "sign",
                "--ks", str(KEYSTORE),
                "--ks-pass", f"pass:{KEYSTORE_PASS}",
                "--ks-key-alias", KEYSTORE_ALIAS,
                "--key-pass", f"pass:{KEYSTORE_PASS}",
                "--out", str(output_apk),
                str(aligned),
            ],
            timeout=180,
        )
    finally:
        aligned.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def patch(*, force: bool = False) -> int:
    if not REPO_APK_DIR.is_dir():
        raise HarnessError(f"missing source APK dir: {REPO_APK_DIR}")
    base_apk = REPO_APK_DIR / "base.apk"
    if not base_apk.exists():
        raise HarnessError(f"missing {base_apk} — run `git lfs pull` first")

    if PATCHED_DIR.exists() and not force:
        print(f"  {PATCHED_DIR} already exists; pass --force to rebuild.")
        return 0

    _ensure_debug_keystore()

    with tempfile.TemporaryDirectory() as work_str:
        work = Path(work_str)
        decompiled = work / "decompiled"
        _apktool_decompile(base_apk, decompiled)
        _patch_isb_smali(decompiled)
        _fix_manifest(decompiled)

        unsigned = work / "unsigned.apk"
        _apktool_build(decompiled, unsigned)

        PATCHED_DIR.mkdir(parents=True, exist_ok=True)
        signed_base = PATCHED_DIR / "base.apk"
        _sign_apk(unsigned, signed_base)
        print(f"  signed base → {signed_base}")

        # Re-sign each split with the same keystore (Android requires matching signers)
        for split in REPO_APK_DIR.glob("split_config.*.apk"):
            out = PATCHED_DIR / split.name
            _sign_apk(split, out)
            print(f"  signed split → {out}")

    # Write manifest
    apks = sorted(PATCHED_DIR.glob("*.apk"))
    manifest = {
        "package": "com.kohler.hermoth",
        "version": "3.0.1",
        "source": "patched-from-konnect-apk",
        "signed_by": "Android Debug (CN=Android Debug,O=Android,C=US)",
        "patches_applied": [
            "smali_classes7/Is/b.smali: replaced n() body with `return false`",
            "AndroidManifest.xml: removed broken default_notification_icon meta-data",
        ],
        "install_command": (
            "adb install-multiple -i com.android.vending " + " ".join(p.name for p in apks)
        ),
        "apks": {p.name: "sha256:" + _sha256_file(p) for p in apks},
    }
    atomic_write_text(
        PATCHED_DIR / "manifest.json",
        json.dumps(manifest, indent=2) + "\n",
        mode=0o644,
    )

    # Save the smali diff for posterity
    PATCH_DIR.mkdir(parents=True, exist_ok=True)
    diff_path = PATCH_DIR / "Is_b_n_return_false.smali"
    atomic_write_text(diff_path, PATCHED_N_METHOD, mode=0o644)

    print()
    print(f"  Patched APK bundle ready at {PATCHED_DIR}")
    print(f"  Install with: cd {PATCHED_DIR} && adb install-multiple -i com.android.vending *.apk")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-patch even if konnect-apk-patched/ exists.",
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("Patching Konnect APK (Is.b.n() → return false)")
    print("=" * 60)
    print()
    try:
        return patch(force=args.force)
    except HarnessError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
