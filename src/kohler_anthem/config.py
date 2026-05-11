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

    # API resource for OAuth scope. Accepts either the application GUID
    # (e.g. "f5d87f3d-bdeb-4933-ab70-ef56cc343744") or a path fragment
    # (e.g. "api-mob/access"). The current Kohler tenant only honors the
    # GUID form — the path form fails with AADB2C90205.
    api_resource: str = "f5d87f3d-bdeb-4933-ab70-ef56cc343744"

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
        """Build the OAuth scope string.

        Kohler's B2C tenant only honors scopes built against the API
        resource's **application GUID** (currently
        ``f5d87f3d-bdeb-4933-ab70-ef56cc343744``). The older
        ``api-mob/access`` path form fails with AADB2C90205
        ("application does not have sufficient permissions").

        Accepts ``api_resource`` as either a bare GUID/path or a full
        ``https://...`` URL — both are normalized into the right scope.
        """
        if self.api_resource.startswith(("https://", "http://")):
            base = self.api_resource.rstrip("/")
        else:
            base = f"https://{self.auth_tenant}/{self.api_resource.strip('/')}"
        return f"openid offline_access {base}/apiaccess"
