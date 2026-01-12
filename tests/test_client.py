"""Tests for KohlerAnthemClient."""

from __future__ import annotations

import pytest
from aioresponses import aioresponses

from kohler_anthem import (
    KohlerAnthemClient,
    KohlerConfig,
    Outlet,
)
from kohler_anthem.exceptions import ApiError, DeviceNotFoundError
from kohler_anthem.const import API_BASE


@pytest.fixture
def config() -> KohlerConfig:
    """Create test config."""
    return KohlerConfig(
        username="user@example.com",
        password="secret",
        client_id="client-123",
        apim_subscription_key="apim-key",
        api_resource="api-resource",
    )


@pytest.fixture
def mock_token_response() -> dict:
    """Mock OAuth token response."""
    return {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_in": 3600,
        "id_token": "test-id-token",
    }


@pytest.fixture
def mock_customer_response() -> dict:
    """Mock customer/device discovery response."""
    return {
        "id": "customer-123",
        "tenantId": "tenant-456",
        "temperatureUnit": "Celsius",
        "customerHome": [
            {
                "homeId": "home-1",
                "homeName": "My House",
                "devices": [
                    {
                        "deviceId": "gcs-device-1",
                        "logicalName": "Master Shower",
                        "sku": "GCS",
                        "isActive": True,
                    }
                ],
            }
        ],
    }


@pytest.fixture
def mock_device_state_response() -> dict:
    """Mock device state response."""
    return {
        "id": "state-1",
        "deviceId": "gcs-device-1",
        "sku": "GCS",
        "connectionState": "Connected",
        "state": {
            "currentSystemState": "normalOperation",
            "presetOrExperienceId": "0",
            "warmUpState": {
                "warmUp": "warmUpDisabled",
                "state": "warmUpNotInProgress",
            },
            "valveState": [
                {
                    "valveIndex": "1",
                    "atFlow": "0",
                    "atTemp": "0",
                    "flowSetpoint": "50",
                    "temperatureSetpoint": "37.7",
                    "out1": "0",
                    "out2": "0",
                    "out3": "0",
                }
            ],
        },
        "setting": {
            "valveSettings": [],
        },
    }


@pytest.fixture
def mock_presets_response() -> dict:
    """Mock presets response."""
    return {
        "deviceId": "gcs-device-1",
        "sku": "GCS",
        "presets": [
            {
                "presetId": "1",
                "title": "Morning Shower",
                "isExperience": "false",
                "state": "off",
                "time": "1800",
                "valveDetails": [],
            },
            {
                "presetId": "2",
                "title": "Relaxation",
                "isExperience": "true",
                "state": "off",
                "time": "2400",
                "valveDetails": [],
            },
        ],
    }


@pytest.fixture
def mock_command_response() -> dict:
    """Mock command response."""
    return {
        "correlationId": "cmd-123",
        "timestamp": 1234567890,
    }


