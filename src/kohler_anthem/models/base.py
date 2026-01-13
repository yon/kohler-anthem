"""Base model with closed-API best practices."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from typing_extensions import Self


class KohlerBaseModel(BaseModel):
    """Base model for all Kohler Anthem API responses.

    Features for handling closed/undocumented APIs:
    - extra="ignore": Won't fail on unknown fields (API may add new fields)
    - populate_by_name: Allows both camelCase (API) and snake_case (Python)
    - Raw response storage for debugging when API changes
    """

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> Self:
        """Parse API response and create model instance.

        Args:
            data: Raw API response dictionary

        Returns:
            Validated model instance
        """
        return cls.model_validate(data)
