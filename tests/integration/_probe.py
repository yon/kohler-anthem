"""Live API probe helpers shared by integration tests and the CLI diagnostic.

Each probe returns a ProbeResult that classifies the outcome:
    OK              — endpoint accepted the request (2xx)
    APIM_AUTH_FAIL  — APIM gateway rejected the subscription key (401, APIM-format error)
    BACKEND_AUTH_FAIL — backend rejected the JWT (401, backend-format error)
    BACKEND_FORBIDDEN — APIM passed, JWT passed, backend RBAC rejected (403)
    NOT_FOUND       — endpoint moved or removed (404)
    BAD_REQUEST     — auth passed, body validation failed (400) — usually means the user
                      DOES have access; we just sent a deliberately empty body
    OTHER           — unexpected status code

The classification distinguishes APIM-level from backend-level failures, which is
the key insight for diagnosing what Kohler has changed.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import aiohttp

from kohler_anthem.const import API_BASE, ENDPOINTS

DEFAULT_USER_AGENT = "kohler-anthem-health-check/1.0"
TOKEN_URL_TEMPLATE = "https://{tenant_short}.b2clogin.com/tfp/{tenant}/{policy}/oauth2/v2.0/token"
DEFAULT_AUTH_TENANT = "konnectkohler.onmicrosoft.com"
DEFAULT_AUTH_POLICY = "B2C_1_ROPC_Auth"


class Status(Enum):
    OK = "OK"
    APIM_AUTH_FAIL = "APIM_AUTH_FAIL"
    BACKEND_AUTH_FAIL = "BACKEND_AUTH_FAIL"
    BACKEND_FORBIDDEN = "BACKEND_FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    BAD_REQUEST = "BAD_REQUEST"
    OTHER = "OTHER"
    NETWORK_ERROR = "NETWORK_ERROR"


@dataclass
class ProbeResult:
    name: str
    method: str
    endpoint: str
    status: Status
    http_code: int | None = None
    detail: str = ""
    raw_body: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status is Status.OK


@dataclass
class TokenResult:
    access_token: str | None
    expires_in: int | None
    refresh_token: str | None
    error: str | None
    error_description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ok(self) -> bool:
        return bool(self.access_token)


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return {}


def _classify(http_code: int, body_text: str) -> tuple[Status, str]:
    """Classify an HTTP response into a Status + human-readable detail."""
    body_lower = body_text.lower()
    if 200 <= http_code < 300:
        return Status.OK, ""
    if http_code == 400:
        return Status.BAD_REQUEST, _short(body_text)
    if http_code == 401:
        if "subscription key" in body_lower:
            return Status.APIM_AUTH_FAIL, "APIM rejected subscription key"
        return Status.BACKEND_AUTH_FAIL, _short(body_text)
    if http_code == 403:
        return Status.BACKEND_FORBIDDEN, "Backend RBAC denied (token type or roles)"
    if http_code == 404:
        return Status.NOT_FOUND, _short(body_text)
    return Status.OTHER, _short(body_text)


def _short(text: str, limit: int = 200) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


async def fetch_token(
    session: aiohttp.ClientSession,
    *,
    username: str,
    password: str,
    client_id: str,
    api_resource: str,
    auth_tenant: str = DEFAULT_AUTH_TENANT,
    auth_policy: str = DEFAULT_AUTH_POLICY,
) -> TokenResult:
    """Run the ROPC password grant against Azure AD B2C and return the result.

    Tokens returned by this flow have ``tfp=B2C_1_ROPC_Auth``. They authorize
    reads but the backend rejects them on /commands/* writes — see
    `fetch_b2c_signin_token` for the policy that unlocks writes.
    """
    tenant_short = auth_tenant.split(".")[0]
    url = TOKEN_URL_TEMPLATE.format(
        tenant_short=tenant_short, tenant=auth_tenant, policy=auth_policy
    )
    if api_resource.startswith(("https://", "http://")):
        scope_base = api_resource.rstrip("/")
    else:
        scope_base = f"https://{auth_tenant}/{api_resource.strip('/')}"
    scope = f"openid offline_access {scope_base}/apiaccess"
    data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
        "scope": scope,
    }
    try:
        async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            try:
                payload: dict[str, Any] = await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, json.JSONDecodeError):
                payload = {"raw": await resp.text()}
    except aiohttp.ClientError as e:
        return TokenResult(None, None, None, error=f"network: {e}")

    return TokenResult(
        access_token=payload.get("access_token"),
        expires_in=payload.get("expires_in"),
        refresh_token=payload.get("refresh_token"),
        error=payload.get("error"),
        error_description=payload.get("error_description"),
        raw=payload,
    )


async def fetch_b2c_signin_token(
    session: aiohttp.ClientSession,
    *,
    refresh_token: str,
    client_id: str,
    api_resource: str,
    auth_tenant: str = DEFAULT_AUTH_TENANT,
) -> TokenResult:
    """Silent refresh against the B2C_1A_signin policy.

    The refresh_token is seeded by the manual OAuth flow in
    ``dev/scripts/b2c_signin.py``. Tokens returned here are what Kohler's
    backend accepts for /commands/* writes.
    """
    tenant_short = auth_tenant.split(".")[0]
    url = TOKEN_URL_TEMPLATE.format(
        tenant_short=tenant_short, tenant=auth_tenant, policy="B2C_1A_signin"
    )
    if api_resource.startswith(("https://", "http://")):
        scope_base = api_resource.rstrip("/")
    else:
        scope_base = f"https://{auth_tenant}/{api_resource.strip('/')}"
    scope = f"openid offline_access {scope_base}/apiaccess"
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": scope,
    }
    try:
        async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            try:
                payload: dict[str, Any] = await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, json.JSONDecodeError):
                payload = {"raw": await resp.text()}
    except aiohttp.ClientError as e:
        return TokenResult(None, None, None, error=f"network: {e}")

    return TokenResult(
        access_token=payload.get("access_token"),
        expires_in=payload.get("expires_in"),
        refresh_token=payload.get("refresh_token"),
        error=payload.get("error"),
        error_description=payload.get("error_description"),
        raw=payload,
    )


async def probe_endpoint(
    session: aiohttp.ClientSession,
    *,
    name: str,
    method: str,
    endpoint: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> ProbeResult:
    """Probe one endpoint and classify the result."""
    url = f"{API_BASE}{endpoint}"
    try:
        async with session.request(
            method,
            url,
            headers=headers,
            json=body if body is not None else None,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            text = await resp.text()
            status, detail = _classify(resp.status, text)
            return ProbeResult(
                name=name,
                method=method,
                endpoint=endpoint,
                status=status,
                http_code=resp.status,
                detail=detail,
                raw_body=_short(text, 400),
            )
    except aiohttp.ClientError as e:
        return ProbeResult(
            name=name,
            method=method,
            endpoint=endpoint,
            status=Status.NETWORK_ERROR,
            detail=str(e),
        )


def auth_headers(access_token: str, apim_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Ocp-Apim-Subscription-Key": apim_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }


@dataclass
class ProbeSet:
    """A complete one-shot probe of token + every known endpoint."""

    token: TokenResult
    token_claims: dict[str, Any]
    results: list[ProbeResult]

    @property
    def by_name(self) -> dict[str, ProbeResult]:
        return {r.name: r for r in self.results}


async def run_full_probe(
    *,
    username: str,
    password: str,
    client_id: str,
    apim_subscription_key: str,
    api_resource: str,
    tenant_id: str | None,
    device_id: str | None,
    b2c_refresh_token: str | None = None,
) -> ProbeSet:
    """Authenticate and probe every endpoint we care about.

    Two token types are used:
      * ROPC user JWT (`tfp=B2C_1_ROPC_Auth`) for reads.
      * B2C_1A_signin user JWT for /commands/* writes — only available when
        ``b2c_refresh_token`` is supplied. Falls back to the ROPC token (and
        the writes will 403, as documented in
        `working/findings/commands_writes_403_2026-05-10.md`).
    """
    async with aiohttp.ClientSession() as session:
        token_result = await fetch_token(
            session,
            username=username,
            password=password,
            client_id=client_id,
            api_resource=api_resource,
        )
        if not token_result.is_ok:
            return ProbeSet(token=token_result, token_claims={}, results=[])

        claims = _decode_jwt_payload(token_result.access_token or "")
        # Tenant from JWT claims is authoritative; fall back to provided value.
        effective_tenant = tenant_id or claims.get("oid") or claims.get("sub")

        headers = auth_headers(token_result.access_token, apim_subscription_key)
        endpoints: list[tuple[str, str, str, dict[str, Any] | None, dict[str, str]]] = []

        # Acquire the B2C_1A_signin token used for /commands/* writes.
        write_headers = headers
        if b2c_refresh_token:
            b2c_result = await fetch_b2c_signin_token(
                session,
                refresh_token=b2c_refresh_token,
                client_id=client_id,
                api_resource=api_resource,
            )
            if b2c_result.is_ok:
                write_headers = auth_headers(
                    b2c_result.access_token, apim_subscription_key
                )

        # Reads (use the ROPC user token)
        if effective_tenant:
            endpoints.append(
                (
                    "read.customer_devices",
                    "GET",
                    ENDPOINTS["customer_devices"].format(customer_id=effective_tenant),
                    None,
                    headers,
                )
            )
        if device_id:
            endpoints.append(
                (
                    "read.device_state",
                    "GET",
                    ENDPOINTS["device_state"].format(device_id=device_id),
                    None,
                    headers,
                )
            )
            endpoints.append(
                (
                    "read.presets",
                    "GET",
                    ENDPOINTS["presets"].format(device_id=device_id),
                    None,
                    headers,
                )
            )

        # Writes — use empty body so we never trigger device side-effects.
        # An empty body returns 400 (validation) when the caller has access,
        # 403 when the caller is forbidden. Perfect classifier.
        # NOTE: Kohler's backend can return 403 for both "wrong token type"
        # and "missing required body fields" — when probing /commands/* with
        # the B2C_1A_signin token, 403 here means the body is rejected, not
        # the auth. Use the library-level write test for a definitive check.
        empty_body: dict[str, Any] = {}
        # mobile/settings uses the user-bound ROPC token.
        endpoints.append(
            ("write.mobile_settings", "POST", ENDPOINTS["mobile_settings"], empty_body, headers)
        )
        # /commands/* writes use the B2C_1A_signin token if available.
        endpoints.append(("write.warmup", "POST", ENDPOINTS["warmup"], empty_body, write_headers))
        endpoints.append(
            ("write.preset_control", "POST", ENDPOINTS["preset_control"], empty_body, write_headers)
        )
        endpoints.append(
            ("write.valve_control", "POST", ENDPOINTS["valve_control"], empty_body, write_headers)
        )

        results: list[ProbeResult] = []
        for name, method, endpoint, body, hdrs in endpoints:
            result = await probe_endpoint(
                session,
                name=name,
                method=method,
                endpoint=endpoint,
                headers=hdrs,
                body=body,
            )
            results.append(result)

        return ProbeSet(token=token_result, token_claims=claims, results=results)


def expected_token_claims(api_resource: str) -> dict[str, Any]:
    """Return claim values we expect a healthy token to carry."""
    return {
        "aud": api_resource,
        "scp": "apiaccess",
        "iss_prefix": "https://konnectkohler.b2clogin.com/",
    }


def token_claim_problems(claims: dict[str, Any], api_resource: str) -> list[str]:
    """Return a list of human-readable problems with the JWT claims, or []."""
    expected = expected_token_claims(api_resource)
    problems: list[str] = []
    if claims.get("aud") != expected["aud"]:
        problems.append(f"aud={claims.get('aud')} (expected {expected['aud']})")
    if claims.get("scp") != expected["scp"]:
        problems.append(f"scp={claims.get('scp')} (expected {expected['scp']})")
    iss = claims.get("iss", "")
    if not iss.startswith(expected["iss_prefix"]):
        problems.append(f"iss={iss} (expected prefix {expected['iss_prefix']})")
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        problems.append(f"token already expired (exp={exp})")
    return problems
