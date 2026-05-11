"""Authentication for Kohler Anthem.

Two flows live here, one per B2C policy that Kohler's backend accepts:

* **User JWT, ROPC policy (`KohlerAuth`)** — `authenticate()` does Resource
  Owner Password Credential against `B2C_1_ROPC_Auth`. Returns a
  user-bound token with `tfp=B2C_1_ROPC_Auth`, accepted on read endpoints
  (`/devices/api/v1/*`, `/platform/api/v1/mobile/*`).
* **User JWT, B2C_1A_signin policy (`B2CSignInAuth`)** — silent refresh of
  a previously-issued `B2C_1A_signin`-policy token using a stored
  `refresh_token`. Returns a user-bound token with `tfp=B2C_1A_signin`,
  the *only* token Kohler's backend accepts on `/commands/gcs/*` writes.
  The refresh_token is seeded by an interactive OAuth flow (driven by
  Home Assistant's config flow, or by `python -m kohler_anthem.b2c_signin`); the
  library itself never opens a browser.

(The harness also captures an APIM mTLS service-account JWT — see
`credential-extraction/`. That token is *not* what `/commands/*` accepts
and is no longer part of the library runtime; see
`working/findings/commands_writes_403_2026-05-10.md`.)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp

from .exceptions import AuthenticationError

if TYPE_CHECKING:
    from .config import KohlerConfig


@dataclass
class TokenInfo:
    """OAuth token information."""

    access_token: str
    refresh_token: str
    expires_at: float  # Unix timestamp
    id_token: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if token is expired or about to expire (5 min buffer)."""
        return time.time() >= (self.expires_at - 300)

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> TokenInfo:
        """Create TokenInfo from OAuth response.

        Args:
            data: Token response from Azure AD B2C

        Returns:
            TokenInfo instance
        """
        expires_in = data.get("expires_in", 3600)
        # API may return expires_in as string
        if isinstance(expires_in, str):
            expires_in = int(expires_in)
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=time.time() + expires_in,
            id_token=data.get("id_token"),
        )


class KohlerAuth:
    """Handles ROPC authentication with Kohler's Azure AD B2C."""

    def __init__(self, config: KohlerConfig) -> None:
        """Initialize authentication.

        Args:
            config: Kohler configuration with credentials
        """
        self._config = config
        self._token: TokenInfo | None = None

    @property
    def token(self) -> TokenInfo | None:
        """Get current token info."""
        return self._token

    @property
    def access_token(self) -> str | None:
        """Get current access token if valid."""
        if self._token and not self._token.is_expired:
            return self._token.access_token
        return None

    async def authenticate(self, session: aiohttp.ClientSession) -> TokenInfo:
        """Perform initial authentication using ROPC flow.

        Args:
            session: aiohttp session for making requests

        Returns:
            TokenInfo with access and refresh tokens

        Raises:
            AuthenticationError: If authentication fails
        """
        data = {
            "grant_type": "password",
            "client_id": self._config.client_id,
            "username": self._config.username,
            "password": self._config.password,
            "scope": self._config.auth_scope,
        }

        try:
            async with session.post(self._config.token_url, data=data) as response:
                response_data = await response.json()

                if response.status != 200:
                    error = response_data.get("error_description", "Unknown error")
                    raise AuthenticationError(
                        f"Authentication failed: {error}",
                        status_code=response.status,
                        raw_response=response_data,
                    )

                self._token = TokenInfo.from_response(response_data)
                return self._token

        except aiohttp.ClientError as e:
            raise AuthenticationError(f"Network error during authentication: {e}") from e

    async def refresh(self, session: aiohttp.ClientSession) -> TokenInfo:
        """Refresh the access token using refresh token.

        Args:
            session: aiohttp session for making requests

        Returns:
            New TokenInfo with fresh tokens

        Raises:
            AuthenticationError: If refresh fails or no refresh token available
        """
        if not self._token or not self._token.refresh_token:
            raise AuthenticationError("No refresh token available, must re-authenticate")

        data = {
            "grant_type": "refresh_token",
            "client_id": self._config.client_id,
            "refresh_token": self._token.refresh_token,
            "scope": self._config.auth_scope,
        }

        try:
            async with session.post(self._config.token_url, data=data) as response:
                response_data = await response.json()

                if response.status != 200:
                    # Refresh failed, try full re-auth
                    return await self.authenticate(session)

                self._token = TokenInfo.from_response(response_data)
                return self._token

        except aiohttp.ClientError as e:
            raise AuthenticationError(f"Network error during token refresh: {e}") from e

    async def ensure_valid_token(self, session: aiohttp.ClientSession) -> str:
        """Ensure we have a valid access token, refreshing if needed.

        Args:
            session: aiohttp session for making requests

        Returns:
            Valid access token

        Raises:
            AuthenticationError: If unable to get valid token
        """
        if self._token is None:
            await self.authenticate(session)
        elif self._token.is_expired:
            await self.refresh(session)

        if self._token is None:
            raise AuthenticationError("Failed to obtain access token")

        return self._token.access_token

    def clear_token(self) -> None:
        """Clear stored token (for logout or forced re-auth)."""
        self._token = None


