#!/usr/bin/env python3
"""Capture the Kohler Konnect app's `/token` POST against B2C_1A_signin.

How it works:
  1. Run `mitmdump` in its own process group, recording every flow.
  2. Launch the app with Frida + frida_bypass.js (which neutralizes pinning,
     root/emulator detection, and proxy detection in-app), also in its own
     process group.
  3. Wait for the user to sign in (or for `konnect_signin.py` to drive it).
  4. On Ctrl-C or after `--wait-seconds`, tear everything down (group signal
     + escalation), parse the captured flows, and write structured JSON.

The two big resilience properties:
  * children are spawned with `start_new_session=True` so we can signal the
    whole process group, preventing orphaned mitmdump/frida helpers
  * we wait for mitmdump's listen port to accept connections before launching
    Frida (no fixed `time.sleep`)
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import IO
from urllib.parse import parse_qsl, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import (
    EXTRACTION_DIR,
    atomic_write_text,
    chmod_owner_only,
    find_adb,
    find_frida,
    find_mitmdump,
    load_env,
    port_in_use,
    secure_mkdir,
    utc_now_iso,
    wait_for_port,
)

PACKAGE = "com.kohler.hermoth"
FRIDA_SCRIPT = EXTRACTION_DIR / "scripts" / "frida_bypass.js"
TOKEN_PATH_PATTERN = "/token"
# Match the two known JWT endpoints:
#   * b2clogin.com — direct B2C token endpoint (legacy WebView/PKCE flow)
#   * kohlerkonnect-apim.azure-api.net — APIM-proxied ROPC service-account JWT
#     (the one we actually need for the library)
TOKEN_HOST_HINTS = ("b2clogin.com", "kohlerkonnect-apim.azure-api.net")
TOKEN_HOST_HINT = TOKEN_HOST_HINTS[0]  # back-compat for callers that print this


def start_mitmdump(
    mitmdump: str,
    port: str,
    flow_file: Path,
    log_handle: IO[str],
    upstream_client_cert: Path | None = None,
) -> subprocess.Popen:
    cmd = [
        mitmdump,
        "--listen-port", port,
        "--set", "save_stream_file=" + str(flow_file),
        "--set", "stream_large_bodies=10m",
        "--showhost",
        "--flow-detail", "1",
    ]
    if upstream_client_cert and upstream_client_cert.exists():
        # Present this PEM (cert + key) as the upstream client cert for any
        # host that requires mTLS. Kohler's APIM gateway demands one.
        cmd += ["--set", f"client_certs={upstream_client_cert}"]
    print(f"  Starting mitmdump on :{port} → {flow_file}")
    return subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def start_frida(frida: str, log_handle: IO[str]) -> subprocess.Popen:
    cmd = [frida, "-U", "-f", PACKAGE, "-l", str(FRIDA_SCRIPT), "--runtime=v8"]
    print(f"  Launching Konnect via Frida ({PACKAGE})")
    return subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        start_new_session=True,
    )


def wait_for_app_ready(adb: str, timeout: int = 60) -> bool:
    """Wait until the Konnect process is running on the device."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            [adb, "shell", "pidof", PACKAGE],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            return True
        time.sleep(1)
    return False


# Konnect's bootstrap walks through several UI gates that block the /token
# auth call. We drive past each one with a center-of-button tap so the harness
# can run unattended. Coordinates are for the Pixel 5 / Android 11 AVD layout.
LOCATION_PERMISSION_ACTIVITY = ".products.feature.locationpermission.LocationPermissionActivity"
AZURE_LOGIN_ACTIVITY = ".products.feature.sign.presentation.AzureLoginActivity"
CONTINUE_BUTTON_TAP_XY = (540, 2028)   # LocationPermissionActivity "Continue"
SIGN_IN_BUTTON_TAP_XY = (540, 1705)    # AzureLoginActivity "Sign In" — fires /token


