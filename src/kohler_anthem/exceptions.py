"""Exception hierarchy for Kohler Anthem API client.

All exceptions include context for debugging closed API issues:
- status_code: HTTP status code (if applicable)
- raw_response: Raw API response for debugging when API changes
"""

from __future__ import annotations

from typing import Any


class KohlerAnthemError(Exception):
    """Base exception for all Kohler Anthem errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        raw_response: dict[str, Any] | str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.raw_response = raw_response

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.raw_response is not None:
            raw = str(self.raw_response)
            if len(raw) > 200:
                raw = raw[:200] + "..."
            parts.append(f"response={raw}")
        return " | ".join(parts)


class AuthenticationError(KohlerAnthemError):
    """Authentication failed."""


class TokenExpiredError(AuthenticationError):
    """Access token has expired."""


class InvalidCredentialsError(AuthenticationError):
    """Invalid username or password."""


class ApiError(KohlerAnthemError):
    """API request failed."""


class DeviceNotFoundError(ApiError):
    """Device not found."""


class CommandFailedError(ApiError):
    """Command execution failed."""


class ConnectionError(KohlerAnthemError):
    """Network connection error."""


class ValidationError(KohlerAnthemError):
    """Request validation error."""
