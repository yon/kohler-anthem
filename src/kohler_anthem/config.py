"""Configuration for Kohler Anthem API client."""

from __future__ import annotations

from dataclasses import dataclass

# Loopback HTTP redirect — works for any public client without app-registration
# changes. Custom-scheme redirects (msauth.com.kohler.hermoth://auth) are mobile-
# only; out-of-band (urn:ietf:wg:oauth:2.0:oob) is deprecated and not enabled
# on B2C_1A_signin. Port 0 = pick a free ephemeral port at runtime.
DEFAULT_OAUTH_REDIRECT_URI = "http://127.0.0.1:0/oauth/callback"


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


@dataclass
class KohlerOAuthConfig:
    """OAuth Authorization Code + PKCE configuration for B2C_1A_signin.

    Unlike KohlerConfig (ROPC), this carries no username/password. The library
    obtains tokens from a one-time interactive sign-in (handled by the caller)
    and then uses the resulting refresh token for all subsequent traffic.

    Attributes:
        client_id: Azure AD B2C application client ID (same as KohlerConfig).
        apim_subscription_key: Azure API Management subscription key.
        api_resource: Azure AD B2C API resource identifier (used in scope).
        redirect_uri: OAuth redirect URI. Defaults to a loopback HTTP server.
        auth_tenant: Azure AD B2C tenant.
        auth_policy: B2C policy name. B2C_1A_signin is the interactive policy
            the official Kohler apps use.
    """

    client_id: str
    apim_subscription_key: str
    api_resource: str
    redirect_uri: str = DEFAULT_OAUTH_REDIRECT_URI
    auth_tenant: str = "konnectkohler.onmicrosoft.com"
    auth_policy: str = "B2C_1A_signin"

    @property
    def _policy_base(self) -> str:
        # B2C_1A_signin uses no `tfp/` prefix (unlike B2C_1_ROPC_Auth).
        return (
            f"https://{self.auth_tenant.split('.')[0]}.b2clogin.com/"
            f"{self.auth_tenant}/{self.auth_policy}/oauth2/v2.0"
        )

    @property
    def authorize_url(self) -> str:
        """Browser-facing URL for the interactive sign-in step."""
        return f"{self._policy_base}/authorize"

    @property
    def token_url(self) -> str:
        """Token endpoint for code exchange and refresh."""
        return f"{self._policy_base}/token"

    @property
    def auth_scope(self) -> str:
        """OAuth scope string. `offline_access` is what mints the refresh token."""
        return f"openid offline_access https://{self.auth_tenant}/{self.api_resource}/apiaccess"
