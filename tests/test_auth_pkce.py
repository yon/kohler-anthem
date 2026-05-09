"""Tests for OAuth Authorization Code + PKCE auth (B2C_1A_signin)."""

from __future__ import annotations

import base64
import hashlib
import re
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from kohler_anthem.auth import KohlerOAuthAuth, TokenInfo, TokenStore
from kohler_anthem.config import KohlerOAuthConfig
from kohler_anthem.exceptions import AuthenticationError, ReauthRequired

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def oauth_config() -> KohlerOAuthConfig:
    return KohlerOAuthConfig(
        client_id="11111111-1111-1111-1111-111111111111",
        apim_subscription_key="apim-key",
        api_resource="22222222-2222-2222-2222-222222222222",
    )


class _MemoryTokenStore:
    """In-memory TokenStore for tests. Records save() calls."""

    def __init__(self, initial: TokenInfo | None = None) -> None:
        self._token = initial
        self.saved: list[TokenInfo] = []
        self.load_calls = 0

    async def load(self) -> TokenInfo | None:
        self.load_calls += 1
        return self._token

    async def save(self, token: TokenInfo) -> None:
        self._token = token
        self.saved.append(token)


def _mock_token_endpoint(
    *,
    status: int = 200,
    payload: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock aiohttp.ClientSession whose .post returns `payload`."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=payload or {})
    session = MagicMock()
    session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=response)))
    return session


# ---------------------------------------------------------------------------
# OAuth config
# ---------------------------------------------------------------------------


class TestKohlerOAuthConfig:
    def test_authorize_url_uses_b2c_1a_signin_policy(self, oauth_config: KohlerOAuthConfig) -> None:
        """Authorize URL must point at the interactive policy, not ROPC."""
        url = oauth_config.authorize_url
        assert "b2c_1a_signin" in url.lower()
        assert "ropc" not in url.lower()
        # B2C_1A_signin uses no `tfp/` prefix (unlike ROPC).
        assert "/tfp/" not in url

    def test_token_url_uses_b2c_1a_signin_policy(self, oauth_config: KohlerOAuthConfig) -> None:
        url = oauth_config.token_url
        assert "b2c_1a_signin" in url.lower()
        assert "/tfp/" not in url
        assert url.endswith("/oauth2/v2.0/token")

    def test_auth_scope_includes_apiaccess(self, oauth_config: KohlerOAuthConfig) -> None:
        scope = oauth_config.auth_scope
        assert "openid" in scope
        assert "offline_access" in scope
        assert "/apiaccess" in scope
        assert oauth_config.api_resource in scope

    def test_default_redirect_uri_is_loopback(self, oauth_config: KohlerOAuthConfig) -> None:
        """Loopback HTTP works without app-registration changes for desktop use."""
        assert oauth_config.redirect_uri.startswith("http://127.0.0.1")


# ---------------------------------------------------------------------------
# PKCE pair
# ---------------------------------------------------------------------------


class TestPkcePair:
    def test_pair_generates_valid_verifier_and_challenge(self) -> None:
        verifier, challenge = KohlerOAuthAuth.generate_pkce_pair()
        # RFC 7636 §4.1: verifier is 43-128 chars from the unreserved set.
        assert 43 <= len(verifier) <= 128
        assert re.fullmatch(r"[A-Za-z0-9\-._~]+", verifier)
        # Challenge must be base64url(SHA-256(verifier)) with no padding.
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert challenge == expected

    def test_each_call_returns_a_fresh_pair(self) -> None:
        a_verifier, a_challenge = KohlerOAuthAuth.generate_pkce_pair()
        b_verifier, b_challenge = KohlerOAuthAuth.generate_pkce_pair()
        assert a_verifier != b_verifier
        assert a_challenge != b_challenge


# ---------------------------------------------------------------------------
# Authorize URL
# ---------------------------------------------------------------------------


