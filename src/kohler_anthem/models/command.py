"""Command request and response models."""

from __future__ import annotations

from pydantic import Field

from .base import KohlerBaseModel


class CommandResponse(KohlerBaseModel):
    """Response from command endpoints."""

    correlation_id: str = Field(default="", alias="correlationId")
    timestamp: int = Field(default=0)


class ValveControlModel(KohlerBaseModel):
    """Valve control values for solowritesystem command."""

    primary_valve1: str = Field(default="00000000", alias="primaryValve1")
    secondary_valve1: str = Field(default="00000000", alias="secondaryValve1")
    secondary_valve2: str = Field(default="00000000", alias="secondaryValve2")
    secondary_valve3: str = Field(default="00000000", alias="secondaryValve3")
    secondary_valve4: str = Field(default="00000000", alias="secondaryValve4")
    secondary_valve5: str = Field(default="00000000", alias="secondaryValve5")
    secondary_valve6: str = Field(default="00000000", alias="secondaryValve6")
    secondary_valve7: str = Field(default="00000000", alias="secondaryValve7")
