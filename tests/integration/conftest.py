"""Fixtures for integration tests against the live Kohler API.

Credentials are loaded in priority order:
  1. Environment variables (KOHLER_USERNAME, KOHLER_PASSWORD, ...)
  2. credential-extraction/kohler-credentials.yaml

If neither is present, all integration tests skip.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_YAML = REPO_ROOT / "credential-extraction" / "kohler-credentials.yaml"

ENV_KEYS = {
    "username": "KOHLER_USERNAME",
    "password": "KOHLER_PASSWORD",
    "client_id": "KOHLER_CLIENT_ID",
    "apim_subscription_key": "KOHLER_APIM_KEY",
    "api_resource": "KOHLER_API_RESOURCE",
    "tenant_id": "KOHLER_TENANT_ID",
    "device_id": "KOHLER_DEVICE_ID",
    "b2c_refresh_token": "KOHLER_B2C_REFRESH_TOKEN",
}

YAML_KEYS = {
    "username": "kohler_username",
    "password": "kohler_password",
    "client_id": "kohler_client_id",
    "apim_subscription_key": "kohler_apim_key",
    "api_resource": "kohler_api_resource",
    "tenant_id": "kohler_tenant_id",
    "device_id": "kohler_device_id",
    "b2c_refresh_token": "kohler_b2c_refresh_token",
}


@dataclass(frozen=True)
class LiveCredentials:
    """Live Kohler credentials loaded for integration tests."""

    username: str
    password: str
    client_id: str
    apim_subscription_key: str
    api_resource: str
    tenant_id: str | None = None
    device_id: str | None = None
    # Seeded by dev/scripts/b2c_signin.py — required for /commands/* writes.
    b2c_refresh_token: str | None = None


def _load_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _load_credentials() -> LiveCredentials | None:
    yaml_data = _load_yaml(CREDENTIALS_YAML)
    resolved: dict[str, str] = {}
    for field, env_key in ENV_KEYS.items():
        env_val = os.environ.get(env_key)
        yaml_val = yaml_data.get(YAML_KEYS[field])
        value = env_val or yaml_val
        if value and not value.startswith("YOUR_VALUE"):
            resolved[field] = value

    required = ("username", "password", "client_id", "apim_subscription_key", "api_resource")
    if not all(field in resolved for field in required):
        return None

    return LiveCredentials(
        username=resolved["username"],
        password=resolved["password"],
        client_id=resolved["client_id"],
        apim_subscription_key=resolved["apim_subscription_key"],
        api_resource=resolved["api_resource"],
        tenant_id=resolved.get("tenant_id"),
        device_id=resolved.get("device_id"),
        b2c_refresh_token=resolved.get("b2c_refresh_token"),
    )


@pytest.fixture(scope="session")
def credentials() -> LiveCredentials:
    """Load live credentials, or skip the entire integration suite."""
    creds = _load_credentials()
    if creds is None:
        pytest.skip(
            "Live credentials not available. Set KOHLER_USERNAME/PASSWORD/CLIENT_ID/"
            "APIM_KEY/API_RESOURCE env vars or populate "
            "credential-extraction/kohler-credentials.yaml"
        )
    return creds
