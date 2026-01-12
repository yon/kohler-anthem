"""Kohler Anthem Digital Shower API client.

A Python library for controlling Kohler Anthem digital showers.

Example:
    from kohler_anthem import KohlerAnthemClient, KohlerConfig, Outlet

    config = KohlerConfig(
        username="user@example.com",
        password="password",
        client_id="azure-ad-client-id",
        apim_subscription_key="azure-apim-key",
        api_resource="azure-api-resource-id",
    )

    async with KohlerAnthemClient(config) as client:
        customer = await client.get_customer("customer-id")
        device_id = customer.get_all_devices()[0].device_id
        await client.turn_on_outlet(device_id, Outlet.SHOWERHEAD)
"""

from .auth import KohlerAuth, TokenInfo
from .client import KohlerAnthemClient
from .config import KohlerConfig
from .converters import (
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    gallons_to_liters,
    liters_to_gallons,
)
from .exceptions import (
    ApiError,
    AuthenticationError,
    DeviceNotFoundError,
    KohlerAnthemError,
)
from .models import (
    CommandResponse,
    ConnectionState,
    Customer,
    Device,
    DeviceSettings,
    DeviceState,
    DeviceStateData,
    FlowUnit,
    Home,
    KohlerBaseModel,
    Outlet,
    OutletConfiguration,
    OutletDetail,
    OutletState,
    OutletType,
    Preset,
    PresetResponse,
    SystemState,
    TemperatureUnit,
    ValveControlModel,
    ValveDetail,
    ValveMode,
    ValvePrefix,
    ValveSettings,
    ValveState,
    WarmUpState,
    WarmUpStatus,
)
from .valve import (
    create_off_command,
    create_outlet_command,
    create_stop_command,
    decode_valve_command,
    encode_valve_command,
    is_valve_off,
    outlet_to_mode,
)

__all__ = [
    # Client
    "KohlerAnthemClient",
    # Config
    "KohlerConfig",
    # Auth
    "KohlerAuth",
    "TokenInfo",
    # Exceptions
    "KohlerAnthemError",
    "AuthenticationError",
    "ApiError",
    "DeviceNotFoundError",
    # Models
    "KohlerBaseModel",
    "CommandResponse",
    "ConnectionState",
    "Customer",
    "Device",
    "DeviceSettings",
    "DeviceState",
    "DeviceStateData",
    "FlowUnit",
    "Home",
    "Outlet",
    "OutletConfiguration",
    "OutletDetail",
    "OutletState",
    "OutletType",
    "Preset",
    "PresetResponse",
    "SystemState",
    "TemperatureUnit",
    "ValveControlModel",
    "ValveDetail",
    "ValveMode",
    "ValvePrefix",
    "ValveSettings",
    "ValveState",
    "WarmUpState",
    "WarmUpStatus",
    # Valve helpers
    "encode_valve_command",
    "decode_valve_command",
    "create_off_command",
    "create_outlet_command",
    "create_stop_command",
    "is_valve_off",
    "outlet_to_mode",
    # Converters
    "celsius_to_fahrenheit",
    "fahrenheit_to_celsius",
    "gallons_to_liters",
    "liters_to_gallons",
]

__version__ = "0.1.0"
