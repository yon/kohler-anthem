"""Tests for API response models.

These tests document the structure of API responses and parsing behavior
discovered through traffic capture and testing.
"""

import pytest

from kohler_anthem.models import (
    ConnectionState,
    DeviceState,
    DeviceStateData,
    SystemState,
    ValveControlModel,
    ValveSettings,
    ValveState,
    WarmUpStatus,
)


class TestValveState:
    """Document ValveState parsing from API responses."""

    def test_parse_outlet_flags(self):
        """API returns out1/out2/out3 as "0"/"1" strings."""
        data = {
            "valveIndex": "Valve1",
            "out1": "1",
            "out2": "0",
            "out3": "0",
            "atFlow": "1",
            "atTemp": "1",
            "flowSetpoint": "25",  # API uses 0-50 scale
            "temperatureSetpoint": "37.7",
            "errorFlag": "0",
            "errorCode": "0",
            "pauseFlag": "0",
            "outlets": [],
        }
        valve = ValveState.model_validate(data)

        assert valve.out1 is True
        assert valve.out2 is False
        assert valve.out3 is False

    def test_parse_flow_setpoint_converts_scale(self):
        """API returns flowSetpoint on 0-50 scale, we convert to 0-100%.

        Example: API value 25 = 50%, API value 50 = 100%
        """
        data = {
            "valveIndex": "Valve1",
            "out1": "0",
            "out2": "0",
            "out3": "0",
            "atFlow": "0",
            "atTemp": "0",
            "flowSetpoint": "25",  # Should become 50%
            "temperatureSetpoint": "38.0",
            "errorFlag": "0",
            "errorCode": "0",
            "pauseFlag": "0",
            "outlets": [],
        }
        valve = ValveState.model_validate(data)
        assert valve.flow_setpoint == 50

    def test_parse_temperature_setpoint(self):
        """temperatureSetpoint is in Celsius as a string."""
        data = {
            "valveIndex": "Valve1",
            "out1": "0",
            "out2": "0",
            "out3": "0",
            "atFlow": "0",
            "atTemp": "0",
            "flowSetpoint": "50",
            "temperatureSetpoint": "37.7",  # 100°F
            "errorFlag": "0",
            "errorCode": "0",
            "pauseFlag": "0",
            "outlets": [],
        }
        valve = ValveState.model_validate(data)
        assert valve.temperature_setpoint == pytest.approx(37.7, abs=0.01)

    def test_is_active_property(self):
        """is_active returns True if any outlet is on."""
        # With out1 active
        valve = ValveState(
            valve_index="Valve1",
            out1=True,
            out2=False,
            out3=False,
        )
        assert valve.is_active is True

        # With no outlets active
        valve = ValveState(
            valve_index="Valve1",
            out1=False,
            out2=False,
            out3=False,
        )
        assert valve.is_active is False


class TestDeviceStateData:
    """Document DeviceStateData (inner state object) parsing."""

    def test_current_system_state_enum(self):
        """currentSystemState maps to SystemState enum."""
        data = {
            "currentSystemState": "showerInProgress",
            "warmUpState": {"warmUp": "warmUpDisabled", "state": "warmUpNotInProgress"},
            "presetOrExperienceId": "0",
            "totalVolume": "100",
            "totalFlow": "5.5",
            "ready": "true",
            "valveState": [],
            "ioTActive": "Active",
        }
        state = DeviceStateData.model_validate(data)
        assert state.current_system_state == SystemState.SHOWER

    def test_is_running_property(self):
        """is_running returns True when system state is SHOWER."""
        state = DeviceStateData(current_system_state=SystemState.SHOWER)
        assert state.is_running is True

        state = DeviceStateData(current_system_state=SystemState.NORMAL)
        assert state.is_running is False

    def test_active_preset_id(self):
        """active_preset_id returns int or None."""
        # With active preset
        state = DeviceStateData(preset_or_experience_id="3")
        assert state.active_preset_id == 3

        # No preset
        state = DeviceStateData(preset_or_experience_id="0")
        assert state.active_preset_id is None


class TestDeviceState:
    """Document full DeviceState response parsing."""

    def test_connection_state_enum(self):
        """connectionState maps to ConnectionState enum."""
        data = {
            "id": "device123",
            "deviceId": "device123",
            "sku": "GCS",
            "tenantId": "customer456",
            "connectionState": "Connected",
            "lastConnected": 1704067200000,
            "state": {
                "currentSystemState": "Normal",
                "warmUpState": {"warmUp": "warmUpDisabled", "state": "NotInProgress"},
                "presetOrExperienceId": "0",
                "totalVolume": "0",
                "totalFlow": "0",
                "ready": "true",
                "valveState": [],
                "ioTActive": "Inactive",
            },
            "setting": {
                "valveSettings": [],
                "flowControl": "Disabled",
            },
        }
        device = DeviceState.model_validate(data)
        assert device.connection_state == ConnectionState.CONNECTED
        assert device.is_connected is True

    def test_disconnected_state(self):
        """Verify disconnected state is parsed correctly."""
        data = {
            "id": "device123",
            "deviceId": "device123",
            "connectionState": "Disconnected",
            "state": {},
            "setting": {},
        }
        device = DeviceState.model_validate(data)
        assert device.connection_state == ConnectionState.DISCONNECTED
        assert device.is_connected is False


class TestValveSettings:
    """Document valve settings/configuration parsing."""

    def test_outlet_configurations(self):
        """outletConfigurations contains per-outlet limits."""
        data = {
            "valve": "Valve1",
            "noOfOutlets": "2",
            "valveFirmwareType": "1",
            "valveFirmwareVersion": "100",
            "outletConfigurations": [
                {
                    "outLetType": "1",
                    "outLetId": "1",
                    "maximumOutletTemperature": "48.8",
                    "minimumOutletTemperature": "15.0",
                    "defaultOutletTemperature": "37.7",
                    "maximumFlowrate": "100",
                    "minimumFlowrate": "0",
                    "defaultFlowrate": "50",
                    "maximumRuntime": "1800",
                },
            ],
        }
        settings = ValveSettings.model_validate(data)
        assert settings.num_outlets == 2
        assert len(settings.outlet_configurations) == 1
        assert settings.outlet_configurations[0].max_temperature == pytest.approx(48.8)
        assert settings.outlet_configurations[0].default_temperature == pytest.approx(37.7)


class TestValveControlModel:
    """Document valve control command model."""

    def test_primary_valve_command(self):
        """Valve control sends hex commands per valve."""
        control = ValveControlModel(
            primary_valve1="0179C801",  # Primary valve 1 ON
        )
        dumped = control.model_dump(by_alias=True)

        assert dumped["primaryValve1"] == "0179C801"

    def test_all_valves_off(self):
        """All zeros turns everything off."""
        control = ValveControlModel(
            primary_valve1="00000000",
            secondary_valve1="00000000",
            secondary_valve2="00000000",
        )
        for field in ["primaryValve1", "secondaryValve1", "secondaryValve2"]:
            assert control.model_dump(by_alias=True)[field] == "00000000"


class TestWarmUpStatus:
    """Document warmup status values."""

    def test_warmup_states(self):
        """Warmup can be in progress or not in progress."""
        assert WarmUpStatus.IN_PROGRESS.value == "warmUpInProgress"
        assert WarmUpStatus.NOT_IN_PROGRESS.value == "warmUpNotInProgress"


class TestSystemState:
    """Document system state values."""

    def test_system_states(self):
        """System can be Normal (idle) or Shower (running)."""
        assert SystemState.NORMAL.value == "normalOperation"
        assert SystemState.SHOWER.value == "showerInProgress"
