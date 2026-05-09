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
# Interactive policies (B2C_1A_*) use no `tfp/` prefix.
OAUTH_TOKEN_URL_TEMPLATE = (
    "https://{tenant_short}.b2clogin.com/{tenant}/{policy}/oauth2/v2.0/token"
)
DEFAULT_AUTH_TENANT = "konnectkohler.onmicrosoft.com"
DEFAULT_AUTH_POLICY = "B2C_1_ROPC_Auth"
DEFAULT_OAUTH_AUTH_POLICY = "B2C_1A_signin"


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
    """Run the ROPC password grant against Azure AD B2C and return the result."""
    tenant_short = auth_tenant.split(".")[0]
    url = TOKEN_URL_TEMPLATE.format(
        tenant_short=tenant_short, tenant=auth_tenant, policy=auth_policy
    )
    scope = f"openid offline_access https://{auth_tenant}/{api_resource}/apiaccess"
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


async def fetch_oauth_token(
    session: aiohttp.ClientSession,
    *,
    refresh_token: str,
    client_id: str,
    api_resource: str,
    auth_tenant: str = DEFAULT_AUTH_TENANT,
    auth_policy: str = DEFAULT_OAUTH_AUTH_POLICY,
) -> TokenResult:
    """Use a refresh_token (from B2C_1A_signin) to mint a fresh access token."""
    tenant_short = auth_tenant.split(".")[0]
    url = OAUTH_TOKEN_URL_TEMPLATE.format(
        tenant_short=tenant_short, tenant=auth_tenant, policy=auth_policy
    )
    scope = f"openid offline_access https://{auth_tenant}/{api_resource}/apiaccess"
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


def _build_endpoint_plan(
    *,
    effective_tenant: str | None,
    device_id: str | None,
) -> list[tuple[str, str, str, dict[str, Any] | None]]:
    """Build the (name, method, endpoint, body) tuples used by every probe run.

    Reads return 200; empty-body writes return 400 (caller has access) or 403
    (caller does not). Same plan whether token came from ROPC or OAuth.
    """
    endpoints: list[tuple[str, str, str, dict[str, Any] | None]] = []
    if effective_tenant:
        endpoints.append(
            (
                "read.customer_devices",
                "GET",
                ENDPOINTS["customer_devices"].format(customer_id=effective_tenant),
                None,
            )
        )
    if device_id:
        endpoints.append(
            (
                "read.device_state",
                "GET",
                ENDPOINTS["device_state"].format(device_id=device_id),
                None,
            )
        )
        endpoints.append(
            ("read.presets", "GET", ENDPOINTS["presets"].format(device_id=device_id), None)
        )
    empty_body: dict[str, Any] = {}
    endpoints.append(("write.mobile_settings", "POST", ENDPOINTS["mobile_settings"], empty_body))
    endpoints.append(("write.warmup", "POST", ENDPOINTS["warmup"], empty_body))
    endpoints.append(("write.preset_control", "POST", ENDPOINTS["preset_control"], empty_body))
    endpoints.append(("write.valve_control", "POST", ENDPOINTS["valve_control"], empty_body))
    return endpoints


async def _probe_with_token(
    session: aiohttp.ClientSession,
    *,
    token_result: TokenResult,
    apim_subscription_key: str,
    tenant_id: str | None,
    device_id: str | None,
) -> ProbeSet:
    """Decode claims, build endpoint plan, run all probes."""
    claims = _decode_jwt_payload(token_result.access_token or "")
    effective_tenant = tenant_id or claims.get("oid") or claims.get("sub")
    headers = auth_headers(token_result.access_token, apim_subscription_key)
    endpoints = _build_endpoint_plan(effective_tenant=effective_tenant, device_id=device_id)
    results: list[ProbeResult] = []
    for name, method, endpoint, body in endpoints:
        result = await probe_endpoint(
            session, name=name, method=method, endpoint=endpoint, headers=headers, body=body
        )
        results.append(result)
    return ProbeSet(token=token_result, token_claims=claims, results=results)


async def run_full_probe(
    *,
    username: str,
    password: str,
    client_id: str,
    apim_subscription_key: str,
    api_resource: str,
    tenant_id: str | None,
    device_id: str | None,
) -> ProbeSet:
    """Authenticate via ROPC and probe every endpoint we care about."""
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
        return await _probe_with_token(
            session,
            token_result=token_result,
            apim_subscription_key=apim_subscription_key,
            tenant_id=tenant_id,
            device_id=device_id,
        )


async def run_full_probe_with_oauth(
    *,
    refresh_token: str,
    client_id: str,
    apim_subscription_key: str,
    api_resource: str,
    tenant_id: str | None,
    device_id: str | None,
) -> ProbeSet:
    """Mint an access token via B2C_1A_signin refresh_token grant and probe.

    Use this once an interactive sign-in (e.g. ``dev/scripts/oauth_login.py``)
    has produced a refresh token. The capability matrix this returns is the
    real Phase 0 verification: command-write probes flip from BACKEND_FORBIDDEN
    to OK / BAD_REQUEST when the auth-rewrite hypothesis holds.
    """
    async with aiohttp.ClientSession() as session:
        token_result = await fetch_oauth_token(
            session,
            refresh_token=refresh_token,
            client_id=client_id,
            api_resource=api_resource,
        )
        if not token_result.is_ok:
            return ProbeSet(token=token_result, token_claims={}, results=[])
        return await _probe_with_token(
            session,
            token_result=token_result,
            apim_subscription_key=apim_subscription_key,
            tenant_id=tenant_id,
            device_id=device_id,
        )


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
