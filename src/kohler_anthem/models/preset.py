"""Preset models."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .base import KohlerBaseModel


class OutletDetail(KohlerBaseModel):
    """Outlet detail within a preset."""

    outlet_index: str = Field(alias="outletIndex")
    temperature: float = Field(default=37.7)
    flow: int = Field(default=50)
    value: bool = Field(default=False)  # enabled/disabled

    @field_validator("temperature", mode="before")
    @classmethod
    def parse_temperature(cls, v: Any) -> float:
        """Parse temperature string."""
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 37.7
        return float(v) if v is not None else 37.7

    @field_validator("flow", mode="before")
    @classmethod
    def parse_flow(cls, v: Any) -> int:
        """Parse flow string."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 50
        return int(v) if v is not None else 50

    @field_validator("value", mode="before")
    @classmethod
    def parse_value(cls, v: Any) -> bool:
        """Parse value string ('0'/'1') to bool."""
        if isinstance(v, str):
            return v == "1"
        return bool(v) if v is not None else False


class ValveDetail(KohlerBaseModel):
    """Valve detail within a preset."""

    valve_index: str = Field(alias="valveIndex")
    hex_string: str | None = Field(default=None, alias="hexString")
    outlets: list[OutletDetail] = Field(default_factory=list)


class Preset(KohlerBaseModel):
    """Preset configuration."""

    preset_id: str = Field(alias="presetId")
    title: str = Field(default="")
    logical_name: str = Field(default="", alias="logicalName")
    is_experience: bool = Field(default=False, alias="isExperience")
    pause_flag: str = Field(default="off", alias="pauseFlag")
    state: str = Field(default="off")
    timestamp: int | None = Field(default=None)
    time: int = Field(default=1800)  # duration in seconds
    valve_details: list[ValveDetail] = Field(default_factory=list, alias="valveDetails")

    @field_validator("is_experience", mode="before")
    @classmethod
    def parse_is_experience(cls, v: Any) -> bool:
        """Parse isExperience string."""
        if isinstance(v, str):
            return v.lower() == "true"
        return bool(v) if v is not None else False

    @field_validator("time", mode="before")
    @classmethod
    def parse_time(cls, v: Any) -> int:
        """Parse time string."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 1800
        return int(v) if v is not None else 1800

    @property
    def id(self) -> int:
        """Get preset ID as integer."""
        try:
            return int(self.preset_id)
        except ValueError:
            return 0

    @property
    def duration_minutes(self) -> int:
        """Get duration in minutes."""
        return self.time // 60


class PresetResponse(KohlerBaseModel):
    """Preset list response."""

    device_id: str = Field(default="", alias="deviceId")
    sku: str = Field(default="GCS")
    tenant_id: str = Field(default="", alias="tenantId")
    presets: list[Preset] = Field(default_factory=list)

    def get_preset(self, preset_id: int) -> Preset | None:
        """Get preset by ID.

        Args:
            preset_id: Preset ID (1-5)

        Returns:
            Preset if found, None otherwise
        """
        for preset in self.presets:
            if preset.id == preset_id:
                return preset
        return None

    def get_experiences(self) -> list[Preset]:
        """Get all experiences (not presets)."""
        return [p for p in self.presets if p.is_experience]

    def get_presets_only(self) -> list[Preset]:
        """Get presets only (not experiences)."""
        return [p for p in self.presets if not p.is_experience]
