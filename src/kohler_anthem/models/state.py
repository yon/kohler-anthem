"""Device state models."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .base import KohlerBaseModel
from .enums import ConnectionState, SystemState, WarmUpStatus


class OutletState(KohlerBaseModel):
    """Individual outlet state within a valve."""

    outlet_index: str = Field(alias="outletIndex")
    outlet_temp: float = Field(default=0, alias="outletTemp")
    outlet_flow: float = Field(default=0, alias="outletFlow")

    @field_validator("outlet_temp", "outlet_flow", mode="before")
    @classmethod
    def parse_numeric(cls, v: Any) -> float:
        """Parse string numbers to float."""
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 0.0
        return float(v) if v is not None else 0.0


class ValveState(KohlerBaseModel):
    """Individual valve state."""

    valve_index: str = Field(alias="valveIndex")
    at_flow: bool = Field(default=False, alias="atFlow")
    at_temp: bool = Field(default=False, alias="atTemp")
    flow_setpoint: int = Field(default=0, alias="flowSetpoint")
    temperature_setpoint: float = Field(default=0, alias="temperatureSetpoint")
    error_flag: bool = Field(default=False, alias="errorFlag")
    error_code: int = Field(default=0, alias="errorCode")
    pause_flag: bool = Field(default=False, alias="pauseFlag")
    out1: bool = Field(default=False)
    out2: bool = Field(default=False)
    out3: bool = Field(default=False)
    outlets: list[OutletState] = Field(default_factory=list)

    @field_validator(
        "at_flow", "at_temp", "error_flag", "pause_flag", "out1", "out2", "out3", mode="before"
    )
    @classmethod
    def parse_bool(cls, v: Any) -> bool:
        """Parse string booleans ('0'/'1') to bool."""
        if isinstance(v, str):
            return v == "1" or v.lower() == "true"
        return bool(v) if v is not None else False

    @field_validator("error_code", mode="before")
    @classmethod
    def parse_error_code(cls, v: Any) -> int:
        """Parse error code to int."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 0
        return int(v) if v is not None else 0

    @field_validator("flow_setpoint", mode="before")
    @classmethod
    def parse_flow_setpoint(cls, v: Any) -> int:
        """Parse flow setpoint - API returns 0-50 scale as float, convert to 0-100%."""
        if v is None:
            return 0
        if isinstance(v, str):
            try:
                raw = float(v)
            except ValueError:
                return 0
        else:
            raw = float(v)
        # API uses 0-50 scale, convert to 0-100%
        return round(raw * 2)

    @field_validator("temperature_setpoint", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse string floats to float."""
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 0.0
        return float(v) if v is not None else 0.0

    @property
    def is_active(self) -> bool:
        """Check if any outlet is active."""
        return self.out1 or self.out2 or self.out3


class WarmUpState(KohlerBaseModel):
    """Warmup state."""

    warm_up: str = Field(default="warmUpDisabled", alias="warmUp")
    state: WarmUpStatus = Field(default=WarmUpStatus.NOT_IN_PROGRESS)

    @field_validator("warm_up", mode="before")
    @classmethod
    def parse_warm_up(cls, v: Any) -> str:
        """Parse warm_up, handling None from API."""
        if v is None:
            return "warmUpDisabled"
        return str(v)

    @field_validator("state", mode="before")
    @classmethod
    def parse_state(cls, v: Any) -> WarmUpStatus:
        """Parse warmup state string to enum."""
        if isinstance(v, str):
            try:
                return WarmUpStatus(v)
            except ValueError:
                return WarmUpStatus.NOT_IN_PROGRESS
        if isinstance(v, WarmUpStatus):
            return v
        return WarmUpStatus.NOT_IN_PROGRESS


class OutletConfiguration(KohlerBaseModel):
    """Outlet configuration limits."""

    outlet_type: int = Field(default=0, alias="outLetType")
    outlet_id: int = Field(default=0, alias="outLetId")
    max_temperature: float = Field(default=48.8, alias="maximumOutletTemperature")
    min_temperature: float = Field(default=15.0, alias="minimumOutletTemperature")
    default_temperature: float = Field(default=37.7, alias="defaultOutletTemperature")
    max_flowrate: int = Field(default=100, alias="maximumFlowrate")
    min_flowrate: int = Field(default=0, alias="minimumFlowrate")
    default_flowrate: int = Field(default=50, alias="defaultFlowrate")
    max_runtime: int = Field(default=1800, alias="maximumRuntime")

    @field_validator(
        "outlet_type",
        "outlet_id",
        "max_flowrate",
        "min_flowrate",
        "default_flowrate",
        "max_runtime",
        mode="before",
    )
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse string integers."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 0
        return int(v) if v is not None else 0

    @field_validator("max_temperature", "min_temperature", "default_temperature", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse string floats."""
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 0.0
        return float(v) if v is not None else 0.0


class ValveSettings(KohlerBaseModel):
    """Valve configuration settings."""

    valve: str = Field(default="Valve1")
    num_outlets: int = Field(default=0, alias="noOfOutlets")
    valve_firmware_type: int = Field(default=0, alias="valveFirmwareType")
    valve_firmware_version: int = Field(default=0, alias="valveFirmwareVersion")
    outlet_configurations: list[OutletConfiguration] = Field(
        default_factory=list, alias="outletConfigurations"
    )

    @field_validator("num_outlets", "valve_firmware_type", "valve_firmware_version", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse string integers."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 0
        return int(v) if v is not None else 0


class DeviceSettings(KohlerBaseModel):
    """Device settings."""

    valve_settings: list[ValveSettings] = Field(default_factory=list, alias="valveSettings")
    flow_control: str = Field(default="Disabled", alias="flowControl")


class FirmwareInfo(KohlerBaseModel):
    """Firmware version information."""

    gateway_firmware: str | None = Field(default=None)
    primary_valve_firmware: str | None = Field(default=None)
    ui_firmware: str | None = Field(default=None)


class DeviceStateData(KohlerBaseModel):
    """Inner state object from device state response."""

    warm_up_state: WarmUpState = Field(default_factory=WarmUpState, alias="warmUpState")
    current_system_state: SystemState = Field(
        default=SystemState.NORMAL, alias="currentSystemState"
    )
    preset_or_experience_id: str = Field(default="0", alias="presetOrExperienceId")
    total_volume: int = Field(default=0, alias="totalVolume")
    total_flow: float = Field(default=0.0, alias="totalFlow")
    ready: bool = Field(default=False)
    valve_state: list[ValveState] = Field(default_factory=list, alias="valveState")
    iot_active: str = Field(default="Inactive", alias="ioTActive")

    @field_validator("current_system_state", mode="before")
    @classmethod
    def parse_system_state(cls, v: Any) -> SystemState:
        """Parse system state string to enum."""
        if isinstance(v, str):
            try:
                return SystemState(v)
            except ValueError:
                return SystemState.NORMAL
        if isinstance(v, SystemState):
            return v
        return SystemState.NORMAL

    @field_validator("ready", mode="before")
    @classmethod
    def parse_ready(cls, v: Any) -> bool:
        """Parse ready string to bool."""
        if isinstance(v, str):
            return v.lower() == "true"
        return bool(v) if v is not None else False

    @field_validator("total_volume", mode="before")
    @classmethod
    def parse_total_volume(cls, v: Any) -> int:
        """Parse total volume."""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 0
        return int(v) if v is not None else 0

    @field_validator("total_flow", mode="before")
    @classmethod
    def parse_total_flow(cls, v: Any) -> float:
        """Parse total flow."""
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 0.0
        return float(v) if v is not None else 0.0

    @property
    def is_running(self) -> bool:
        """Check if shower is currently running."""
        return self.current_system_state == SystemState.SHOWER

    @property
    def active_preset_id(self) -> int | None:
        """Get active preset ID or None if no preset running."""
        if self.preset_or_experience_id == "0":
            return None
        try:
            return int(self.preset_or_experience_id)
        except ValueError:
            return None

    @property
    def is_warming_up(self) -> bool:
        """Check if warmup is in progress."""
        return self.warm_up_state.state == WarmUpStatus.IN_PROGRESS


class DeviceState(KohlerBaseModel):
    """Full device state response."""

    id: str = Field(default="")
    device_id: str = Field(default="", alias="deviceId")
    sku: str = Field(default="GCS")
    tenant_id: str = Field(default="", alias="tenantId")
    connection_state: ConnectionState = Field(
        default=ConnectionState.DISCONNECTED, alias="connectionState"
    )
    last_connected: int | None = Field(default=None, alias="lastConnected")
    state: DeviceStateData = Field(default_factory=DeviceStateData)
    setting: DeviceSettings = Field(default_factory=DeviceSettings)

    @field_validator("connection_state", mode="before")
    @classmethod
    def parse_connection_state(cls, v: Any) -> ConnectionState:
        """Parse connection state string to enum."""
        if isinstance(v, str):
            try:
                return ConnectionState(v)
            except ValueError:
                return ConnectionState.DISCONNECTED
        if isinstance(v, ConnectionState):
            return v
        return ConnectionState.DISCONNECTED

    @property
    def is_connected(self) -> bool:
        """Check if device is connected."""
        return self.connection_state == ConnectionState.CONNECTED

    @property
    def is_running(self) -> bool:
        """Check if shower is currently running."""
        return self.state.is_running

    @property
    def is_warming_up(self) -> bool:
        """Check if warmup is in progress."""
        return self.state.is_warming_up
