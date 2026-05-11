#!/usr/bin/env python3
"""End-to-end harness for capturing the Kohler Konnect /token request.

Runs the full pipeline from a clean machine:

  1. Verify required tools are installed and the env file has what it needs.
  2. Verify (or hash-check) the in-repo Konnect APK.
  3. Patch the APK to bypass Konnect's runtime root check (`Is.b.n()`).
  4. Boot the KohlerExtraction Android Virtual Device (AVD) with a writable
     /system partition.
  5. Push frida-server matching the host's frida-tools version.
  6. Install the patched APK with `-i com.android.vending` (Pairip check).
  7. Install the mitmproxy CA into /system/etc/security/cacerts.
  8. If KOHLER_APIM_CLIENT_CERT_PASSWORD is missing, run a short Frida
     capture against KeyStore.load to recover the PKCS12 password.
  9. Extract res/raw/app_certificate.p12 → PEM for mitmdump upstream mTLS.
 10. Hand off to `token_capture.py` (mitmdump + Frida) to record the
     service-account JWT.

Each step is implemented as a separate script under scripts/ so individual
pieces can be re-run independently. This file's only job is orchestration.

Side effects worth noting:
  - Every run creates `<cache>/harness-runs/<timestamp>/` with `run.log`,
    `summary.json`, and `versions.json` so failures are diagnosable after
    the fact.
  - On Ctrl-C, the orchestrator signals every child process group and waits
    for cleanup before exiting.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from env_lib import (  # noqa: E402
    EXTRACTION_DIR,
    PROJECT_ROOT,
    RunContext,
    adb_device_connected,
    atomic_write_text,
    find_adb,
    find_frida,
    find_mitmdump,
    find_openssl,
    find_python,
    load_env,
    run,
    utc_now_iso,
    venv_exists,
)

VENV_DIR = PROJECT_ROOT / ".venv"
PATCHED_APK_MANIFEST = EXTRACTION_DIR / "konnect-apk-patched" / "manifest.json"
# The harness requires no env keys to boot the AVD. Cert-extraction needs
# KOHLER_APIM_CLIENT_CERT_PEM (path) and KOHLER_APIM_CLIENT_CERT_PASSWORD
# (recovered automatically by the capture-pfx-password step when missing).
REQUIRED_ENV_KEYS: tuple[str, ...] = ()


@dataclass
class StepResult:
    name: str
    exit_code: int
    skipped: bool = False
    notes: str = ""


@dataclass
class HarnessRun:
    timestamp: str
    started_at: str
    ended_at: str = ""
    overall_exit: int = 0
    steps: list[StepResult] = field(default_factory=list)


def _step(name: str) -> None:
    print()
    print("━" * 70)
    print(f"▶  {name}")
    print("━" * 70)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def run_script(script: str, *args: str, log_path: Path | None = None) -> int:
    """Run a sibling script. If log_path is given, tee output there."""
    python = find_python()
    cmd = [python, str(SCRIPTS_DIR / script), *args]
    if log_path is None:
        return subprocess.call(cmd)

    # Tee subprocess output to both stdout and the log file
    with log_path.open("ab") as log:
        log.write(f"\n=== {script} {' '.join(args)} ===\n".encode())
        log.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, b""):
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
                log.write(line)
                log.flush()
            return proc.wait()
        except KeyboardInterrupt:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            raise


def check_prereqs() -> tuple[bool, list[str]]:
    """Tool + env-file presence check. Returns (ok, missing-or-warnings)."""
    _step("Verifying prerequisites")
    ok = True
    missing: list[str] = []
    for name, finder in [
        ("adb", find_adb),
        ("frida", find_frida),
        ("mitmdump", find_mitmdump),
        ("openssl", find_openssl),
    ]:
        path = finder()
        if path:
            _ok(f"{name} → {path}")
        else:
            _fail(f"{name} not found")
            ok = False
            missing.append(name)

    if not venv_exists():
        _fail(f"venv missing at {VENV_DIR}; run `make venv` (or `make deps`)")
        ok = False
        missing.append("venv")
    else:
        _ok(f"venv: {VENV_DIR}")

    return ok, missing


def secrets_check() -> tuple[bool, list[str]]:
    """Verify the env file exists and is readable. No env keys are required
    up-front anymore — capture-pfx-password / extract-client-cert run as part
    of the harness flow and persist their findings."""
    _step("Verifying secrets")
    env = load_env()
    if not env.env_file.exists():
        _fail(f"env file does not exist: {env.env_file}")
        _fail(
            "Run `make secrets-init` (creates a stub) and `make secrets-link` "
            "(creates the .env symlink), then fill in the values."
        )
        return False, ["env_file"]
    if env.env_file.is_symlink() and not env.env_file_resolved.exists():
        _fail(f"env file symlink is broken: {env.env_file} → {os.readlink(env.env_file)}")
        _fail("Is /Volumes/ring/ mounted?")
        return False, ["env_file"]
    _ok(f"env file: {env.env_file} → {env.env_file_resolved}")
    if REQUIRED_ENV_KEYS:
        from env_lib import MissingEnvError

        try:
            env.require(*REQUIRED_ENV_KEYS)
        except MissingEnvError as exc:
            _fail(str(exc))
            return False, list(exc.missing)
        _ok(f"required keys present: {', '.join(REQUIRED_ENV_KEYS)}")
    return True, []


def collect_versions() -> dict:
    """Capture tool versions for the run summary."""
    versions: dict[str, str] = {}

    for tool, finder in [
        ("frida", find_frida),
        ("mitmdump", find_mitmdump),
        ("adb", find_adb),
        ("openssl", find_openssl),
    ]:
        path = finder()
        if not path:
            versions[tool] = "not-found"
            continue
        result = run([path, "--version"], timeout=5)
        out = (result.stdout or result.stderr).strip().splitlines()
        versions[tool] = out[0][:120] if out else f"exit={result.returncode}"

    # Konnect APK version comes from the cache's `latest/manifest.json`
    try:
        env = load_env()
        manifest = env.cache_subdir("konnect-apk") / "latest" / "manifest.json"
        if manifest.exists():
            versions["konnect_apk"] = json.loads(manifest.read_text()).get("version", "unknown")
        else:
            versions["konnect_apk"] = "not-fetched"
    except Exception as exc:
        versions["konnect_apk"] = f"error: {exc}"

    return versions


def write_summary(run_ctx: RunContext, harness_run: HarnessRun) -> None:
    payload = {
        "timestamp": harness_run.timestamp,
        "started_at": harness_run.started_at,
        "ended_at": harness_run.ended_at,
        "overall_exit": harness_run.overall_exit,
        "steps": [
            {"name": s.name, "exit_code": s.exit_code, "skipped": s.skipped, "notes": s.notes}
            for s in harness_run.steps
        ],
    }
    atomic_write_text(run_ctx.summary_path, json.dumps(payload, indent=2))


def write_versions(run_ctx: RunContext, versions: dict) -> None:
    atomic_write_text(run_ctx.versions_path, json.dumps(versions, indent=2))


def maybe_step(harness_run: HarnessRun, name: str, fn, *, skip: bool = False) -> int:
    """Record a step's result. Returns the step's exit code."""
    if skip:
        harness_run.steps.append(StepResult(name, 0, skipped=True))
        _ok(f"skipped: {name}")
        return 0
    code = fn()
    harness_run.steps.append(StepResult(name, code))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-apk-fetch",
        action="store_true",
        help="(Deprecated, ignored.) The harness uses the in-repo LFS-tracked APK.",
    )
    parser.add_argument(
        "--skip-capture",
        action="store_true",
        help="Run everything up to and including cert-extract, then stop.",
    )
    parser.add_argument(
        "--force-apk-download",
        action="store_true",
        help="(Deprecated, ignored.) Use `make apk-update` to refresh the in-repo APK.",
    )
    parser.add_argument(
        "--force-apk-patch",
        action="store_true",
        help="Re-run apktool patch + resign even if konnect-apk-patched/ exists.",
    )
    parser.add_argument(
        "--recreate-emulator",
        action="store_true",
        help="Delete and recreate the KohlerExtraction AVD before starting.",
    )
    args = parser.parse_args(argv)

    print()
    print("╔" + "═" * 68 + "╗")
    print("║  Kohler Konnect /token capture harness".ljust(69) + "║")
    print("╚" + "═" * 68 + "╝")

    env = load_env()
    run_ctx = RunContext.new(env)
    harness_run = HarnessRun(timestamp=run_ctx.timestamp, started_at=utc_now_iso())
    print()
    print(f"  Run log: {run_ctx.log_path}")
    print(f"  Summary: {run_ctx.summary_path}")
    print(f"  Versions: {run_ctx.versions_path}")

    # Versions snapshot at the top — useful even if the run fails immediately
    versions = collect_versions()
    write_versions(run_ctx, versions)

    overall_exit = 0
    try:
        prereqs_ok, missing_tools = check_prereqs()
        harness_run.steps.append(
            StepResult(
                "prereqs",
                0 if prereqs_ok else 1,
                notes=("missing: " + ", ".join(missing_tools)) if missing_tools else "",
            )
        )
        if not prereqs_ok:
            print()
            print("  Resolve the missing tools above and re-run.")
            print("  (Most can be installed with: cd credential-extraction && make deps)")
            overall_exit = 1
            return overall_exit

        secrets_ok, missing_keys = secrets_check()
        harness_run.steps.append(
            StepResult(
                "secrets-check",
                0 if secrets_ok else 1,
                notes=("missing: " + ", ".join(missing_keys)) if missing_keys else "",
            )
        )
        if not secrets_ok:
            overall_exit = 1
            return overall_exit

        _step("Verifying in-repo Konnect APK (git LFS)")
        code = run_script("apk_fetch.py", "--verify", log_path=run_ctx.log_path)
        harness_run.steps.append(StepResult("apk-verify", code))
        if code != 0:
            overall_exit = code
            return overall_exit

        _step("Patching APK (Is.b.n() → return false, resign with debug key)")
        patch_args = ["--force"] if args.force_apk_patch else []
        code = run_script("apk_patch.py", *patch_args, log_path=run_ctx.log_path)
        harness_run.steps.append(StepResult("apk-patch", code))
        if code != 0:
            overall_exit = code
            return overall_exit

        _step("Starting Android Virtual Device (KohlerExtraction)")
        avd_args = ["--recreate"] if args.recreate_emulator else []
        code = run_script("avd_setup.py", *avd_args, log_path=run_ctx.log_path)
        harness_run.steps.append(StepResult("avd-setup", code))
        if code != 0:
            overall_exit = code
            return overall_exit

        if not adb_device_connected():
            _fail("Emulator not reachable via adb after setup. Aborting.")
            harness_run.steps.append(StepResult("adb-reachable", 1))
            overall_exit = 1
            return overall_exit
        _ok("Emulator is up and reachable via adb")

        _step("Installing frida-server on emulator")
        code = run_script("frida_setup.py", log_path=run_ctx.log_path)
        harness_run.steps.append(StepResult("frida-setup", code))
        if code != 0:
            overall_exit = code
            return overall_exit

        _step("Installing patched Konnect APK (-i com.android.vending)")
        code = run_script("emulator_apk_install.py", "--patched",
                          log_path=run_ctx.log_path)
        harness_run.steps.append(StepResult("apk-install-patched", code))
        if code != 0:
            overall_exit = code
            return overall_exit

        _step("Installing mitmproxy CA + configuring proxy")
        code = run_script("mitmproxy_setup.py", log_path=run_ctx.log_path)
        harness_run.steps.append(StepResult("mitmproxy-setup", code))
        if code != 0:
            overall_exit = code
            return overall_exit

        # If the env doesn't already hold the PKCS12 password, recover it now
        # by attaching Frida to a fresh Konnect launch and reading the
        # KeyStore.load() arg. The script returns 0 on success.
        env = load_env()
        if not env.get("KOHLER_APIM_CLIENT_CERT_PASSWORD"):
            _step("Recovering PKCS12 password via Frida (KeyStore.load hook)")
            code = run_script("capture_pfx_password.py", log_path=run_ctx.log_path)
            harness_run.steps.append(StepResult("capture-pfx-password", code))
            if code != 0:
                _fail(
                    "Could not recover the PKCS12 password automatically. "
                    "Set KOHLER_APIM_CLIENT_CERT_PASSWORD in the env file or "
                    "re-run `make capture-pfx-password` separately."
                )
                overall_exit = code
                return overall_exit
        else:
            maybe_step(harness_run, "capture-pfx-password", lambda: 0, skip=True)

        # Extract res/raw/app_certificate.p12 → PEM for upstream mTLS.
        env = load_env()
        if env.get("KOHLER_APIM_CLIENT_CERT_PASSWORD"):
            _step("Extracting APIM mTLS client cert → PEM")
            code = run_script("extract_client_cert.py", log_path=run_ctx.log_path)
            harness_run.steps.append(StepResult("extract-client-cert", code))
            if code != 0:
                overall_exit = code
                return overall_exit
        else:
            maybe_step(harness_run, "extract-client-cert", lambda: 0, skip=True)

        # Refresh versions now that more is known (apk version present)
        write_versions(run_ctx, collect_versions())

        if args.skip_capture:
            print()
            _ok("Setup complete. Run `make emulator-token-capture` when ready.")
            return 0

        _step("Running token capture (mitmdump + Frida, upstream mTLS on)")
        code = run_script("token_capture.py", log_path=run_ctx.log_path)
        harness_run.steps.append(StepResult("token-capture", code))
        overall_exit = code
        return overall_exit
    except KeyboardInterrupt:
        print()
        print("  Ctrl-C — exiting (children received SIGTERM in their own groups).")
        overall_exit = 130
        return overall_exit
    finally:
        harness_run.ended_at = utc_now_iso()
        harness_run.overall_exit = overall_exit
        try:
            write_summary(run_ctx, harness_run)
            print()
            print(f"  Wrote summary: {run_ctx.summary_path}")
        except Exception as exc:
            print(f"  WARNING: failed to write run summary: {exc}")


if __name__ == "__main__":
    sys.exit(main())
