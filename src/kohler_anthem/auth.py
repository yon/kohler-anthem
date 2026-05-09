"""Azure AD B2C authentication for Kohler Anthem.

Two flows are supported:

- `KohlerAuth` — Resource Owner Password Credentials (ROPC, legacy). Kept for
  reads-only fallback on older deployments; Kohler's backend rejects ROPC-
  issued tokens on `/commands/gcs/*` as of May 2026.
- `KohlerOAuthAuth` — OAuth Authorization Code + PKCE against `B2C_1A_signin`.
  This is what the official mobile apps use; required for full control access.
  The library never persists secrets itself — the caller provides a `TokenStore`
  that handles persistence (e.g., Home Assistant config entry, JSON file).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.parse import urlencode

import aiohttp

from .exceptions import AuthenticationError, ReauthRequired

if TYPE_CHECKING:
    from .config import KohlerConfig, KohlerOAuthConfig


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


# ---------------------------------------------------------------------------
# OAuth Authorization Code + PKCE (B2C_1A_signin)
# ---------------------------------------------------------------------------


@runtime_checkable
class TokenStore(Protocol):
    """Caller-provided persistence for OAuth tokens.

    Home Assistant stores tokens in the config entry; the CLI helper stores
    them in a JSON file. The library never writes to disk on its own.
    """

    async def load(self) -> TokenInfo | None: ...

    async def save(self, token: TokenInfo) -> None: ...


# Errors that mean the refresh token itself is dead. Standard B2C error codes.
_REAUTH_ERROR_CODES = frozenset(
    {
        "invalid_grant",
        "interaction_required",
        "login_required",
        "consent_required",
    }
)


def _is_reauth_error(payload: dict[str, Any]) -> bool:
    error = payload.get("error", "")
    if isinstance(error, str) and error in _REAUTH_ERROR_CODES:
        return True
    description = payload.get("error_description", "")
    if isinstance(description, str):
        # B2C error codes for refresh-token-dead conditions.
        for code in ("AADB2C90080", "AADB2C90081", "AADB2C90088"):
            if code in description:
                return True
    return False


class KohlerOAuthAuth:
    """OAuth Authorization Code + PKCE against B2C_1A_signin.

    The interactive sign-in step (browser) is the caller's responsibility —
    use ``build_authorize_url`` to construct the URL and
    ``exchange_code_for_token`` to redeem the resulting code. After that, the
    library uses the persisted refresh token for all subsequent traffic.
    """

    def __init__(
        self,
        config: KohlerOAuthConfig,
        *,
        token_store: TokenStore,
    ) -> None:
        self._config = config
        self._store = token_store
        self._token: TokenInfo | None = None

    @property
    def token(self) -> TokenInfo | None:
        return self._token

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Return ``(verifier, challenge)``.

        Per RFC 7636 §4.1: the verifier is 43-128 chars from the unreserved
        URI character set. We use 64 chars of base64url-encoded random bytes
        (well within the range and unambiguously URL-safe). The challenge is
        ``base64url(SHA-256(verifier))`` with no padding (S256).
        """
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        return verifier, challenge

    def build_authorize_url(self, *, state: str, code_challenge: str) -> str:
        """Build the URL the user opens in a browser to sign in."""
        params = {
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": self._config.auth_scope,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{self._config.authorize_url}?{urlencode(params)}"

    async def exchange_code_for_token(
        self,
        session: aiohttp.ClientSession,
        *,
        code: str,
        code_verifier: str,
    ) -> TokenInfo:
        """Trade an authorization code for tokens; persist via the token store."""
        data = {
            "grant_type": "authorization_code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
            "scope": self._config.auth_scope,
        }
        return await self._post_token_request(session, data)

    async def ensure_valid_token(self, session: aiohttp.ClientSession) -> str:
        """Return a valid access token, refreshing if needed.

        Raises:
            ReauthRequired: There is no stored refresh token, or the stored
                refresh token is no longer valid. The caller must walk the
                user through interactive sign-in again.
            AuthenticationError: Other (transient) auth failure.
        """
        if self._token is None:
            self._token = await self._store.load()
        if self._token is None:
            raise ReauthRequired(
                "No stored refresh token. Run the interactive sign-in flow first."
            )
        if not self._token.is_expired:
            return self._token.access_token
        await self._refresh(session)
        assert self._token is not None
        return self._token.access_token

    async def _refresh(self, session: aiohttp.ClientSession) -> TokenInfo:
        assert self._token is not None
        if not self._token.refresh_token:
            raise ReauthRequired("Stored token has no refresh_token")
        data = {
            "grant_type": "refresh_token",
            "client_id": self._config.client_id,
            "refresh_token": self._token.refresh_token,
            "scope": self._config.auth_scope,
        }
        return await self._post_token_request(session, data, preserve_refresh_token=True)

    async def _post_token_request(
        self,
        session: aiohttp.ClientSession,
        data: dict[str, str],
        *,
        preserve_refresh_token: bool = False,
    ) -> TokenInfo:
        try:
            async with session.post(self._config.token_url, data=data) as response:
                payload: dict[str, Any] = await response.json()
                if response.status != 200:
                    description = payload.get("error_description", payload.get("error", "?"))
                    if _is_reauth_error(payload):
                        raise ReauthRequired(
                            f"Refresh token rejected: {description}",
                            status_code=response.status,
                            raw_response=payload,
                        )
                    raise AuthenticationError(
                        f"Token request failed: {description}",
                        status_code=response.status,
                        raw_response=payload,
                    )
        except aiohttp.ClientError as e:
            raise AuthenticationError(f"Network error during token request: {e}") from e

        # B2C may omit refresh_token on refresh responses (no rotation). Carry
        # the previous one forward so we can refresh again next time.
        if (
            preserve_refresh_token
            and "refresh_token" not in payload
            and self._token is not None
        ):
            payload = {**payload, "refresh_token": self._token.refresh_token}
        token = TokenInfo.from_response(payload)
        self._token = token
        await self._store.save(token)
        return token
