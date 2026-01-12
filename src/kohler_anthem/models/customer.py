"""Customer, Home, and Device models."""

from __future__ import annotations

from pydantic import Field

from .base import KohlerBaseModel


class Device(KohlerBaseModel):
    """Device information from discovery response."""

    device_id: str = Field(alias="deviceId")
    logical_name: str = Field(default="", alias="logicalName")
    sku: str = Field(default="GCS")
    serial_number: str | None = Field(default=None, alias="serialNumber")
    is_active: bool = Field(default=True, alias="isActive")
    is_provisioned: bool = Field(default=False, alias="isProvisioned")
    ssid: str | None = Field(default=None)
    created_time: int | None = Field(default=None, alias="createdTime")


class Home(KohlerBaseModel):
    """Home information with devices."""

    home_id: str = Field(alias="homeId")
    home_name: str = Field(default="", alias="homeName")
    address: str | None = Field(default=None)
    home_latitude: float | None = Field(default=None, alias="homeLatitude")
    home_longitude: float | None = Field(default=None, alias="homeLongitude")
    devices: list[Device] = Field(default_factory=list)
    created_time: int | None = Field(default=None, alias="createdTime")


class Customer(KohlerBaseModel):
    """Customer account information."""

    id: str
    tenant_id: str = Field(alias="tenantId")
    temperature_unit: str = Field(default="Fahrenheit", alias="temperatureUnit")
    water_units: str = Field(default="Standard", alias="waterUnits")
    is_active: bool = Field(default=True, alias="isActive")
    customer_home: list[Home] = Field(default_factory=list, alias="customerHome")
    created_time: int | None = Field(default=None, alias="createdTime")

    def get_all_devices(self) -> list[Device]:
        """Get all devices across all homes.

        Returns:
            Flattened list of all devices
        """
        return [device for home in self.customer_home for device in home.devices]

    def get_device(self, device_id: str) -> Device | None:
        """Get device by ID.

        Args:
            device_id: Device identifier

        Returns:
            Device if found, None otherwise
        """
        for device in self.get_all_devices():
            if device.device_id == device_id:
                return device
        return None