class TestAuthorizeUrl:
    def test_authorize_url_includes_required_params(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        store = _MemoryTokenStore()
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        url = auth.build_authorize_url(state="state-abc", code_challenge="chal-xyz")
        parts = urlsplit(url)
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert params["client_id"] == oauth_config.client_id
        assert params["redirect_uri"] == oauth_config.redirect_uri
        assert params["response_type"] == "code"
        assert params["response_mode"] == "query"
        assert params["scope"] == oauth_config.auth_scope
        assert params["code_challenge"] == "chal-xyz"
        assert params["code_challenge_method"] == "S256"
        assert params["state"] == "state-abc"


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


class TestExchangeCodeForToken:
    @pytest.mark.asyncio
    async def test_persists_refresh_token(self, oauth_config: KohlerOAuthConfig) -> None:
        store = _MemoryTokenStore()
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = _mock_token_endpoint(
            payload={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
                "id_token": "id-1",
            }
        )
        token = await auth.exchange_code_for_token(
            session, code="code-1", code_verifier="verifier-1"
        )
        assert token.access_token == "access-1"
        assert token.refresh_token == "refresh-1"
        assert len(store.saved) == 1
        assert store.saved[0].refresh_token == "refresh-1"

    @pytest.mark.asyncio
    async def test_sends_pkce_code_verifier_not_client_secret(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        """Public-client PKCE: send code_verifier; do NOT send client_secret."""
        store = _MemoryTokenStore()
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = _mock_token_endpoint(
            payload={
                "access_token": "a",
                "refresh_token": "r",
                "expires_in": 3600,
            }
        )
        await auth.exchange_code_for_token(session, code="c", code_verifier="my-verifier")
        # session.post(url, data=...) — the data dict is the second positional or `data=`
        call = session.post.call_args
        sent = call.kwargs.get("data") or (call.args[1] if len(call.args) > 1 else None)
        assert sent is not None
        assert sent["grant_type"] == "authorization_code"
        assert sent["code"] == "c"
        assert sent["code_verifier"] == "my-verifier"
        assert sent["client_id"] == oauth_config.client_id
        assert sent["redirect_uri"] == oauth_config.redirect_uri
        assert "client_secret" not in sent

    @pytest.mark.asyncio
    async def test_failure_raises_authentication_error(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        store = _MemoryTokenStore()
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = _mock_token_endpoint(
            status=400,
            payload={
                "error": "invalid_grant",
                "error_description": "AADB2C90090: bad code",
            },
        )
        with pytest.raises(AuthenticationError) as exc:
            await auth.exchange_code_for_token(session, code="bad", code_verifier="v")
        assert exc.value.status_code == 400
        assert "AADB2C90090" in str(exc.value)
        assert store.saved == []  # nothing persisted on failure


# ---------------------------------------------------------------------------
# Refresh + ensure_valid_token
# ---------------------------------------------------------------------------


class TestRefreshAndEnsureValid:
    @pytest.mark.asyncio
    async def test_refresh_token_used_when_present(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        """A stored refresh token short-circuits the interactive flow."""
        stored = TokenInfo(
            access_token="old-access",
            refresh_token="old-refresh",
            expires_at=time.time() - 100,  # already expired
        )
        store = _MemoryTokenStore(initial=stored)
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = _mock_token_endpoint(
            payload={
                "access_token": "new-access",
                "refresh_token": "old-refresh",  # IdP didn't rotate
                "expires_in": 3600,
            }
        )
        access = await auth.ensure_valid_token(session)
        assert access == "new-access"
        # Send-side: refresh_token grant (not authorization_code)
        sent = session.post.call_args.kwargs["data"]
        assert sent["grant_type"] == "refresh_token"
        assert sent["refresh_token"] == "old-refresh"
        assert "client_secret" not in sent

    @pytest.mark.asyncio
    async def test_refresh_token_rotation_persists_new_value(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        """When the IdP returns a new refresh token, the store must be updated."""
        stored = TokenInfo(
            access_token="old-access",
            refresh_token="old-refresh",
            expires_at=time.time() - 100,
        )
        store = _MemoryTokenStore(initial=stored)
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = _mock_token_endpoint(
            payload={
                "access_token": "new-access",
                "refresh_token": "rotated-refresh",
                "expires_in": 3600,
            }
        )
        await auth.ensure_valid_token(session)
        assert any(t.refresh_token == "rotated-refresh" for t in store.saved)

    @pytest.mark.asyncio
    async def test_refresh_failure_raises_reauth_required(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        """invalid_grant on refresh means the user must redo interactive sign-in."""
        stored = TokenInfo(
            access_token="old-access",
            refresh_token="dead-refresh",
            expires_at=time.time() - 100,
        )
        store = _MemoryTokenStore(initial=stored)
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = _mock_token_endpoint(
            status=400,
            payload={
                "error": "invalid_grant",
                "error_description": "AADB2C90080: refresh token expired",
            },
        )
        with pytest.raises(ReauthRequired):
            await auth.ensure_valid_token(session)

    @pytest.mark.asyncio
    async def test_no_stored_token_raises_reauth_required(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        """ensure_valid_token cannot interactively sign in; absence => ReauthRequired."""
        store = _MemoryTokenStore(initial=None)
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = MagicMock()
        with pytest.raises(ReauthRequired):
            await auth.ensure_valid_token(session)

    @pytest.mark.asyncio
    async def test_unexpired_token_skips_refresh(
        self, oauth_config: KohlerOAuthConfig
    ) -> None:
        """If the access token is still good, don't hit the network."""
        stored = TokenInfo(
            access_token="still-good",
            refresh_token="r",
            expires_at=time.time() + 3600,
        )
        store = _MemoryTokenStore(initial=stored)
        auth = KohlerOAuthAuth(oauth_config, token_store=store)
        session = MagicMock()
        access = await auth.ensure_valid_token(session)
        assert access == "still-good"
        session.post.assert_not_called()


# ---------------------------------------------------------------------------
# TokenStore protocol smoke test
# ---------------------------------------------------------------------------


def test_memory_store_satisfies_token_store_protocol() -> None:
    """Static check that _MemoryTokenStore is a structural TokenStore."""
    store: TokenStore = _MemoryTokenStore()
    assert hasattr(store, "load")
    assert hasattr(store, "save")