class TestKohlerAnthemClient:
    """Test KohlerAnthemClient class."""

    @pytest.mark.asyncio
    async def test_connect_and_close(
        self, config: KohlerConfig, mock_token_response: dict
    ) -> None:
        """Test client connect and close."""
        client = KohlerAnthemClient(config)

        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)

            await client.connect()
            assert client._session is not None
            assert client._auth.token is not None

            await client.close()
            assert client._session is None

    @pytest.mark.asyncio
    async def test_context_manager(
        self, config: KohlerConfig, mock_token_response: dict
    ) -> None:
        """Test async context manager."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)

            async with KohlerAnthemClient(config) as client:
                assert client._session is not None

    @pytest.mark.asyncio
    async def test_get_customer(
        self,
        config: KohlerConfig,
        mock_token_response: dict,
        mock_customer_response: dict,
    ) -> None:
        """Test get_customer."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.get(
                f"{API_BASE}/devices/api/v1/device-management/customer-device/customer-123",
                payload=mock_customer_response,
            )

            async with KohlerAnthemClient(config) as client:
                customer = await client.get_customer("customer-123")

                assert customer.id == "customer-123"
                assert len(customer.customer_home) == 1
                assert len(customer.get_all_devices()) == 1
                assert customer.get_all_devices()[0].device_id == "gcs-device-1"

    @pytest.mark.asyncio
    async def test_get_device_state(
        self,
        config: KohlerConfig,
        mock_token_response: dict,
        mock_device_state_response: dict,
    ) -> None:
        """Test get_device_state."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.get(
                f"{API_BASE}/devices/api/v1/device-management/gcs-state/gcsadvancestate/gcs-device-1",
                payload=mock_device_state_response,
            )

            async with KohlerAnthemClient(config) as client:
                state = await client.get_device_state("gcs-device-1")

                assert state.device_id == "gcs-device-1"
                assert state.is_connected is True
                assert state.is_running is False
                assert len(state.state.valve_state) == 1

    @pytest.mark.asyncio
    async def test_get_presets(
        self,
        config: KohlerConfig,
        mock_token_response: dict,
        mock_presets_response: dict,
    ) -> None:
        """Test get_presets."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.get(
                f"{API_BASE}/devices/api/v1/device-management/gcs-preset/gcs-device-1",
                payload=mock_presets_response,
            )

            async with KohlerAnthemClient(config) as client:
                presets = await client.get_presets("gcs-device-1")

                assert len(presets.presets) == 2
                assert presets.get_preset(1).title == "Morning Shower"
                assert len(presets.get_experiences()) == 1

    @pytest.mark.asyncio
    async def test_turn_on_outlet(
        self,
        config: KohlerConfig,
        mock_token_response: dict,
        mock_customer_response: dict,
        mock_command_response: dict,
    ) -> None:
        """Test turn_on_outlet."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.get(
                f"{API_BASE}/devices/api/v1/device-management/customer-device/customer-123",
                payload=mock_customer_response,
            )
            m.post(
                f"{API_BASE}/platform/api/v1/commands/gcs/solowritesystem",
                payload=mock_command_response,
            )

            async with KohlerAnthemClient(config) as client:
                # Need to call get_customer first to set customer_id
                await client.get_customer("customer-123")

                response = await client.turn_on_outlet(
                    "gcs-device-1",
                    Outlet.SHOWERHEAD,
                    temperature_celsius=38.0,
                    flow_percent=100,
                )

                assert response.correlation_id == "cmd-123"

    @pytest.mark.asyncio
    async def test_turn_off(
        self,
        config: KohlerConfig,
        mock_token_response: dict,
        mock_customer_response: dict,
        mock_command_response: dict,
    ) -> None:
        """Test turn_off."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.get(
                f"{API_BASE}/devices/api/v1/device-management/customer-device/customer-123",
                payload=mock_customer_response,
            )
            m.post(
                f"{API_BASE}/platform/api/v1/commands/gcs/solowritesystem",
                payload=mock_command_response,
            )

            async with KohlerAnthemClient(config) as client:
                await client.get_customer("customer-123")
                response = await client.turn_off("gcs-device-1")

                assert response.correlation_id == "cmd-123"

    @pytest.mark.asyncio
    async def test_start_preset(
        self,
        config: KohlerConfig,
        mock_token_response: dict,
        mock_command_response: dict,
    ) -> None:
        """Test start_preset."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.post(
                f"{API_BASE}/platform/api/v1/commands/gcs/controlpresetorexperience",
                payload=mock_command_response,
            )

            async with KohlerAnthemClient(config) as client:
                response = await client.start_preset("gcs-device-1", preset_id=1)

                assert response.correlation_id == "cmd-123"

    @pytest.mark.asyncio
    async def test_start_warmup(
        self,
        config: KohlerConfig,
        mock_token_response: dict,
        mock_command_response: dict,
    ) -> None:
        """Test start_warmup."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.post(
                f"{API_BASE}/platform/api/v1/commands/gcs/warmup",
                payload=mock_command_response,
            )

            async with KohlerAnthemClient(config) as client:
                response = await client.start_warmup("gcs-device-1")

                assert response.correlation_id == "cmd-123"

    @pytest.mark.asyncio
    async def test_api_error_404(
        self, config: KohlerConfig, mock_token_response: dict
    ) -> None:
        """Test 404 raises DeviceNotFoundError."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.get(
                f"{API_BASE}/devices/api/v1/device-management/gcs-state/gcsadvancestate/nonexistent",
                status=404,
                payload={"error": "Not found"},
            )

            async with KohlerAnthemClient(config) as client:
                with pytest.raises(DeviceNotFoundError) as exc_info:
                    await client.get_device_state("nonexistent")

                assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_api_error_500(
        self, config: KohlerConfig, mock_token_response: dict
    ) -> None:
        """Test 500 raises ApiError."""
        with aioresponses() as m:
            m.post(config.token_url, payload=mock_token_response)
            m.get(
                f"{API_BASE}/devices/api/v1/device-management/gcs-state/gcsadvancestate/device-1",
                status=500,
                payload={"error": "Internal server error"},
            )

            async with KohlerAnthemClient(config) as client:
                with pytest.raises(ApiError) as exc_info:
                    await client.get_device_state("device-1")

                assert exc_info.value.status_code == 500
