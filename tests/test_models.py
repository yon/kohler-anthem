"""Tests for Pydantic models."""

import pytest

from kohler_anthem import (
    ConnectionState,
    Customer,
    Device,
    DeviceState,
    Home,
    OutletDetail,
    OutletState,
    Preset,
    PresetResponse,
    SystemState,
    ValveState,
    WarmUpStatus,
)


class TestCustomerModels:
    """Test customer/device models."""

    def test_device_from_response(self) -> None:
        """Test Device parsing."""
        data = {
            "deviceId": "dev-123",
            "logicalName": "Master Shower",
            "sku": "GCS",
            "serialNumber": "SN12345",
            "isActive": True,
        }
        device = Device.from_response(data)
        assert device.device_id == "dev-123"
        assert device.logical_name == "Master Shower"
        assert device.sku == "GCS"
        assert device.serial_number == "SN12345"
        assert device.is_active is True

    def test_device_with_extra_fields(self) -> None:
        """Test Device ignores unknown fields (closed API pattern)."""
        data = {
            "deviceId": "dev-123",
            "logicalName": "Shower",
            "unknownField": "ignored",
            "anotherNew": 123,
        }
        device = Device.from_response(data)
        assert device.device_id == "dev-123"
        # Should not raise, unknown fields ignored

    def test_home_with_devices(self) -> None:
        """Test Home parsing with nested devices."""
        data = {
            "homeId": "home-1",
            "homeName": "My House",
            "devices": [
                {"deviceId": "dev-1", "logicalName": "Shower 1"},
                {"deviceId": "dev-2", "logicalName": "Shower 2"},
            ],
        }
        home = Home.from_response(data)
        assert home.home_id == "home-1"
        assert len(home.devices) == 2
        assert home.devices[0].device_id == "dev-1"

    def test_customer_get_all_devices(self) -> None:
        """Test Customer.get_all_devices flattens homes."""
        data = {
            "id": "cust-1",
            "tenantId": "tenant-1",
            "customerHome": [
                {
                    "homeId": "home-1",
                    "homeName": "House 1",
                    "devices": [{"deviceId": "dev-1", "logicalName": "S1"}],
                },
                {
                    "homeId": "home-2",
                    "homeName": "House 2",
                    "devices": [
                        {"deviceId": "dev-2", "logicalName": "S2"},
                        {"deviceId": "dev-3", "logicalName": "S3"},
                    ],
                },
            ],
        }
        customer = Customer.from_response(data)
        devices = customer.get_all_devices()
        assert len(devices) == 3
        assert {d.device_id for d in devices} == {"dev-1", "dev-2", "dev-3"}

    def test_customer_get_device(self) -> None:
        """Test Customer.get_device lookup."""
        data = {
            "id": "cust-1",
            "tenantId": "tenant-1",
            "customerHome": [
                {
                    "homeId": "home-1",
                    "homeName": "House",
                    "devices": [{"deviceId": "dev-123", "logicalName": "Shower"}],
                },
            ],
        }
        customer = Customer.from_response(data)
        assert customer.get_device("dev-123") is not None
        assert customer.get_device("nonexistent") is None


class TestDeviceStateModels:
    """Test device state models."""

    def test_valve_state_string_booleans(self) -> None:
        """Test ValveState parses string booleans."""
        data = {
            "valveIndex": "1",
            "atFlow": "1",
            "atTemp": "0",
            "out1": "true",
            "out2": "false",
            "out3": "0",
        }
        valve = ValveState.from_response(data)
        assert valve.at_flow is True
        assert valve.at_temp is False
        assert valve.out1 is True
        assert valve.out2 is False
        assert valve.out3 is False

    def test_valve_state_is_active(self) -> None:
        """Test ValveState.is_active property."""
        data = {"valveIndex": "1", "out1": "1", "out2": "0", "out3": "0"}
        valve = ValveState.from_response(data)
        assert valve.is_active is True

        data = {"valveIndex": "1", "out1": "0", "out2": "0", "out3": "0"}
        valve = ValveState.from_response(data)
        assert valve.is_active is False

    def test_outlet_state_string_numbers(self) -> None:
        """Test OutletState parses string numbers."""
        data = {
            "outletIndex": "1",
            "outletTemp": "38.5",
            "outletFlow": "75",
        }
        outlet = OutletState.from_response(data)
        assert outlet.outlet_temp == 38.5
        assert outlet.outlet_flow == 75.0

    def test_device_state_full(self) -> None:
        """Test full DeviceState parsing."""
        data = {
            "id": "state-1",
            "deviceId": "dev-123",
            "connectionState": "Connected",
            "state": {
                "currentSystemState": "showerInProgress",
                "presetOrExperienceId": "1",
                "warmUpState": {"warmUp": "warmUpEnabled", "state": "warmUpNotInProgress"},
                "valveState": [
                    {"valveIndex": "1", "out1": "1", "out2": "0", "out3": "0"}
                ],
            },
        }
        state = DeviceState.from_response(data)
        assert state.is_connected is True
        assert state.connection_state == ConnectionState.CONNECTED
        assert state.is_running is True
        assert state.state.current_system_state == SystemState.SHOWER
        assert state.state.active_preset_id == 1

    def test_device_state_is_warming_up(self) -> None:
        """Test DeviceState.is_warming_up property."""
        data = {
            "deviceId": "dev-1",
            "state": {
                "warmUpState": {"state": "warmUpInProgress"},
            },
        }
        state = DeviceState.from_response(data)
        assert state.is_warming_up is True


class TestPresetModels:
    """Test preset models."""

    def test_outlet_detail_string_parsing(self) -> None:
        """Test OutletDetail parses string values."""
        data = {
            "outletIndex": "1",
            "temperature": "38.5",
            "flow": "75",
            "value": "1",
        }
        outlet = OutletDetail.from_response(data)
        assert outlet.temperature == 38.5
        assert outlet.flow == 75
        assert outlet.value is True

    def test_preset_basic(self) -> None:
        """Test Preset parsing."""
        data = {
            "presetId": "1",
            "title": "Morning Shower",
            "isExperience": "false",
            "state": "off",
            "time": "1800",
        }
        preset = Preset.from_response(data)
        assert preset.id == 1
        assert preset.title == "Morning Shower"
        assert preset.is_experience is False
        assert preset.duration_minutes == 30

    def test_preset_response_get_preset(self) -> None:
        """Test PresetResponse.get_preset lookup."""
        data = {
            "deviceId": "dev-1",
            "presets": [
                {"presetId": "1", "title": "Preset 1"},
                {"presetId": "2", "title": "Preset 2"},
            ],
        }
        response = PresetResponse.from_response(data)
        assert response.get_preset(1) is not None
        assert response.get_preset(1).title == "Preset 1"
        assert response.get_preset(99) is None

    def test_preset_response_filter_experiences(self) -> None:
        """Test PresetResponse filtering presets vs experiences."""
        data = {
            "deviceId": "dev-1",
            "presets": [
                {"presetId": "1", "title": "Preset", "isExperience": "false"},
                {"presetId": "2", "title": "Experience", "isExperience": "true"},
            ],
        }
        response = PresetResponse.from_response(data)
        assert len(response.get_presets_only()) == 1
        assert len(response.get_experiences()) == 1