class B2CSignInAuth:
    """Refresh-token-based JWT acquisition against B2C_1A_signin policy.

    The refresh_token is seeded by a one-time interactive sign-in (browser,
    OAuth authorization-code+PKCE) that lives outside the library — either
    Home Assistant's config flow, or the `python -m kohler_anthem.b2c_signin`
    helper for local development.

    Once seeded, this class POSTs to ``{authority}/oauth2/v2.0/token`` with
    ``grant_type=refresh_token`` whenever a fresh access_token is needed.
    Kohler rotates the refresh_token on every refresh; ``current_refresh_token``
    exposes the latest one so callers can persist it (HA writes it back to
    the config entry; the dev helper updates the env file).
    """

    def __init__(self, config: KohlerConfig) -> None:
        self._config = config
        self._token: TokenInfo | None = None
        self._refresh_token: str | None = config.b2c_refresh_token or None

    @property
    def is_configured(self) -> bool:
        """True if a refresh_token is present (seeded or fetched at runtime)."""
        return bool(self._refresh_token)

    @property
    def current_refresh_token(self) -> str | None:
        """Latest refresh token (rotated on each refresh). Persist this."""
        return self._refresh_token

    @property
    def access_token(self) -> str | None:
        """Current access token if valid; else None."""
        if self._token and not self._token.is_expired:
            return self._token.access_token
        return None

    async def refresh(self, session: aiohttp.ClientSession) -> TokenInfo:
        """Exchange the stored refresh_token for a fresh access_token.

        On success, ``self._refresh_token`` is updated to the new rotated
        value returned by B2C (or kept if the response omits it).

        Raises:
            AuthenticationError: refresh_token missing, expired/revoked,
                or any network error.
        """
        if not self._refresh_token:
            raise AuthenticationError(
                "B2C refresh_token not configured. Seed one via "
                "`python -m kohler_anthem.b2c_signin url|exchange` (or HA's "
                "config flow), then "
                "set KOHLER_B2C_REFRESH_TOKEN."
            )
        data = {
            "grant_type": "refresh_token",
            "client_id": self._config.client_id,
            "refresh_token": self._refresh_token,
            "scope": self._config.auth_scope,
        }
        try:
            async with session.post(
                self._config.b2c_signin_token_url, data=data
            ) as response:
                payload = await response.json()
                if response.status != 200:
                    error = payload.get("error_description") or payload.get(
                        "error"
                    ) or "unknown"
                    raise AuthenticationError(
                        f"B2C refresh failed: {error}",
                        status_code=response.status,
                        raw_response=payload,
                    )
        except aiohttp.ClientError as e:
            raise AuthenticationError(f"Network error during B2C refresh: {e}") from e

        # B2C rotates the refresh_token on each successful refresh; keep it.
        if payload.get("refresh_token"):
            self._refresh_token = payload["refresh_token"]
        self._token = TokenInfo.from_response(payload)
        return self._token

    async def ensure_valid_token(self, session: aiohttp.ClientSession) -> str:
        """Return a valid B2C_1A_signin access_token, refreshing if needed."""
        if self._token is None or self._token.is_expired:
            await self.refresh(session)
        if self._token is None:
            raise AuthenticationError("Failed to obtain B2C_1A_signin token")
        return self._token.access_token

    def clear_token(self) -> None:
        """Forget the in-memory access token. The refresh_token is kept."""
        self._token = None
