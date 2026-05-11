"""Capture a Kohler B2C_1A_signin refresh_token via manual OAuth-code flow.

Konnect's MSAL library implements standard OAuth2 authorization-code + PKCE
against the `B2C_1A_signin` policy. This script does the same thing without
needing an Android device: it constructs the /authorize URL with a redirect
URI Kohler has registered (`msauth://com.kohler.hermoth/...`), opens it in
the user's browser, the user signs in, B2C redirects to msauth:// (which
the browser can't open on a Mac — it shows "no application" — but the URL
is visible in the address bar with `?code=...`). The user pastes that URL
back here; the script exchanges the code for tokens.

Steps:

  1. Run this script.
  2. It prints an /authorize URL — copy it into your browser.
  3. Sign in with your Kohler account.
  4. B2C redirects to `msauth://com.kohler.hermoth/...?code=AAA&state=BBB`.
     Your browser will show "this site can't be reached" or "no app to
     handle msauth://" — that's expected.
  5. Copy the FULL URL from the address bar and paste it here when prompted.
  6. The script POSTs to /oauth2/v2.0/token and writes the refresh_token to
     `/Volumes/ring/env/kohler.env` (KOHLER_B2C_REFRESH_TOKEN=…).

The msauth:// redirect URI is registered in Kohler's B2C app (verified from
the bundled msal_config.json in the APK), so B2C will accept this redirect
and issue the auth code. The browser failing to navigate to msauth:// is
inconsequential — we only need to read the URL.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

CLIENT_ID = "8caf9530-1d13-48e6-867c-0f082878debc"
AUTHORITY_PATH = "tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin"
AUTHORITY = f"https://konnectkohler.b2clogin.com/{AUTHORITY_PATH}"
REDIRECT_URI = "msauth://com.kohler.hermoth/2DuDM2vGmcL4bKPn2xKzKpsy68k%3D"
API_AUDIENCE_GUID = "f5d87f3d-bdeb-4933-ab70-ef56cc343744"
SCOPE = (
    f"openid offline_access "
    f"https://konnectkohler.onmicrosoft.com/{API_AUDIENCE_GUID}/apiaccess"
)


def _pkce_pair() -> tuple[str, str]:
    """Generate a (verifier, challenge_S256) PKCE pair per RFC 7636."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _decode_jwt(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


STATE_FILE = "/tmp/kohler_b2c_signin_state.json"


def _build_authorize_url() -> tuple[str, dict]:
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    nonce = secrets.token_urlsafe(16)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "response_mode": "query",
    }
    url = f"{AUTHORITY}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params, safe="/:")
    return url, {"verifier": verifier, "state": state}


def cmd_url(args: argparse.Namespace) -> int:
    url, state = _build_authorize_url()
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh)
    os.chmod(STATE_FILE, 0o600)

    print()
    print("=" * 78)
    print("Kohler B2C_1A_signin refresh-token capture (manual OAuth code flow)")
    print("=" * 78)
    print()
    print("Step 1. Open this URL in your browser:")
    print()
    print(f"    {url}")
    print()
    print("Step 2. Sign in with your real Kohler account.")
    print()
    print("Step 3. The browser redirects to msauth://com.kohler.hermoth/...?code=...")
    print("        and shows 'site can't be reached' or 'no app to open this'.")
    print("        That's expected. Copy the FULL URL from the address bar.")
    print()
    print("Step 4. Run:")
    print("        .venv/bin/python dev/scripts/b2c_signin.py exchange '<paste-url>'")
    print()
    if not args.no_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(url)
    return 0


def cmd_exchange(args: argparse.Namespace) -> int:
    if not os.path.exists(STATE_FILE):
        print(f"  ERROR: no PKCE state file at {STATE_FILE}.")
        print("  Run `b2c_signin.py url` first to generate the authorize URL.")
        return 1
    with open(STATE_FILE) as fh:
        state = json.load(fh)
    verifier = state["verifier"]
    expected_state = state["state"]

    redirected = args.url.strip()
    if not redirected.startswith("msauth://"):
        print(f"  ERROR: expected URL starting with msauth://, got: {redirected[:80]}")
        return 1
    parsed = urllib.parse.urlparse(redirected)
    qs = urllib.parse.parse_qs(parsed.query)
    if "error" in qs:
        print(f"  ERROR from B2C: {qs.get('error')} — {qs.get('error_description', [''])[0]}")
        return 1
    code = qs.get("code", [""])[0]
    returned_state = qs.get("state", [""])[0]
    if not code:
        print(f"  ERROR: no `code` query param in URL. Query keys: {list(qs)}")
        return 1
    if returned_state != expected_state:
        print("  WARNING: state mismatch. Continuing anyway.")

    print("  Exchanging auth code for tokens...")
    token_params = {
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": urllib.parse.unquote(REDIRECT_URI),
        "code_verifier": verifier,
        "scope": SCOPE,
    }
    req = urllib.request.Request(
        f"{AUTHORITY}/oauth2/v2.0/token",
        data=urllib.parse.urlencode(token_params).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"  ERROR: token exchange returned {e.code}: {body[:400]}")
        return 1

    refresh_token = payload.get("refresh_token", "")
    access_token = payload.get("access_token", "")
    if not refresh_token:
        print(f"  ERROR: no refresh_token in response. Keys: {list(payload.keys())}")
        return 1

    claims = _decode_jwt(access_token)
    print()
    print("  Access token claims:")
    for k in ("aud", "iss", "tfp", "scp", "oid", "name", "emails"):
        if k in claims:
            print(f"    {k}: {claims[k]}")
    print(f"  Refresh token length: {len(refresh_token)} chars")
    print()

    env_line = f"export KOHLER_B2C_REFRESH_TOKEN={refresh_token}"
    env_path = args.env_file
    if env_path and os.path.exists(env_path):
        with open(env_path) as fh:
            lines = fh.readlines()
        existing = [
            i for i, line in enumerate(lines)
            if line.strip().startswith(("export KOHLER_B2C_REFRESH_TOKEN=",
                                        "KOHLER_B2C_REFRESH_TOKEN="))
        ]
        new_line = env_line + "\n"
        if existing:
            lines[existing[0]] = new_line
            action = "Updated"
        else:
            lines.append(new_line)
            action = "Appended"
        with open(env_path, "w") as fh:
            fh.writelines(lines)
        os.chmod(env_path, 0o600)
        print(f"  ✓ {action} KOHLER_B2C_REFRESH_TOKEN in {env_path}")
    else:
        print(f"  Env file {env_path} not found. Add manually:")
        print(f"    {env_line}")
    print()
    # PKCE state served its purpose
    with contextlib.suppress(OSError):
        os.unlink(STATE_FILE)
    print("  Now test:")
    print("    .venv/bin/pytest tests/integration/test_credentials_health.py -q")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_url = sub.add_parser("url", help="Step 1: generate the /authorize URL.")
    p_url.add_argument("--no-browser", action="store_true",
                       help="Don't auto-open the browser.")
    p_url.set_defaults(func=cmd_url)

    p_ex = sub.add_parser(
        "exchange",
        help="Step 2: exchange the redirected msauth:// URL for tokens.",
    )
    p_ex.add_argument("url", help="The msauth://com.kohler.hermoth/...?code=... URL.")
    p_ex.add_argument("--env-file", default="/Volumes/ring/env/kohler.env",
                      help="Where to write KOHLER_B2C_REFRESH_TOKEN.")
    p_ex.set_defaults(func=cmd_exchange)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
