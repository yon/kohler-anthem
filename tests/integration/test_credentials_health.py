"""Live-API health checks: detect which capabilities are revoked or broken.

These tests don't validate the library's behavior — they validate that the
upstream Kohler API still grants this caller the access we expect. When
something breaks in production, run this suite to pinpoint exactly which
capability flipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ._probe import (
    ProbeSet,
    Status,
    run_full_probe,
    token_claim_problems,
)

if TYPE_CHECKING:
    from .conftest import LiveCredentials


@pytest.fixture(scope="module")
async def probe(credentials: LiveCredentials) -> ProbeSet:
    """Run one full probe and share the result across tests in this module."""
    return await run_full_probe(
        username=credentials.username,
        password=credentials.password,
        client_id=credentials.client_id,
        apim_subscription_key=credentials.apim_subscription_key,
        api_resource=credentials.api_resource,
        tenant_id=credentials.tenant_id,
        device_id=credentials.device_id,
        b2c_refresh_token=credentials.b2c_refresh_token,
    )


# ---------------------------------------------------------------------------
# OAuth / token-level checks
# ---------------------------------------------------------------------------


def test_ropc_token_issued(probe: ProbeSet) -> None:
    """The ROPC password grant must succeed and return an access token.

    If this fails, either credentials are wrong or Kohler has disabled the
    B2C_1_ROPC_Auth policy entirely (in which case the auth-flow rewrite is
    no longer optional — it's required).
    """
    assert probe.token.is_ok, (
        f"ROPC token request failed: error={probe.token.error}, "
        f"description={probe.token.error_description}"
    )


def test_token_claims_match_expectations(probe: ProbeSet, credentials: LiveCredentials) -> None:
    """The issued JWT must carry the claims the backend expects.

    If aud/scp/iss drift, the backend will refuse it. This test surfaces such
    drift before it manifests as a 403.
    """
    problems = token_claim_problems(probe.token_claims, credentials.api_resource)
    assert not problems, "Token claims problem(s): " + "; ".join(problems)


# ---------------------------------------------------------------------------
# Read capabilities
# ---------------------------------------------------------------------------


def test_read_customer_devices(probe: ProbeSet, credentials: LiveCredentials) -> None:
    """GET customer device list must return 200.

    This is the integration's discovery call. If this 403s, the entire
    integration is dead, not just controls.
    """
    if not credentials.tenant_id and not probe.token_claims.get("oid"):
        pytest.skip("No tenant_id available (provide KOHLER_TENANT_ID or rely on JWT oid)")
    result = probe.by_name["read.customer_devices"]
    assert result.is_ok, _fmt(result)


def test_read_device_state(probe: ProbeSet, credentials: LiveCredentials) -> None:
    """GET device state must return 200.

    Used by the coordinator on every poll.
    """
    if not credentials.device_id:
        pytest.skip("Provide KOHLER_DEVICE_ID to probe device state")
    result = probe.by_name["read.device_state"]
    assert result.is_ok, _fmt(result)


def test_read_presets(probe: ProbeSet, credentials: LiveCredentials) -> None:
    """GET preset list must return 200."""
    if not credentials.device_id:
        pytest.skip("Provide KOHLER_DEVICE_ID to probe presets")
    result = probe.by_name["read.presets"]
    assert result.is_ok, _fmt(result)


# ---------------------------------------------------------------------------
# Write capabilities
#
# We POST an empty `{}` body. If the caller has access, the backend returns
# 400 (or 201 in a few permissive cases) because validation runs after auth.
# If the caller is forbidden, the backend returns 403 *before* validation.
# So OK + BAD_REQUEST both mean "you have access"; BACKEND_FORBIDDEN means
# "you do not".
# ---------------------------------------------------------------------------


WRITE_OK = {Status.OK, Status.BAD_REQUEST}


def test_write_mobile_settings_allowed(probe: ProbeSet) -> None:
    """POST /platform/api/v1/mobile/settings must be allowed.

    The integration calls this on startup to obtain IoT Hub credentials. If
    this is forbidden, real-time MQTT updates will not work.
    """
    result = probe.by_name["write.mobile_settings"]
    assert result.status in WRITE_OK, _fmt(result)


def _commands_probe_indeterminate(credentials: LiveCredentials) -> bool:
    """When b2c_refresh_token is configured, the empty-body /commands/* probes
    are ambiguous: Kohler returns 403 for both wrong-auth AND missing-body-
    fields. The real auth verification lives in test_library_writes.py.
    """
    return credentials.b2c_refresh_token is not None


def test_write_warmup_allowed(probe: ProbeSet, credentials: LiveCredentials) -> None:
    """POST /platform/api/v1/commands/gcs/warmup must be allowed.

    ROPC-only mode: a 403 here is the canary for the original regression.
    B2C mode: empty-body returns 403 even with valid auth (Kohler quirk) —
    delegated to test_library_writes.py for the definitive write check.
    """
    if _commands_probe_indeterminate(credentials):
        pytest.skip("B2C refresh_token configured — see test_library_writes.py")
    result = probe.by_name["write.warmup"]
    assert result.status in WRITE_OK, _fmt(result)


def test_write_preset_control_allowed(probe: ProbeSet, credentials: LiveCredentials) -> None:
    """POST /platform/api/v1/commands/gcs/controlpresetorexperience must be allowed.

    See `test_write_warmup_allowed` for the ROPC vs B2C handling.
    """
    if _commands_probe_indeterminate(credentials):
        pytest.skip("B2C refresh_token configured — see test_library_writes.py")
    result = probe.by_name["write.preset_control"]
    assert result.status in WRITE_OK, _fmt(result)


def test_write_valve_control_allowed(probe: ProbeSet, credentials: LiveCredentials) -> None:
    """POST /platform/api/v1/commands/gcs/solowritesystem must be allowed.

    Backs every light / number / switch entity that controls valve state.
    See `test_write_warmup_allowed` for the ROPC vs B2C handling.
    """
    if _commands_probe_indeterminate(credentials):
        pytest.skip("B2C refresh_token configured — see test_library_writes.py")
    result = probe.by_name["write.valve_control"]
    assert result.status in WRITE_OK, _fmt(result)


# ---------------------------------------------------------------------------
# Diagnostic summary (always passes — provides a printout when -s is used)
# ---------------------------------------------------------------------------


def test_capability_summary(probe: ProbeSet, capsys: pytest.CaptureFixture[str]) -> None:
    """Print a capability matrix so failures in this file are easy to read."""
    lines = [""]
    lines.append("Capability matrix:")
    lines.append(f"  token issued: {probe.token.is_ok}  expires_in={probe.token.expires_in}")
    if probe.token_claims:
        keys = ("aud", "scp", "iss", "oid", "tfp")
        rendered = ", ".join(f"{k}={probe.token_claims.get(k)}" for k in keys)
        lines.append(f"  claims: {rendered}")
    for r in probe.results:
        lines.append(
            f"  {r.method:5} {r.endpoint:75} -> HTTP {r.http_code} {r.status.value} {r.detail}"
        )
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(result) -> str:
    return (
        f"{result.method} {result.endpoint} -> HTTP {result.http_code} "
        f"[{result.status.value}] {result.detail or result.raw_body}"
    )
