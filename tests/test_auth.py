"""Tests for authentication."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from kohler_anthem import KohlerConfig
from kohler_anthem.auth import KohlerAuth, TokenInfo
from kohler_anthem.exceptions import AuthenticationError


class TestTokenInfo:
    """Test TokenInfo dataclass."""

    def test_from_response_basic(self) -> None:
        """Test creating TokenInfo from OAuth response."""
        data = {
            "access_token": "access-123",
            "refresh_token": "refresh-456",
            "expires_in": 3600,
            "id_token": "id-789",
        }
        token = TokenInfo.from_response(data)
        assert token.access_token == "access-123"
        assert token.refresh_token == "refresh-456"
        assert token.id_token == "id-789"
        assert token.expires_at > time.time()

    def test_from_response_string_expires_in(self) -> None:
        """Test expires_in as string (API quirk)."""
        data = {
            "access_token": "access-123",
            "refresh_token": "refresh-456",
            "expires_in": "3600",  # String instead of int
        }
        token = TokenInfo.from_response(data)
        assert token.expires_at > time.time()

    def test_from_response_missing_optional(self) -> None:
        """Test missing optional fields."""
        data = {
            "access_token": "access-123",
        }
        token = TokenInfo.from_response(data)
        assert token.access_token == "access-123"
        assert token.refresh_token == ""
        assert token.id_token is None

    def test_is_expired_false(self) -> None:
        """Test token not expired."""
        token = TokenInfo(
            access_token="test",
            refresh_token="test",
            expires_at=time.time() + 3600,  # 1 hour from now
        )
        assert token.is_expired is False

    def test_is_expired_true(self) -> None:
        """Test token expired."""
        token = TokenInfo(
            access_token="test",
            refresh_token="test",
            expires_at=time.time() - 100,  # 100 seconds ago
        )
        assert token.is_expired is True

    def test_is_expired_within_buffer(self) -> None:
        """Test token expires within 5 min buffer."""
        token = TokenInfo(
            access_token="test",
            refresh_token="test",
            expires_at=time.time() + 200,  # 3.3 minutes from now (within 5 min buffer)
        )
        assert token.is_expired is True


class TestKohlerAuth:
    """Test KohlerAuth class."""

    @pytest.fixture
    def config(self) -> KohlerConfig:
        """Create test config."""
        return KohlerConfig(
            username="user@example.com",
            password="secret",
            client_id="client-123",
            apim_subscription_key="apim-key",
            api_resource="api-resource",
        )

    def test_init(self, config: KohlerConfig) -> None:
        """Test auth initialization."""
        auth = KohlerAuth(config)
        assert auth.token is None
        assert auth.access_token is None

    def test_access_token_when_valid(self, config: KohlerConfig) -> None:
        """Test access_token property returns token when valid."""
        auth = KohlerAuth(config)
        auth._token = TokenInfo(
            access_token="valid-token",
            refresh_token="refresh",
            expires_at=time.time() + 3600,
        )
        assert auth.access_token == "valid-token"

    def test_access_token_when_expired(self, config: KohlerConfig) -> None:
        """Test access_token property returns None when expired."""
        auth = KohlerAuth(config)
        auth._token = TokenInfo(
            access_token="expired-token",
            refresh_token="refresh",
            expires_at=time.time() - 100,
        )
        assert auth.access_token is None

    def test_clear_token(self, config: KohlerConfig) -> None:
        """Test clear_token removes stored token."""
        auth = KohlerAuth(config)
        auth._token = TokenInfo(
            access_token="token",
            refresh_token="refresh",
            expires_at=time.time() + 3600,
        )
        auth.clear_token()
        assert auth.token is None

    @pytest.mark.asyncio
    async def test_authenticate_success(self, config: KohlerConfig) -> None:
        """Test successful authentication."""
        auth = KohlerAuth(config)

        # Mock session
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        })

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        token = await auth.authenticate(mock_session)

        assert token.access_token == "new-access-token"
        assert auth.token is not None

    @pytest.mark.asyncio
    async def test_authenticate_failure(self, config: KohlerConfig) -> None:
        """Test authentication failure."""
        auth = KohlerAuth(config)

        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.json = AsyncMock(return_value={
            "error": "invalid_grant",
            "error_description": "Invalid credentials",
        })

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with pytest.raises(AuthenticationError) as exc_info:
            await auth.authenticate(mock_session)

        assert exc_info.value.status_code == 401
        assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_ensure_valid_token_authenticates_when_none(self, config: KohlerConfig) -> None:
        """Test ensure_valid_token authenticates when no token."""
        auth = KohlerAuth(config)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "access_token": "new-token",
            "refresh_token": "refresh",
            "expires_in": 3600,
        })

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        token = await auth.ensure_valid_token(mock_session)

        assert token == "new-token"

    @pytest.mark.asyncio
    async def test_refresh_no_token(self, config: KohlerConfig) -> None:
        """Test refresh fails when no token available."""
        auth = KohlerAuth(config)

        mock_session = MagicMock()

        with pytest.raises(AuthenticationError, match="No refresh token"):
            await auth.refresh(mock_session)