def _current_activity(adb: str) -> str:
    """Return the top resumed activity name, or '' if it can't be determined."""
    result = subprocess.run(
        [adb, "shell", "dumpsys", "activity", "activities"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("mResumedActivity") or line.startswith("topResumedActivity"):
            return line
    return ""


def _tap(adb: str, x: int, y: int) -> None:
    subprocess.run(
        [adb, "shell", "input", "tap", str(x), str(y)],
        capture_output=True, timeout=5,
    )


def drive_to_token_call(adb: str, *, max_attempts: int = 25) -> bool:
    """Best-effort: tap through Konnect's UI gates until /token can fire.

    Sequence:
      1. LocationPermissionActivity → tap "Continue"
      2. AzureLoginActivity → tap "Sign In" (this fires GET /token/api/v1/token)
    Returns True once the Sign In tap has been sent. The function is intentionally
    tolerant: if a screen's layout differs, it gives up so the user can drive the
    UI manually.
    """
    sign_in_tapped = False
    for attempt in range(max_attempts):
        activity = _current_activity(adb)
        if LOCATION_PERMISSION_ACTIVITY in activity:
            _tap(adb, *CONTINUE_BUTTON_TAP_XY)
            time.sleep(1.5)
            continue
        if AZURE_LOGIN_ACTIVITY in activity:
            _tap(adb, *SIGN_IN_BUTTON_TAP_XY)
            sign_in_tapped = True
            print(f"  ✓ Tapped Sign In on AzureLoginActivity (attempt {attempt + 1})")
            return True
        # Some other activity (likely a transient splash) — wait briefly and retry
        time.sleep(1.5)
    if sign_in_tapped:
        return True
    print("  ⚠ Could not auto-drive Konnect to the /token call. "
          "Tap through 'Continue' and 'Sign In' on the emulator manually.")
    return False


def parse_token_flows(flow_file: Path) -> list[dict]:
    """Parse the mitmdump stream file and return /token-related entries.

    Resilient to corrupted/truncated flow files — bad flows are skipped and
    logged, good ones still returned.
    """
    try:
        from mitmproxy.io import FlowReader
    except ImportError as exc:
        raise RuntimeError(
            "mitmproxy library not available — run `.venv/bin/pip install mitmproxy`"
        ) from exc

    captured: list[dict] = []
    if not flow_file.exists() or flow_file.stat().st_size == 0:
        return captured

    skipped = 0
    with flow_file.open("rb") as fh:
        reader = FlowReader(fh)
        flow_iter = reader.stream()
        while True:
            try:
                flow = next(flow_iter)
            except StopIteration:
                break
            except Exception as exc:  # truncated/corrupt flow — keep going
                skipped += 1
                if skipped <= 3:  # avoid log spam
                    print(f"    skipped bad flow: {exc}")
                continue

            if not hasattr(flow, "request"):
                continue
            req = flow.request
            if not any(h in req.host for h in TOKEN_HOST_HINTS):
                continue
            if TOKEN_PATH_PATTERN not in req.path.lower():
                continue

            try:
                captured.append(_extract_flow(flow))
            except Exception as exc:
                skipped += 1
                if skipped <= 3:
                    print(f"    flow extract error: {exc}")

    if skipped:
        print(f"    (skipped {skipped} bad/incomplete flows total)")
    return captured


def _extract_flow(flow) -> dict:
    req = flow.request
    req_body = req.get_text(strict=False) or ""
    content_type = req.headers.get("content-type", "")
    parsed_body: dict | str = req_body
    if "x-www-form-urlencoded" in content_type:
        parsed_body = dict(parse_qsl(req_body, keep_blank_values=True))

    resp = getattr(flow, "response", None)
    resp_body = resp.get_text(strict=False) if resp else None

    return {
        "timestamp": dt.datetime.fromtimestamp(req.timestamp_start, tz=dt.timezone.utc).isoformat(),
        "method": req.method,
        "url": req.url,
        "path": req.path,
        "host": req.host,
        "query": dict(parse_qsl(urlparse(req.url).query, keep_blank_values=True)),
        "request_headers": dict(req.headers),
        "request_body_raw": req_body,
        "request_body_parsed": parsed_body,
        "response_status": resp.status_code if resp else None,
        "response_headers": dict(resp.headers) if resp else None,
        "response_body": resp_body,
    }


def write_capture(captures: list[dict], dest: Path) -> None:
    payload = json.dumps({
        "package": PACKAGE,
        "host_hint": TOKEN_HOST_HINT,
        "path_pattern": TOKEN_PATH_PATTERN,
        "count": len(captures),
        "captured_at": utc_now_iso(),
        "flows": captures,
    }, indent=2, default=str)
    atomic_write_text(dest, payload)


def extract_refresh_tokens(captures: list[dict]) -> list[dict]:
    """Scan captured flows for B2C `/oauth2/v2.0/token` responses with refresh_tokens.

    Konnect's MSAL sign-in does a final POST to `b2clogin.com/.../oauth2/v2.0/token`
    that returns a JSON body containing `access_token` + `refresh_token` + claims.
    This function pulls out anything that looks like that and returns the
    refresh_tokens with enough metadata to identify which policy issued them.

    Returns a list of `{"refresh_token": str, "tfp": str|None, "scope": str|None,
    "host": str, "captured_at": str}` — usually just one entry per sign-in.
    """
    found: list[dict] = []
    for flow in captures:
        host = flow.get("host", "")
        if "b2clogin.com" not in host:
            continue
        if "/oauth2/v2.0/token" not in flow.get("path", "").lower():
            continue
        if flow.get("response_status") not in (200, 201):
            continue
        body = flow.get("response_body") or ""
        if not body:
            continue
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            continue
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            continue
        # Decode the access_token for the `tfp` claim (which policy issued it)
        tfp: str | None = None
        scope: str | None = payload.get("scope")
        access_token = payload.get("access_token", "")
        if access_token and access_token.count(".") == 2:
            try:
                import base64

                jwt_payload = access_token.split(".")[1]
                jwt_payload += "=" * ((4 - len(jwt_payload) % 4) % 4)
                claims = json.loads(base64.urlsafe_b64decode(jwt_payload))
                tfp = claims.get("tfp") or claims.get("acr")
                scope = scope or claims.get("scp")
            except Exception:
                pass
        found.append(
            {
                "refresh_token": refresh_token,
                "tfp": tfp,
                "scope": scope,
                "host": host,
                "captured_at": flow.get("timestamp"),
            }
        )
    return found


def write_refresh_token_file(
    refresh_tokens: list[dict], dest: Path, prefer_tfp: str = "B2C_1A_signin"
) -> dict | None:
    """Write the most useful refresh_token to a 0600 file. Returns the chosen entry.

    "Most useful" = the entry whose JWT was issued by `prefer_tfp` (B2C_1A_signin
    by default, since that's what /commands/* requires). Falls back to the
    last captured token if no preferred match exists.
    """
    if not refresh_tokens:
        return None
    preferred = [t for t in refresh_tokens if t.get("tfp") == prefer_tfp]
    chosen = preferred[-1] if preferred else refresh_tokens[-1]
    atomic_write_text(dest, chosen["refresh_token"] + "\n")
    return chosen


def teardown_groups(processes: list[subprocess.Popen]) -> None:
    """SIGTERM each process group; escalate to SIGKILL after a grace period."""
    for proc in processes:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

    # Give them up to 5s to exit cleanly
    deadline = time.time() + 5
    while time.time() < deadline:
        if all(p.poll() is not None for p in processes):
            return
        time.sleep(0.2)

    for proc in processes:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="8080", help="mitmdump listen port (default: 8080)")
    parser.add_argument(
        "--no-frida",
        action="store_true",
        help="Skip launching the app with Frida — useful if it's already running.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=0,
        help=(
            "If >0, run for this many seconds then auto-terminate. Default 0 = "
            "wait for Ctrl-C."
        ),
    )
    args = parser.parse_args(argv)

    print()
    print("=" * 60)
    print("B2C_1A_signin /token capture")
    print("=" * 60)
    print()

    adb = find_adb()
    if not adb:
        print("  ERROR: adb not found. Run `make deps`.")
        return 1
    mitmdump = find_mitmdump()
    if not mitmdump:
        print("  ERROR: mitmdump not found.")
        return 1
    frida = find_frida() if not args.no_frida else None
    if not args.no_frida and not frida:
        print("  ERROR: frida not found.")
        return 1

    port_num = int(args.port)
    if port_in_use(port_num):
        print(
            f"  ERROR: port {port_num} is already in use. "
            f"Run `lsof -i :{port_num}` and stop the existing listener "
            f"(usually an orphaned mitmdump)."
        )
        return 1

    env = load_env()
    captures_dir = env.cache_subdir("token-captures")
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = captures_dir / timestamp
    secure_mkdir(session_dir, 0o700)

    flow_file = session_dir / "flows.mitm"
    mitm_log_path = session_dir / "mitmdump.log"
    frida_log_path = session_dir / "frida.log"
    capture_json = session_dir / "token_capture.json"

    # Upstream client cert for mTLS to the Kohler APIM gateway. Required —
    # without it the gateway returns 403 "Invalid client certificate" and
    # Konnect's sign-in flow refuses to open the B2C WebView.
    upstream_cert_path = env.get("KOHLER_APIM_CLIENT_CERT_PEM").strip()
    upstream_cert = Path(upstream_cert_path).expanduser() if upstream_cert_path else None
    if upstream_cert and upstream_cert.exists():
        print(f"  Upstream client cert: {upstream_cert}")
    else:
        print(
            "  WARNING: KOHLER_APIM_CLIENT_CERT_PEM not set or missing — "
            "APIM mTLS requests will 403. Run `make capture-pfx-password` first."
        )
        upstream_cert = None

    processes: list[subprocess.Popen] = []
    exit_code = 1

    with ExitStack() as stack:
        mitm_log = stack.enter_context(mitm_log_path.open("w"))
        frida_log = stack.enter_context(frida_log_path.open("w"))
        chmod_owner_only(mitm_log_path, 0o600)
        chmod_owner_only(frida_log_path, 0o600)

        mitm = start_mitmdump(mitmdump, args.port, flow_file, mitm_log, upstream_cert)
        processes.append(mitm)

        # Probe the listen port instead of `time.sleep`. mitmdump usually
        # binds within ~500ms but can be slower under load.
        if not wait_for_port("127.0.0.1", port_num, timeout=15):
            print(f"  ERROR: mitmdump did not start listening on :{port_num} within 15s")
            print(f"  See: {mitm_log_path}")
            teardown_groups(processes)
            return 1

        if not args.no_frida:
            frida_proc = start_frida(frida, frida_log)
            processes.append(frida_proc)
            if not wait_for_app_ready(adb, timeout=60):
                print(f"  WARNING: app did not start within 60s — see {frida_log_path}")
            # Konnect's bootstrap walks: splash → LocationPermissionActivity →
            # AzureLoginActivity. /token only fires when "Sign In" is tapped.
            # Drive the UI past these gates so the harness can run unattended.
            time.sleep(6)
            drive_to_token_call(adb)

        print()
        print("  Capture is live. Sign in to the Konnect app in the emulator now.")
        print(f"  Stream file: {flow_file}")
        print(f"  Mitm log:    {mitm_log_path}")
        print(f"  Frida log:   {frida_log_path}")
        print()
        if args.wait_seconds > 0:
            print(f"  Auto-terminating in {args.wait_seconds}s.")
        else:
            print("  Press Ctrl-C when sign-in completes.")
        print()

        try:
            if args.wait_seconds > 0:
                end_at = time.time() + args.wait_seconds
                while time.time() < end_at:
                    if any(p.poll() is not None for p in processes):
                        break
                    time.sleep(1)
            else:
                while True:
                    time.sleep(2)
                    if all(p.poll() is not None for p in processes):
                        print("  All subprocesses exited; stopping.")
                        break
        except KeyboardInterrupt:
            print()
            print("  Ctrl-C — tearing down...")
        finally:
            teardown_groups(processes)

        # mitmdump needs a moment to flush its stream file on shutdown
        time.sleep(1)

    print()
    print("  Parsing captured flows...")
    try:
        captures = parse_token_flows(flow_file)
    except Exception as exc:
        print(f"  ERROR parsing flows: {exc}")
        captures = []

    write_capture(captures, capture_json)

    # Sniff out any B2C refresh_tokens for `KOHLER_B2C_REFRESH_TOKEN`. The
    # /commands/* writes need a B2C_1A_signin-policy token; if the user signed
    # in manually during this session, the OAuth /token POST response
    # contains the refresh_token we need.
    refresh_path = session_dir / "refresh_token.txt"
    refresh_tokens = extract_refresh_tokens(captures)
    chosen = write_refresh_token_file(refresh_tokens, refresh_path) if refresh_tokens else None

    print()
    print("=" * 60)
    print(f"  /token flows captured: {len(captures)}")
    print(f"  → {capture_json}")
    print("=" * 60)
    if refresh_tokens:
        print()
        print("=" * 60)
        print(f"  B2C refresh_tokens captured: {len(refresh_tokens)}")
        for t in refresh_tokens:
            preview = t["refresh_token"][:20] + "…" if t["refresh_token"] else "(empty)"
            print(f"    tfp={t['tfp']} scope={t['scope']!r} token={preview}")
        if chosen:
            print()
            print(f"  Saved best match (tfp={chosen['tfp']}) to:")
            print(f"    {refresh_path}")
            print()
            print("  Activate in env:")
            print(f"    export KOHLER_B2C_REFRESH_TOKEN=$(cat {refresh_path})")
        print("=" * 60)
    if captures:
        first = captures[0]
        print("  First /token POST summary:")
        print(f"    URL:    {first['url']}")
        print(f"    Status: {first['response_status']}")
        body = first.get("request_body_parsed")
        if isinstance(body, dict):
            for k in sorted(body):
                v = body[k]
                shown = v[:80] if isinstance(v, str) else v
                print(f"    body.{k} = {shown}")
        exit_code = 0
    else:
        print("  No /token flows captured. Things to check:")
        print("   - Did the app actually open the sign-in page?")
        print(
            "   - Did `make emulator-mitmproxy-setup` run successfully "
            "(system cert installed)?"
        )
        print(f"   - Look at the raw flow file: {flow_file}")
    print()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
