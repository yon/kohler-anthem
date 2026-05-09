#!/usr/bin/env python3
"""Live diagnostic for Kohler Anthem credentials.

Probes every known endpoint and prints a capability matrix. Use this when
something starts breaking in production to pinpoint exactly which capability
is revoked.

Two auth modes:

    ROPC (legacy)   — uses username + password. Currently rejected on
                      /commands/gcs/* by Kohler's backend (May 2026).
    OAuth (new)     — uses a refresh token from B2C_1A_signin (run
                      dev/scripts/oauth_login.py first to mint one).

Usage:
    # ROPC mode via env vars
    export KOHLER_USERNAME=...
    export KOHLER_PASSWORD=...
    export KOHLER_CLIENT_ID=...
    export KOHLER_APIM_KEY=...
    export KOHLER_API_RESOURCE=...
    export KOHLER_TENANT_ID=...      # optional, falls back to JWT.oid
    export KOHLER_DEVICE_ID=...      # optional, enables device-scoped probes
    python dev/scripts/health_check.py

    # or via Makefile
    make health-check

    # or via credential-extraction/kohler-credentials.yaml
    python dev/scripts/health_check.py --yaml credential-extraction/kohler-credentials.yaml

    # OAuth mode (requires a refresh token from oauth_login.py)
    python dev/scripts/health_check.py \\
        --yaml credential-extraction/kohler-credentials.yaml \\
        --oauth-tokens ~/.kohler-tokens.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from integration._probe import (  # noqa: E402
    ProbeSet,
    Status,
    run_full_probe,
    run_full_probe_with_oauth,
    token_claim_problems,
)


# ANSI colors — only emitted when stdout is a tty.
def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


_COLOR = _supports_color()


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


GREEN = lambda s: _c("32", s)  # noqa: E731
RED = lambda s: _c("31", s)  # noqa: E731
YELLOW = lambda s: _c("33", s)  # noqa: E731
GRAY = lambda s: _c("90", s)  # noqa: E731
BOLD = lambda s: _c("1", s)  # noqa: E731


STATUS_COLOR = {
    Status.OK: GREEN,
    Status.BAD_REQUEST: GREEN,  # access OK; only the body was rejected
    Status.APIM_AUTH_FAIL: RED,
    Status.BACKEND_AUTH_FAIL: RED,
    Status.BACKEND_FORBIDDEN: RED,
    Status.NOT_FOUND: YELLOW,
    Status.NETWORK_ERROR: YELLOW,
    Status.OTHER: YELLOW,
}


def _load_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        print(f"warning: PyYAML not installed; cannot read {path}", file=sys.stderr)
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def load_creds(yaml_path: Path | None) -> dict[str, str | None]:
    yaml_data = _load_yaml(yaml_path) if yaml_path else {}
    pairs = {
        "username": ("KOHLER_USERNAME", "kohler_username"),
        "password": ("KOHLER_PASSWORD", "kohler_password"),
        "client_id": ("KOHLER_CLIENT_ID", "kohler_client_id"),
        "apim_subscription_key": ("KOHLER_APIM_KEY", "kohler_apim_key"),
        "api_resource": ("KOHLER_API_RESOURCE", "kohler_api_resource"),
        "tenant_id": ("KOHLER_TENANT_ID", "kohler_tenant_id"),
        "device_id": ("KOHLER_DEVICE_ID", "kohler_device_id"),
    }
    out: dict[str, str | None] = {}
    for field, (env_key, yaml_key) in pairs.items():
        env = os.environ.get(env_key)
        yml = yaml_data.get(yaml_key)
        value = env or yml
        if value and value.startswith("YOUR_VALUE"):
            value = None
        out[field] = value
    return out


def render(probe: ProbeSet, api_resource: str) -> int:
    """Render the diagnostic. Returns process exit code."""
    print()
    print(BOLD("Kohler Anthem credential health check"))
    print()

    # OAuth — works for both ROPC password grant and B2C_1A_signin refresh grant.
    if probe.token.is_ok:
        print(f"  {GREEN('✓')} access token issued (expires_in={probe.token.expires_in}s)")
    else:
        print(f"  {RED('✗')} access token NOT issued")
        print(f"    error:       {probe.token.error}")
        print(f"    description: {probe.token.error_description}")
        return 2

    # Claims
    problems = token_claim_problems(probe.token_claims, api_resource)
    if problems:
        print(f"  {RED('✗')} JWT claims drift:")
        for p in problems:
            print(f"      {p}")
    else:
        print(f"  {GREEN('✓')} JWT claims OK")
    if probe.token_claims:
        print(
            GRAY(
                "    "
                + ", ".join(
                    f"{k}={probe.token_claims.get(k)}"
                    for k in ("aud", "scp", "iss", "oid", "tfp")
                    if k in probe.token_claims
                )
            )
        )

    print()
    print(BOLD("  Endpoint capability matrix:"))
    if not probe.results:
        print(GRAY("    (no endpoint probes ran — token failure aborted the run)"))
        return 2

    width = max(len(r.endpoint) for r in probe.results)
    failed = 0
    for r in probe.results:
        is_access_ok = r.status in {Status.OK, Status.BAD_REQUEST}
        symbol = GREEN("✓") if is_access_ok else RED("✗")
        if not is_access_ok:
            failed += 1
        color = STATUS_COLOR.get(r.status, YELLOW)
        line = (
            f"    {symbol} {r.method:5} {r.endpoint:<{width}} "
            f"HTTP {r.http_code if r.http_code is not None else '---':>3} "
            f"{color(r.status.value)}"
        )
        print(line)
        if r.detail and not is_access_ok:
            print(GRAY(f"        {r.detail}"))

    print()
    print(BOLD("  Interpretation:"))

    has_apim_fail = any(r.status is Status.APIM_AUTH_FAIL for r in probe.results)
    has_backend_forbidden = any(r.status is Status.BACKEND_FORBIDDEN for r in probe.results)
    has_backend_auth_fail = any(r.status is Status.BACKEND_AUTH_FAIL for r in probe.results)
    has_not_found = any(r.status is Status.NOT_FOUND for r in probe.results)

    if has_apim_fail:
        print(
            f"    {RED('!')} APIM rejected the subscription key on at least one endpoint. "
            "The captured key may be revoked or scoped to a different APIM product. "
            "Consider re-running credential-extraction."
        )
    if has_backend_auth_fail:
        print(
            f"    {RED('!')} Backend rejected the JWT (not an APIM error). The token may "
            "be expired, malformed, or have wrong claims. Check the JWT claims line above."
        )
    if has_backend_forbidden:
        commands_forbidden = any(
            r.status is Status.BACKEND_FORBIDDEN and "/commands/gcs/" in r.endpoint
            for r in probe.results
        )
        non_command_forbidden = any(
            r.status is Status.BACKEND_FORBIDDEN and "/commands/gcs/" not in r.endpoint
            for r in probe.results
        )
        if commands_forbidden and not non_command_forbidden:
            print(
                f"    {RED('!')} Reads + non-command writes pass; "
                "/commands/gcs/* is forbidden. Strong signal that ROPC-issued tokens are "
                "being rejected by backend RBAC. The fix path is to switch the auth flow "
                "to OAuth Authorization Code + PKCE against the B2C_1A_signin policy. "
                "See working/plans/ for the implementation plan."
            )
        else:
            print(
                f"    {RED('!')} Backend forbade access to one or more endpoints. "
                "This is past APIM and JWT validation — likely a missing role/claim "
                "or a token-type restriction."
            )
    if has_not_found:
        print(
            f"    {YELLOW('!')} At least one endpoint returned 404. Kohler may have "
            "moved/renamed it. Update src/kohler_anthem/const.py ENDPOINTS."
        )
    if failed == 0:
        print(f"    {GREEN('All capabilities OK.')}")

    print()
    return 0 if failed == 0 else 1


def _read_token_file(path: Path) -> dict[str, str]:
    """Read a token JSON file written by dev/scripts/oauth_login.py."""
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict):
        sys.exit(f"error: {path} is not a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--yaml",
        type=Path,
        default=None,
        help="Path to credentials YAML (defaults to credential-extraction/kohler-credentials.yaml)",
    )
    parser.add_argument(
        "--oauth-tokens",
        type=Path,
        default=None,
        help="Use a refresh token from this JSON file (written by oauth_login.py) "
        "instead of ROPC. The B2C_1A_signin policy will be used.",
    )
    args = parser.parse_args()

    yaml_path = args.yaml or (REPO_ROOT / "credential-extraction" / "kohler-credentials.yaml")
    creds = load_creds(yaml_path)

    if args.oauth_tokens:
        # OAuth mode: refresh token + the same APIM key + client_id + api_resource.
        oauth_required = ("client_id", "apim_subscription_key", "api_resource")
        missing = [k for k in oauth_required if not creds.get(k)]
        if missing:
            print(
                f"{RED('error')}: missing required credential(s) for OAuth mode: "
                f"{', '.join(missing)}",
                file=sys.stderr,
            )
            return 2
        if not args.oauth_tokens.exists():
            print(f"{RED('error')}: {args.oauth_tokens} does not exist", file=sys.stderr)
            return 2
        token_data = _read_token_file(args.oauth_tokens)
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            print(
                f"{RED('error')}: {args.oauth_tokens} has no refresh_token",
                file=sys.stderr,
            )
            return 2
        probe = asyncio.run(
            run_full_probe_with_oauth(
                refresh_token=refresh_token,
                client_id=creds["client_id"],
                apim_subscription_key=creds["apim_subscription_key"],
                api_resource=creds["api_resource"],
                tenant_id=creds.get("tenant_id"),
                device_id=creds.get("device_id"),
            )
        )
        return render(probe, creds["api_resource"])

    required = ("username", "password", "client_id", "apim_subscription_key", "api_resource")
    missing = [k for k in required if not creds.get(k)]
    if missing:
        print(
            f"{RED('error')}: missing required credential(s): {', '.join(missing)}", file=sys.stderr
        )
        print(
            "  Provide via env vars (KOHLER_USERNAME, KOHLER_PASSWORD, ...) or YAML "
            f"({yaml_path}).",
            file=sys.stderr,
        )
        return 2

    probe = asyncio.run(
        run_full_probe(
            username=creds["username"],
            password=creds["password"],
            client_id=creds["client_id"],
            apim_subscription_key=creds["apim_subscription_key"],
            api_resource=creds["api_resource"],
            tenant_id=creds.get("tenant_id"),
            device_id=creds.get("device_id"),
        )
    )
    return render(probe, creds["api_resource"])


if __name__ == "__main__":
    sys.exit(main())
