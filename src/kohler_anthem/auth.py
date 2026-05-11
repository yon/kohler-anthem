"""Authentication for Kohler Anthem.

Three flows live here:

* **User JWT, ROPC policy (`KohlerAuth`)** — `authenticate()` does Resource
  Owner Password Credential against the `B2C_1_ROPC_Auth` policy. Returns
  a user-bound token (`tfp=B2C_1_ROPC_Auth`). Accepted for read endpoints
  (`/devices/api/v1/*`, `/platform/api/v1/mobile/*`).
* **User JWT, B2C_1A_signin policy (`B2CSignInAuth`)** — silent refresh of
  a previously-issued `B2C_1A_signin`-policy token using a stored
  `refresh_token`. Returns a user-bound token with `tfp=B2C_1A_signin`,
  the *only* token Kohler's backend accepts on `/commands/gcs/*` writes.
  The refresh_token is seeded by an interactive OAuth flow (driven by
  Home Assistant's config flow, or by `dev/scripts/b2c_signin.py`); the
  library itself never opens a browser.
* **Service-account JWT (APIM mTLS)** — `acquire_apim_token()` presents
  the bundled `app_certificate.p12` over mTLS to Kohler's APIM gateway.
  This produces an admin-identity JWT (`oid=c143833c-...`). It is *not*
  what `/commands/*` accepts (empirically verified 2026-05-10); it exists
  for app-level operations elsewhere in the API surface.

The mTLS cert and password are embedded in every public Konnect APK on
every phone; we read them from the bundled .p12 at runtime.
"""

from __future__ import annotations

import ssl
import tempfile
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from .const import (
    APIM_CLIENT_CERT_PASSWORD,
    APIM_TOKEN_SUBSCRIPTION_KEY,
    APIM_TOKEN_URL,
)
from .exceptions import AuthenticationError

if TYPE_CHECKING:
    from .config import KohlerConfig

_BUNDLED_CERT_RESOURCE = ("kohler_anthem._data", "app_certificate.p12")


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


def _build_apim_ssl_context() -> ssl.SSLContext:
    """Build an SSLContext that presents the bundled APIM client cert.

    aiohttp does not accept a PKCS12 blob directly, and Python's `ssl` module
    only loads cert + key from PEM files on disk. So we decrypt the bundled
    .p12 with the embedded password, serialize to a single PEM containing
    both cert and unencrypted private key, write to a temp file scoped to
    this process, and point load_cert_chain() at it.
    """
    cert_bytes = resources.files(_BUNDLED_CERT_RESOURCE[0]).joinpath(
        _BUNDLED_CERT_RESOURCE[1]
    ).read_bytes()
    private_key, cert, _extras = pkcs12.load_key_and_certificates(
        cert_bytes,
        APIM_CLIENT_CERT_PASSWORD.encode(),
    )
    if private_key is None or cert is None:
        raise AuthenticationError(
            "bundled APIM client certificate is missing a key or cert; "
            "this should not happen — file a bug"
        )

    pem_blob = cert.public_bytes(serialization.Encoding.PEM) + private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # Temp file lives for the process lifetime — SSLContext caches the
    # parsed key/cert internally, so the file can be unlinked after load.
    tmp_dir = Path(tempfile.mkdtemp(prefix="kohler_anthem_mtls_"))
    pem_path = tmp_dir / "client.pem"
    pem_path.write_bytes(pem_blob)
    pem_path.chmod(0o600)
    try:
        ctx = ssl.create_default_context()
        ctx.load_cert_chain(certfile=str(pem_path))
        return ctx
    finally:
        # Best-effort cleanup. SSLContext has already parsed the file.
        try:
            pem_path.unlink()
            tmp_dir.rmdir()
        except OSError:
            pass


class KohlerAuth:
    """Handles authentication with Kohler's Azure AD B2C + APIM gateway."""

    def __init__(self, config: KohlerConfig) -> None:
        """Initialize authentication.

        Args:
            config: Kohler configuration with credentials
        """
        self._config = config
        self._token: TokenInfo | None = None
        self._apim_token: TokenInfo | None = None
        self._apim_ssl_context: ssl.SSLContext | None = None

    def apim_ssl_context(self) -> ssl.SSLContext:
        """Return (lazy-build) the SSLContext that presents the APIM client cert."""
        if self._apim_ssl_context is None:
            self._apim_ssl_context = _build_apim_ssl_context()
        return self._apim_ssl_context

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
        """Clear stored tokens (for logout or forced re-auth)."""
        self._token = None
        self._apim_token = None

    # ------------------------------------------------------------------ APIM

    @property
    def apim_access_token(self) -> str | None:
        """Current APIM service-account JWT if valid."""
        if self._apim_token and not self._apim_token.is_expired:
            return self._apim_token.access_token
        return None

    async def acquire_apim_token(self, session: aiohttp.ClientSession) -> TokenInfo:
        """Fetch the service-account JWT via mTLS to Kohler's APIM gateway.

        The library presents the bundled `app_certificate.p12` and the APIM
        subscription key; the gateway issues a JWT signed for the embedded
        service account. That JWT is what `/commands/*` writes accept.

        Args:
            session: aiohttp session — its connector must already use
                ``apim_ssl_context()``, OR the caller must pass ``ssl=...``
                explicitly. The client builds a dedicated session for this.

        Raises:
            AuthenticationError: APIM returned non-200 or the network failed.
        """
        headers = {
            "Ocp-Apim-Subscription-Key": APIM_TOKEN_SUBSCRIPTION_KEY,
            "Accept": "application/json",
            "User-Agent": "Kohler-Konnect/3.0.0 (Android 14; HomeAssistant)",
        }
        try:
            async with session.get(APIM_TOKEN_URL, headers=headers) as response:
                # The response format observed in capture is:
                #   { "access_token": "<jwt>", "expires_in": 3600, ... }
                # Some APIM versions wrap it differently — handle both.
                if response.status not in (200, 201):
                    body = await response.text()
                    raise AuthenticationError(
                        f"APIM token endpoint returned {response.status}: {body[:300]}",
                        status_code=response.status,
                    )
                payload = await response.json()
        except aiohttp.ClientError as e:
            raise AuthenticationError(
                f"Network error during APIM mTLS token fetch: {e}"
            ) from e

        # Normalize: some responses nest the token under "data" or "token"
        token_data: dict[str, Any]
        if "access_token" in payload:
            token_data = payload
        elif isinstance(payload.get("data"), dict) and "access_token" in payload["data"]:
            token_data = payload["data"]
        elif isinstance(payload.get("token"), dict) and "access_token" in payload["token"]:
            token_data = payload["token"]
        else:
            raise AuthenticationError(
                f"APIM token response missing access_token: keys={list(payload)[:6]}",
                raw_response=payload,
            )

        self._apim_token = TokenInfo.from_response(token_data)
        return self._apim_token

    async def ensure_valid_apim_token(self, session: aiohttp.ClientSession) -> str:
        """Return a fresh APIM service-account JWT, fetching if needed."""
        if self._apim_token is None or self._apim_token.is_expired:
            await self.acquire_apim_token(session)
        if self._apim_token is None:
            raise AuthenticationError("Failed to obtain APIM service-account token")
        return self._apim_token.access_token


class B2CSignInAuth:
    """Refresh-token-based JWT acquisition against B2C_1A_signin policy.

    The refresh_token is seeded by a one-time interactive sign-in (browser,
    OAuth authorization-code+PKCE) that lives outside the library — either
    Home Assistant's config flow, or the ``dev/scripts/b2c_signin.py``
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
                "`dev/scripts/b2c_signin.py` (or HA's config flow), then "
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
