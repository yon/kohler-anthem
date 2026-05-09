#!/usr/bin/env python3
"""Interactive OAuth Authorization Code + PKCE sign-in for B2C_1A_signin.

This is the helper that drives the one-time interactive sign-in. After it
runs once, the resulting refresh token is enough to keep the integration
authenticated across HA restarts (until the user explicitly signs out or the
refresh token TTL is reached).

Workflow:
    1. Generate a PKCE pair.
    2. Spin up a loopback HTTP server on 127.0.0.1:<random-port>.
    3. Open the B2C_1A_signin authorize URL in the default browser.
    4. The user signs in; B2C redirects back to the loopback server with
       `?code=...&state=...`.
    5. Exchange the code for tokens at the B2C_1A_signin token endpoint
       (sending the code_verifier; no client_secret — this is a public client).
    6. Persist tokens to a JSON file (token_store).

After step 6, run `make health-check` (or just import the resulting JSON
into an HA config entry) and the `/commands/gcs/*` endpoints should classify
as OK / BAD_REQUEST instead of BACKEND_FORBIDDEN.

Usage:
    python dev/scripts/oauth_login.py \\
        --client-id "$KOHLER_CLIENT_ID" \\
        --apim-key "$KOHLER_APIM_KEY" \\
        --api-resource "$KOHLER_API_RESOURCE" \\
        --output ~/.kohler-tokens.json

Or read those values from credential-extraction/kohler-credentials.yaml:

    python dev/scripts/oauth_login.py \\
        --yaml credential-extraction/kohler-credentials.yaml \\
        --output ~/.kohler-tokens.json

If `--no-browser` is passed, the URL is printed and the user is asked to
paste the redirected URL back in (useful when running on a headless host).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import socket
import sys
import urllib.parse
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, ClassVar

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kohler_anthem.auth import KohlerOAuthAuth, TokenInfo  # noqa: E402
from kohler_anthem.config import KohlerOAuthConfig  # noqa: E402

_LOGGER = logging.getLogger("oauth_login")


# ---------------------------------------------------------------------------
# JSON-file TokenStore
# ---------------------------------------------------------------------------


class JsonFileTokenStore:
    """Persist TokenInfo to a JSON file. Used by this helper and as a model
    implementation for callers writing their own TokenStore."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self) -> TokenInfo | None:
        if not self._path.exists():
            return None
        with self._path.open() as f:
            data = json.load(f)
        return TokenInfo(**data)

    async def save(self, token: TokenInfo) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 0600 — refresh token is a long-lived secret.
        with self._path.open("w") as f:
            json.dump(asdict(token), f, indent=2)
        self._path.chmod(0o600)


# ---------------------------------------------------------------------------
# Loopback redirect catcher
# ---------------------------------------------------------------------------


