"""Live-API health checks under the new OAuth (B2C_1A_signin) flow.

Mirrors test_credentials_health.py but uses an interactive-flow refresh token
instead of the legacy ROPC password grant.

These tests skip unless KOHLER_OAUTH_TOKENS points at a valid JSON file
produced by dev/scripts/oauth_login.py.

Once the auth-rewrite hypothesis is verified, the three /commands/gcs/* tests
flip from failing (under ROPC) to passing under OAuth — that flip is the
empirical proof that the rewrite was the right call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ._probe import (
    ProbeSet,
    Status,
    run_full_probe_with_oauth,
    token_claim_problems,
)

if TYPE_CHECKING:
    from .conftest import LiveCredentials


WRITE_OK = {Status.OK, Status.BAD_REQUEST}


@pytest.fixture(scope="module")
async def oauth_probe(
    credentials: LiveCredentials, oauth_refresh_token: str
) -> ProbeSet:
    """Mint an access token via the B2C_1A_signin refresh grant and probe."""
    return await run_full_probe_with_oauth(
        refresh_token=oauth_refresh_token,
        client_id=credentials.client_id,
        apim_subscription_key=credentials.apim_subscription_key,
        api_resource=credentials.api_resource,
        tenant_id=credentials.tenant_id,
        device_id=credentials.device_id,
    )


def test_oauth_token_issued(oauth_probe: ProbeSet) -> None:
    """Refresh-token grant succeeds.

    If this fails, either the refresh token has expired (run oauth_login.py
    again) or the B2C_1A_signin policy has changed and the rewrite needs to
    be revisited.
    """
    assert oauth_probe.token.is_ok, (
        f"OAuth refresh-token grant failed: error={oauth_probe.token.error}, "
        f"description={oauth_probe.token.error_description}"
    )


def test_oauth_token_claims_match_expectations(
    oauth_probe: ProbeSet, credentials: LiveCredentials
) -> None:
    problems = token_claim_problems(oauth_probe.token_claims, credentials.api_resource)
    assert not problems, "Token claims problem(s): " + "; ".join(problems)


def test_oauth_read_customer_devices(
    oauth_probe: ProbeSet, credentials: LiveCredentials
) -> None:
    if not credentials.tenant_id and not oauth_probe.token_claims.get("oid"):
        pytest.skip("No tenant_id available")
    assert oauth_probe.by_name["read.customer_devices"].is_ok


def test_oauth_write_warmup_allowed(oauth_probe: ProbeSet) -> None:
    """The first canary: under ROPC this is BACKEND_FORBIDDEN; under OAuth it
    must be allowed."""
    assert oauth_probe.by_name["write.warmup"].status in WRITE_OK


def test_oauth_write_preset_control_allowed(oauth_probe: ProbeSet) -> None:
    assert oauth_probe.by_name["write.preset_control"].status in WRITE_OK


def test_oauth_write_valve_control_allowed(oauth_probe: ProbeSet) -> None:
    """The headline canary: solowritesystem must be allowed under OAuth."""
    assert oauth_probe.by_name["write.valve_control"].status in WRITE_OK
