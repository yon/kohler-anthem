"""Tests documenting API endpoints and constants.

These tests document the Kohler Anthem cloud API structure discovered
through app traffic analysis.
"""

from kohler_anthem.const import (
    API_BASE,
    DEFAULT_SKU,
    ENDPOINTS,
)


class TestApiEndpoints:
    """Document the API endpoints discovered from traffic capture."""

    def test_api_base_url(self):
        """API base URL for all device operations."""
        assert API_BASE == "https://api-kohler-us.kohler.io"

    def test_customer_devices_endpoint(self):
        """Endpoint to discover all devices for a customer.

        Returns customer info with nested homes and devices.
        Response includes logical_name, device_id, capabilities for each device.
        """
        endpoint = ENDPOINTS["customer_devices"]
        assert "/customer-device/{customer_id}" in endpoint

    def test_device_state_endpoint(self):
        """Endpoint to get current device state.

        Returns:
            - connectionState: Connected/Disconnected
            - state.currentSystemState: Normal/Shower
            - state.valveState[]: Array of valve states with out1, out2,
              temperatureSetpoint, flowSetpoint
            - state.warmUpState: Warmup status
            - setting.valveSettings[]: Valve configuration including outlet configurations
        """
        endpoint = ENDPOINTS["device_state"]
        assert "{device_id}" in endpoint

    def test_presets_endpoint(self):
        """Endpoint to get device presets.

        Returns up to 5 user-defined presets with temperature, flow, and outlet settings.
        """
        endpoint = ENDPOINTS["presets"]
        assert "{device_id}" in endpoint

    def test_preset_control_endpoint(self):
        """Endpoint to start/stop presets.

        POST body:
        {
            "deviceId": "...",
            "sku": "GCS",
            "presetId": "1",
            "command": "start" | "stop"
        }
        """
        assert "preset_control" in ENDPOINTS

    def test_valve_control_endpoint(self):
        """Endpoint for direct valve control.

        POST body:
        {
            "deviceId": "...",
            "sku": "GCS",
            "tenantId": "...",  # customer ID
            "gcsValveControlModel": {
                "primaryValve1": "0179C801",  # hex command
                "primaryValve2": "00000000",
                ...
            }
        }
        """
        assert "valve_control" in ENDPOINTS

    def test_warmup_endpoint(self):
        """Endpoint to start/stop warmup mode.

        Warmup runs water until temperature is reached, then notifies user.
        """
        assert "warmup" in ENDPOINTS

    def test_mobile_settings_endpoint(self):
        """Endpoint to register mobile device and get IoT Hub credentials.

        POST body:
        {
            "tenantId": "...",
            "mobileDeviceId": "...",
            "username": "HomeAssistant",
            "os": "Android",
            "devicePlatform": "FirebaseCloudMessagingV1",
            "deviceHandle": "...",
            "tags": ["FirmwareUpdate"]
        }

        Returns ioTHubSettings with:
            - ioTHub: Hub hostname (e.g., prd-hub.azure-devices.net)
            - deviceId: MQTT client ID
            - username: MQTT username
            - password: SAS token
            - connectionString: Full connection string
        """
        assert "mobile_settings" in ENDPOINTS

    def test_default_sku(self):
        """Default SKU for Anthem Digital Shower."""
        assert DEFAULT_SKU == "GCS"


class TestAuthenticationFlow:
    """Document the Azure AD B2C authentication flow."""

    def test_auth_policy(self):
        """B2C policy name for sign-in."""
        # The auth flow uses Azure AD B2C with custom policies
        # Policy: B2C_1A_SignUpOrSignIn_ROPC
        pass

    def test_required_scopes(self):
        """OAuth scopes required for API access.

        Scopes:
            - openid
            - offline_access
            - {api_resource}/Customer.IoT (from config)
        """
        pass

    def test_token_refresh(self):
        """Tokens can be refreshed using refresh_token grant.

        Token lifetime is ~1 hour, refresh token is long-lived.
        """
        pass
