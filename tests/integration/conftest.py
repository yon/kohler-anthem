"""Fixtures for integration tests against the live Kohler API.

Credentials are loaded in priority order:
  1. Environment variables (KOHLER_USERNAME, KOHLER_PASSWORD, ...)
  2. credential-extraction/kohler-credentials.yaml

If neither is present, all integration tests skip.

For the OAuth (B2C_1A_signin) probe, set ``KOHLER_OAUTH_TOKENS`` to the path
of a JSON file written by ``dev/scripts/oauth_login.py``. Tests that depend
on it skip when the file is absent.
"""

from __future__ import annotations

import json
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
}

YAML_KEYS = {
    "username": "kohler_username",
    "password": "kohler_password",
    "client_id": "kohler_client_id",
    "apim_subscription_key": "kohler_apim_key",
    "api_resource": "kohler_api_resource",
    "tenant_id": "kohler_tenant_id",
    "device_id": "kohler_device_id",
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


@pytest.fixture(scope="session")
def oauth_refresh_token() -> str:
    """Load a refresh token from KOHLER_OAUTH_TOKENS, or skip the OAuth probe.

    Pre-requisite: run ``dev/scripts/oauth_login.py`` once and set
    ``KOHLER_OAUTH_TOKENS=/path/to/tokens.json``.
    """
    path_str = os.environ.get("KOHLER_OAUTH_TOKENS")
    if not path_str:
        pytest.skip(
            "KOHLER_OAUTH_TOKENS not set. Run dev/scripts/oauth_login.py to mint a "
            "refresh token, then export KOHLER_OAUTH_TOKENS=<path-to-tokens.json>."
        )
    path = Path(path_str)
    if not path.exists():
        pytest.skip(f"KOHLER_OAUTH_TOKENS={path} does not exist")
    with path.open() as f:
        data = json.load(f)
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        pytest.skip(f"{path} has no refresh_token field")
    return refresh_token
