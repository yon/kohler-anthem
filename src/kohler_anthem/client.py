"""Kohler Anthem API client."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import aiohttp

from .auth import KohlerAuth
from .const import (
    API_BASE,
    DEFAULT_SKU,
    ENDPOINTS,
    FLOW_DEFAULT_PERCENT,
    REQUEST_TIMEOUT,
    TEMP_DEFAULT_CELSIUS,
)
from .exceptions import ApiError, DeviceNotFoundError
from .models import (
    CommandResponse,
    Customer,
    DeviceState,
    Outlet,
    PresetResponse,
    ValveControlModel,
    ValveMode,
)
from .valve import create_off_command, create_outlet_command, encode_valve_command

if TYPE_CHECKING:
    from .config import KohlerConfig


class KohlerAnthemClient:
    """Async client for Kohler Anthem Digital Shower API."""

    def __init__(
        self,
        config: KohlerConfig,
        *,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the client.

        Args:
            config: Kohler configuration with credentials and API keys
            timeout: Request timeout in seconds
        """
        self._config = config
        self._api_base = API_BASE
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._auth = KohlerAuth(config)
        self._session: aiohttp.ClientSession | None = None
        self._owns_session = False
        self._customer_id: str | None = None

    async def __aenter__(self) -> KohlerAnthemClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self, session: aiohttp.ClientSession | None = None) -> None:
        """Connect and authenticate with the API.

        Args:
            session: Optional existing aiohttp session to use
        """
        if session:
            self._session = session
            self._owns_session = False
        else:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True

        await self._auth.authenticate(self._session)

    async def close(self) -> None:
        """Close the client session."""
        if self._session and self._owns_session:
            await self._session.close()
        self._session = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated API request.

        Args:
            method: HTTP method
            endpoint: API endpoint (relative to base)
            params: Query parameters
            json: JSON body

        Returns:
            Response JSON

        Raises:
            ApiError: If request fails
        """
        if not self._session:
            raise ApiError("Client not connected, call connect() first")

        token = await self._auth.ensure_valid_token(self._session)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": self._config.apim_subscription_key,
        }

        url = f"{self._api_base}{endpoint}"

        try:
            async with self._session.request(
                method, url, headers=headers, params=params, json=json
            ) as response:
                data: dict[str, Any] = await response.json()

                if response.status == 404:
                    raise DeviceNotFoundError(
                        f"Resource not found: {endpoint}",
                        status_code=404,
                        raw_response=data,
                    )

                if response.status >= 400:
                    raise ApiError(
                        f"API error {response.status}: {data}",
                        status_code=response.status,
                        raw_response=data,
                    )

                return data

        except aiohttp.ClientError as e:
            raise ApiError(f"Network error: {e}") from e

    # =========================================================================
    # Device Discovery
    # =========================================================================

    async def get_customer(self, customer_id: str) -> Customer:
        """Get customer information with all homes and devices.

        Args:
            customer_id: Customer ID (from login token)

        Returns:
            Customer with nested homes and devices
        """
        self._customer_id = customer_id
        endpoint = ENDPOINTS["customer_devices"].format(customer_id=customer_id)
        data = await self._request("GET", endpoint)
        return Customer.from_response(data)

    async def discover_devices(self, customer_id: str) -> list[str]:
        """Discover all device IDs for a customer.

        Args:
            customer_id: Customer ID

        Returns:
            List of device IDs
        """
        customer = await self.get_customer(customer_id)
        return [d.device_id for d in customer.get_all_devices()]

    # =========================================================================
    # Device State
    # =========================================================================

    async def get_device_state(self, device_id: str) -> DeviceState:
        """Get current device state.

        Args:
            device_id: Device ID

        Returns:
            Current device state
        """
        endpoint = ENDPOINTS["device_state"].format(device_id=device_id)
        data = await self._request("GET", endpoint)
        return DeviceState.from_response(data)

    # =========================================================================
    # Presets
    # =========================================================================

    async def get_presets(self, device_id: str) -> PresetResponse:
        """Get all presets and experiences for a device.

        Args:
            device_id: Device ID

        Returns:
            Preset response with all presets
        """
        endpoint = ENDPOINTS["presets"].format(device_id=device_id)
        data = await self._request("GET", endpoint)
        return PresetResponse.from_response(data)

    async def start_preset(
        self,
        device_id: str,
        preset_id: int,
        *,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Start a preset.

        Args:
            device_id: Device ID
            preset_id: Preset ID (1-5)
            sku: Device SKU

        Returns:
            Command response
        """
        endpoint = ENDPOINTS["preset_control"]
        payload = {
            "deviceId": device_id,
            "sku": sku,
            "presetId": str(preset_id),
            "command": "start",
        }
        data = await self._request("POST", endpoint, json=payload)
        return CommandResponse.from_response(data)

    async def stop_preset(
        self,
        device_id: str,
        preset_id: int,
        *,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Stop a running preset.

        Args:
            device_id: Device ID
            preset_id: Preset ID that is currently running
            sku: Device SKU

        Returns:
            Command response
        """
        endpoint = ENDPOINTS["preset_control"]
        payload = {
            "deviceId": device_id,
            "sku": sku,
            "presetId": str(preset_id),
            "command": "stop",
        }
        data = await self._request("POST", endpoint, json=payload)
        return CommandResponse.from_response(data)

    # =========================================================================
    # Warmup
    # =========================================================================

    async def start_warmup(
        self,
        device_id: str,
        preset_id: int = 1,
        *,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Start warmup mode.

        Args:
            device_id: Device ID
            preset_id: Preset to warm up for
            sku: Device SKU

        Returns:
            Command response
        """
        endpoint = ENDPOINTS["warmup"]
        payload = {
            "deviceId": device_id,
            "sku": sku,
            "presetId": str(preset_id),
            "command": "start",
        }
        data = await self._request("POST", endpoint, json=payload)
        return CommandResponse.from_response(data)

    async def stop_warmup(
        self,
        device_id: str,
        preset_id: int = 1,
        *,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Stop warmup mode.

        Args:
            device_id: Device ID
            preset_id: Preset being warmed up
            sku: Device SKU

        Returns:
            Command response
        """
        endpoint = ENDPOINTS["warmup"]
        payload = {
            "deviceId": device_id,
            "sku": sku,
            "presetId": str(preset_id),
            "command": "stop",
        }
        data = await self._request("POST", endpoint, json=payload)
        return CommandResponse.from_response(data)

    # =========================================================================
    # Direct Valve Control
    # =========================================================================

    async def control_valve(
        self,
        device_id: str,
        valve_control: ValveControlModel,
        *,
        tenant_id: str | None = None,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Send raw valve control command.

        Args:
            device_id: Device ID
            valve_control: Valve control values
            tenant_id: Tenant ID (customer ID)
            sku: Device SKU

        Returns:
            Command response
        """
        endpoint = ENDPOINTS["valve_control"]
        payload = {
            "gcsValveControlModel": valve_control.model_dump(by_alias=True),
            "deviceId": device_id,
            "sku": sku,
        }
        if tenant_id:
            payload["tenantId"] = tenant_id

        data = await self._request("POST", endpoint, json=payload)
        return CommandResponse.from_response(data)

    async def turn_on_outlet(
        self,
        device_id: str,
        outlet: Outlet,
        *,
        temperature_celsius: float = TEMP_DEFAULT_CELSIUS,
        flow_percent: int = FLOW_DEFAULT_PERCENT,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Turn on a specific outlet.

        Args:
            device_id: Device ID
            outlet: Which outlet to turn on
            temperature_celsius: Target temperature
            flow_percent: Flow rate percentage
            sku: Device SKU

        Returns:
            Command response
        """
        valve_hex = create_outlet_command(
            outlet,
            temperature_celsius=temperature_celsius,
            flow_percent=flow_percent,
        )
        valve_control = ValveControlModel(primary_valve1=valve_hex)
        return await self.control_valve(
            device_id, valve_control, tenant_id=self._customer_id, sku=sku
        )

    async def turn_off(
        self,
        device_id: str,
        *,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Turn off all outlets.

        Args:
            device_id: Device ID
            sku: Device SKU

        Returns:
            Command response
        """
        valve_control = ValveControlModel(primary_valve1=create_off_command())
        return await self.control_valve(
            device_id, valve_control, tenant_id=self._customer_id, sku=sku
        )

    async def set_temperature(
        self,
        device_id: str,
        temperature_celsius: float,
        *,
        outlet: Outlet = Outlet.SHOWERHEAD,
        flow_percent: int = FLOW_DEFAULT_PERCENT,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Set temperature for active outlet.

        Args:
            device_id: Device ID
            temperature_celsius: Target temperature
            outlet: Which outlet
            flow_percent: Flow rate
            sku: Device SKU

        Returns:
            Command response
        """
        return await self.turn_on_outlet(
            device_id,
            outlet,
            temperature_celsius=temperature_celsius,
            flow_percent=flow_percent,
            sku=sku,
        )

    async def set_flow(
        self,
        device_id: str,
        flow_percent: int,
        *,
        outlet: Outlet = Outlet.SHOWERHEAD,
        temperature_celsius: float = TEMP_DEFAULT_CELSIUS,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Set flow rate for active outlet.

        Args:
            device_id: Device ID
            flow_percent: Flow rate percentage (0-100)
            outlet: Which outlet
            temperature_celsius: Temperature setting
            sku: Device SKU

        Returns:
            Command response
        """
        return await self.turn_on_outlet(
            device_id,
            outlet,
            temperature_celsius=temperature_celsius,
            flow_percent=flow_percent,
            sku=sku,
        )

    async def pause(
        self,
        device_id: str,
        *,
        temperature_celsius: float = TEMP_DEFAULT_CELSIUS,
        flow_percent: int = FLOW_DEFAULT_PERCENT,
        sku: str = DEFAULT_SKU,
    ) -> CommandResponse:
        """Pause water flow (keeps session active).

        Args:
            device_id: Device ID
            temperature_celsius: Current temperature setting
            flow_percent: Current flow setting
            sku: Device SKU

        Returns:
            Command response
        """
        valve_hex = encode_valve_command(
            temperature_celsius=temperature_celsius,
            flow_percent=flow_percent,
            mode=ValveMode.STOP,
        )
        valve_control = ValveControlModel(primary_valve1=valve_hex)
        return await self.control_valve(
            device_id, valve_control, tenant_id=self._customer_id, sku=sku
        )

    # =========================================================================
    # IoT Hub / Mobile Settings
    # =========================================================================

    async def register_mobile_device(
        self,
        tenant_id: str,
        mobile_device_id: str | None = None,
    ) -> dict[str, Any]:
        """Register mobile device and get IoT Hub credentials.

        This endpoint returns the credentials needed to connect to Azure IoT Hub
        for real-time state updates via MQTT.

        Args:
            tenant_id: Customer/tenant ID
            mobile_device_id: Optional device ID (generated if not provided)

        Returns:
            Dictionary with IoT Hub settings including:
            - ioTHub: IoT Hub hostname
            - deviceId: MQTT client device ID
            - connectionString: Full connection string
            - username: MQTT username
            - password: SAS token for authentication
        """
        if not mobile_device_id:
            mobile_device_id = uuid.uuid4().hex[:16]

        endpoint = ENDPOINTS["mobile_settings"]
        # Match the format used by the mobile app
        payload = {
            "tenantId": tenant_id,
            "mobileDeviceId": mobile_device_id,
            "username": "HomeAssistant",
            "os": "Android",  # Must be Android or iOS
            "devicePlatform": "FirebaseCloudMessagingV1",
            "deviceHandle": f"ha_{mobile_device_id}",  # Dummy FCM token
            "tags": ["FirmwareUpdate"],
        }

        data = await self._request("POST", endpoint, json=payload)
        result: dict[str, Any] = data.get("ioTHubSettings", {})
        return result