class _CodeCatcher(BaseHTTPRequestHandler):
    """One-shot HTTP server: capture the OAuth redirect query and reply 200."""

    received: ClassVar[dict[str, str]] = {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        type(self).received = params
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if params.get("error"):
            body = (
                f"<h2>Sign-in failed</h2><p>{params.get('error')}: "
                f"{params.get('error_description', '')}</p>"
                "<p>You can close this tab and check the terminal for details.</p>"
            )
        else:
            body = (
                "<h2>Sign-in complete.</h2>"
                "<p>You can close this tab. The terminal will continue.</p>"
            )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        _LOGGER.debug("loopback: " + format, *args)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_redirect(
    *,
    expected_state: str,
    redirect_path: str,
    server: HTTPServer,
    timeout_s: int,
) -> dict[str, str]:
    """Block until the loopback server captures a request with state=expected."""
    server.timeout = 1
    deadline = timeout_s
    elapsed = 0
    while elapsed < deadline:
        server.handle_request()
        params = _CodeCatcher.received
        if params and params.get("state") == expected_state:
            return params
        # Different state, or no request yet; reset and keep waiting.
        if params:
            _CodeCatcher.received = {}
        elapsed += 1
    raise TimeoutError(
        f"No OAuth redirect received within {timeout_s}s. "
        f"Did you complete the browser sign-in? Expected redirect to {redirect_path}."
    )


# ---------------------------------------------------------------------------
# Credential loader — mirrors health_check.py's loader
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print(f"warning: PyYAML not installed; cannot read {path}", file=sys.stderr)
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def resolve_credentials(args: argparse.Namespace) -> dict[str, str]:
    yaml_data = _load_yaml(args.yaml) if args.yaml else {}
    pairs = {
        "client_id": (args.client_id, "kohler_client_id"),
        "apim_subscription_key": (args.apim_key, "kohler_apim_key"),
        "api_resource": (args.api_resource, "kohler_api_resource"),
    }
    out: dict[str, str] = {}
    for field, (cli_val, yaml_key) in pairs.items():
        value = cli_val or yaml_data.get(yaml_key)
        if value and not value.startswith("YOUR_VALUE"):
            out[field] = value
    missing = [k for k in pairs if k not in out]
    if missing:
        sys.exit(
            f"error: missing required value(s): {', '.join(missing)}. "
            "Provide via CLI flags or --yaml."
        )
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    creds = resolve_credentials(args)

    # Pick a port now and bake it into the redirect URI. In `--no-browser` mode
    # we use a well-known dummy port (the redirect doesn't have to be reachable —
    # the user pastes the URL back); otherwise we pick a free ephemeral port.
    port = 8765 if args.no_browser else _free_port()
    redirect_uri = f"http://127.0.0.1:{port}/oauth/callback"

    config = KohlerOAuthConfig(
        client_id=creds["client_id"],
        apim_subscription_key=creds["apim_subscription_key"],
        api_resource=creds["api_resource"],
        redirect_uri=redirect_uri,
    )
    store = JsonFileTokenStore(args.output)
    auth = KohlerOAuthAuth(config, token_store=store)

    state = secrets.token_urlsafe(16)
    verifier, challenge = KohlerOAuthAuth.generate_pkce_pair()
    authorize_url = auth.build_authorize_url(state=state, code_challenge=challenge)

    print(f"Authorize URL:\n  {authorize_url}\n")

    if args.no_browser:
        print(
            "Open the URL above in any browser, complete sign-in, then paste "
            "the FULL URL of the page your browser ends up on (it will look "
            "like 'http://127.0.0.1:8765/oauth/callback?code=...&state=...')."
        )
        pasted = input("Redirect URL: ").strip()
        params = {
            k: v[0]
            for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).items()
        }
        if params.get("state") != state:
            sys.exit(f"error: state mismatch (got {params.get('state')!r}, expected {state!r})")
    else:
        server = HTTPServer(("127.0.0.1", port), _CodeCatcher)
        Thread(target=lambda: webbrowser.open(authorize_url, new=1, autoraise=True)).start()
        print(f"Listening on http://127.0.0.1:{port}/oauth/callback for the redirect...")
        try:
            params = _wait_for_redirect(
                expected_state=state,
                redirect_path=redirect_uri,
                server=server,
                timeout_s=args.timeout,
            )
        finally:
            server.server_close()

    if "error" in params:
        sys.exit(
            f"error from B2C: {params.get('error')}: {params.get('error_description', '')}"
        )

    code = params.get("code")
    if not code:
        sys.exit(f"error: redirect did not include a code. Got params: {params}")

    print("Exchanging authorization code for token...")
    async with aiohttp.ClientSession() as session:
        token = await auth.exchange_code_for_token(
            session, code=code, code_verifier=verifier
        )

    print(f"\nTokens written to {args.output} (chmod 600).")
    print(f"  access_token expires_at: {token.expires_at}")
    print(f"  refresh_token: {token.refresh_token[:8]}... (truncated)")
    print()
    print("Phase 0 verification — try a forbidden command-write probe with the new token:")
    print()
    print("  python -c \"")
    print("import asyncio, aiohttp, json")
    print(f"token = json.load(open({str(args.output)!r}))['access_token']")
    print(f"key = {creds['apim_subscription_key']!r}")
    print("async def go():")
    print("    async with aiohttp.ClientSession() as s:")
    print(
        "        async with s.post('https://api-kohler-us.kohler.io"
        "/platform/api/v1/commands/gcs/solowritesystem',"
    )
    print("            headers={'Authorization': f'Bearer {token}',")
    print("                     'Ocp-Apim-Subscription-Key': key,")
    print("                     'Content-Type': 'application/json'},")
    print("            json={}) as r:")
    print("            print(r.status, await r.text())")
    print("asyncio.run(go())\"")
    print()
    print(
        "If that prints HTTP 400 (validation error — auth passed) instead of 403 "
        "(BACKEND_FORBIDDEN), Phase 0 is verified and the auth-rewrite hypothesis "
        "is confirmed."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--client-id", help="Azure AD B2C client_id")
    parser.add_argument("--apim-key", help="APIM subscription key")
    parser.add_argument("--api-resource", help="API resource id (used in scope)")
    parser.add_argument(
        "--yaml",
        type=Path,
        default=None,
        help="Read missing values from this YAML "
        "(e.g. credential-extraction/kohler-credentials.yaml)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="JSON file to write tokens to (will be chmod 600)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open the browser; print the URL and ask for paste-back. "
        "Useful when running on a headless host.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for the browser redirect (default: 300).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
