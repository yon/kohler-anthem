"""Tests for KohlerConfig."""

from __future__ import annotations

import pytest

from kohler_anthem import KohlerConfig


class TestKohlerConfig:
    """Test KohlerConfig dataclass."""

    def test_required_fields(self) -> None:
        """Test all required fields are set."""
        config = KohlerConfig(
            username="user@example.com",
            password="secret",
            client_id="client-123",
            apim_subscription_key="apim-key",
            api_resource="api-resource",
        )
        assert config.username == "user@example.com"
        assert config.password == "secret"
        assert config.client_id == "client-123"
        assert config.apim_subscription_key == "apim-key"
        assert config.api_resource == "api-resource"

    def test_default_values(self) -> None:
        """Test default values for optional fields."""
        config = KohlerConfig(
            username="user@example.com",
            password="secret",
            client_id="client-123",
            apim_subscription_key="apim-key",
            api_resource="api-resource",
        )
        assert config.auth_tenant == "konnectkohler.onmicrosoft.com"
        assert config.auth_policy == "B2C_1_ROPC_Auth"

    def test_custom_tenant_and_policy(self) -> None:
        """Test custom tenant and policy."""
        config = KohlerConfig(
            username="user@example.com",
            password="secret",
            client_id="client-123",
            apim_subscription_key="apim-key",
            api_resource="api-resource",
            auth_tenant="custom.onmicrosoft.com",
            auth_policy="B2C_1_Custom",
        )
        assert config.auth_tenant == "custom.onmicrosoft.com"
        assert config.auth_policy == "B2C_1_Custom"

    def test_token_url_property(self) -> None:
        """Test token_url is built correctly."""
        config = KohlerConfig(
            username="user@example.com",
            password="secret",
            client_id="client-123",
            apim_subscription_key="apim-key",
            api_resource="api-resource",
        )
        expected = (
            "https://konnectkohler.b2clogin.com/"
            "tfp/konnectkohler.onmicrosoft.com/B2C_1_ROPC_Auth/oauth2/v2.0/token"
        )
        assert config.token_url == expected

    def test_token_url_custom_tenant(self) -> None:
        """Test token_url with custom tenant."""
        config = KohlerConfig(
            username="user@example.com",
            password="secret",
            client_id="client-123",
            apim_subscription_key="apim-key",
            api_resource="api-resource",
            auth_tenant="mytenant.onmicrosoft.com",
            auth_policy="B2C_1_MyPolicy",
        )
        expected = (
            "https://mytenant.b2clogin.com/"
            "tfp/mytenant.onmicrosoft.com/B2C_1_MyPolicy/oauth2/v2.0/token"
        )
        assert config.token_url == expected

    def test_auth_scope_property(self) -> None:
        """Test auth_scope is built correctly."""
        config = KohlerConfig(
            username="user@example.com",
            password="secret",
            client_id="client-123",
            apim_subscription_key="apim-key",
            api_resource="my-api-resource",
        )
        expected = (
            "openid offline_access "
            "https://konnectkohler.onmicrosoft.com/my-api-resource/apiaccess"
        )
        assert config.auth_scope == expected
