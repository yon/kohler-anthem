"""Azure AD B2C authentication for Kohler Anthem.

Uses Resource Owner Password Credential (ROPC) flow.
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
    """Handles authentication with Kohler's Azure AD B2C."""

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
