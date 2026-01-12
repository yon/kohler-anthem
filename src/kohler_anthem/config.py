"""Configuration for Kohler Anthem API client."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KohlerConfig:
    """Configuration for Kohler Anthem API.

    All secrets and credentials required to authenticate and
    communicate with the Kohler Anthem API.

    Attributes:
        username: Kohler account email
        password: Kohler account password
        client_id: Azure AD B2C application client ID
        apim_subscription_key: Azure API Management subscription key
        api_resource: Azure AD B2C API resource identifier for scope
        auth_tenant: Azure AD B2C tenant (default: konnectkohler.onmicrosoft.com)
        auth_policy: Azure AD B2C policy (default: B2C_1_ROPC_Auth)
    """

    # User credentials
    username: str
    password: str

    # Azure AD B2C
    client_id: str

    # Azure API Management
    apim_subscription_key: str

    # API resource for OAuth scope
    api_resource: str

    # Azure AD B2C (defaults match Kohler's configuration)
    auth_tenant: str = "konnectkohler.onmicrosoft.com"
    auth_policy: str = "B2C_1_ROPC_Auth"

    @property
    def token_url(self) -> str:
        """Build the Azure AD B2C token endpoint URL."""
        return (
            f"https://{self.auth_tenant.split('.')[0]}.b2clogin.com/"
            f"tfp/{self.auth_tenant}/{self.auth_policy}/oauth2/v2.0/token"
        )

    @property
    def auth_scope(self) -> str:
        """Build the OAuth scope string."""
        return f"openid offline_access https://{self.auth_tenant}/{self.api_resource}/apiaccess"
