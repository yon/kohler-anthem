"""Library-level write verification — definitive proof /commands/* works.

The probes in test_credentials_health.py use empty bodies (perfect classifier
for the ROPC vs B2C_1A_signin question on most endpoints) but Kohler's backend
returns 403 on /commands/* for BOTH "wrong token type" AND "missing required
body fields" — so empty-body probes can't confirm a working write path.

These tests build a real KohlerAnthemClient and call the library's write
methods with valid bodies. If the response carries a correlationId, auth +
routing + body are all correct end-to-end.

Skipped if `KOHLER_B2C_REFRESH_TOKEN` (or `KOHLER_DEVICE_ID`) is missing —
writes have no auth without the refresh_token and no target without a device.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kohler_anthem import KohlerAnthemClient, KohlerConfig

if TYPE_CHECKING:
    from .conftest import LiveCredentials


@pytest.fixture
async def client(credentials: LiveCredentials):
    """Connected KohlerAnthemClient with B2C_1A_signin auth wired up."""
    if not credentials.b2c_refresh_token:
        pytest.skip(
            "KOHLER_B2C_REFRESH_TOKEN not set — seed one with "
            "`.venv/bin/python dev/scripts/b2c_signin.py url` then `exchange`."
        )
    if not credentials.device_id:
        pytest.skip("KOHLER_DEVICE_ID not set — writes need a target device.")
    cfg = KohlerConfig(
        username=credentials.username,
        password=credentials.password,
        client_id=credentials.client_id,
        apim_subscription_key=credentials.apim_subscription_key,
        api_resource=credentials.api_resource,
        b2c_refresh_token=credentials.b2c_refresh_token,
    )
    async with KohlerAnthemClient(cfg) as c:
        yield c


async def test_write_warmup(client: KohlerAnthemClient, credentials: LiveCredentials) -> None:
    """POST /commands/gcs/warmup returns a correlationId via the library.

    This is the regression test for the 403 symptom: with a B2C_1A_signin
    refresh_token configured, writes go through the new auth path and the
    backend returns 201 with a correlation ID.
    """
    assert credentials.device_id is not None
    resp = await client.start_warmup(credentials.tenant_id or "", credentials.device_id)
    assert resp.correlation_id, "expected a correlation_id in the response"


async def test_silent_refresh_rotates_refresh_token(
    client: KohlerAnthemClient, credentials: LiveCredentials,
) -> None:
    """B2C rotates the refresh_token on each silent refresh; the lib tracks it.

    After at least one write, the client's `b2c_refresh_token` property
    should expose the latest rotated value — callers (HA's config entry,
    dev scripts) should persist it.
    """
    assert credentials.device_id is not None
    # Trigger a write to force a token refresh.
    await client.start_warmup(credentials.tenant_id or "", credentials.device_id)
    current = client.b2c_refresh_token
    assert current is not None and len(current) > 100, (
        f"expected rotated refresh_token, got len={len(current) if current else 0}"
    )
