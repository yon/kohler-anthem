"""Tests for valve encoding/decoding.

These tests document the valve hex protocol discovered through API traffic analysis.
The valve protocol uses 4-byte hex strings: [prefix][temperature][flow][mode]
"""

import pytest

from kohler_anthem.models.enums import Outlet, ValveMode, ValvePrefix
from kohler_anthem.valve import (
    create_off_command,
    create_outlet_command,
    create_stop_command,
    decode_valve_command,
    encode_valve_command,
    outlet_to_mode,
)


class TestTemperatureEncoding:
    """Temperature encoding formula: temp_byte = (celsius - 25.6) * 10

    This was discovered by capturing traffic from the Kohler app.
    The offset of 25.6°C appears to be the minimum representable temperature.
    """

    def test_100f_encodes_to_0x79(self):
        """100°F (37.78°C) encodes to 0x79 (121 decimal).

        Formula: (37.78 - 25.6) * 10 = 121.8 ≈ 122 = 0x7A
        Note: Due to rounding, 37.7°C gives exactly 0x79.
        """
        result = encode_valve_command(
            temperature_celsius=37.7,  # ~100°F
            flow_percent=50,
            mode=ValveMode.SHOWER,
        )
        # Bytes: prefix=01, temp=79, flow=64, mode=01
        assert result[2:4] == "79", f"Expected temp byte 79, got {result[2:4]}"

    def test_minimum_temperature_15c(self):
        """Minimum supported temperature is 15°C (~59°F)."""
        result = encode_valve_command(
            temperature_celsius=15.0,
            flow_percent=50,
            mode=ValveMode.SHOWER,
        )
        # (15.0 - 25.6) * 10 = -106 -> clamped to 0
        assert result[2:4] == "00"

    def test_maximum_temperature_49c(self):
        """Maximum supported temperature is 49°C (~120°F)."""
        result = encode_valve_command(
            temperature_celsius=49.0,
            flow_percent=50,
            mode=ValveMode.SHOWER,
        )
        # (49.0 - 25.6) * 10 = 234 = 0xEA
        assert result[2:4] == "EA"

    def test_temperature_out_of_range_low(self):
        """Temperature below 15°C raises ValueError."""
        with pytest.raises(ValueError, match="Temperature must be 15-49"):
            encode_valve_command(
                temperature_celsius=14.0,
                flow_percent=50,
                mode=ValveMode.SHOWER,
            )

    def test_temperature_out_of_range_high(self):
        """Temperature above 49°C raises ValueError."""
        with pytest.raises(ValueError, match="Temperature must be 15-49"):
            encode_valve_command(
                temperature_celsius=50.0,
                flow_percent=50,
                mode=ValveMode.SHOWER,
            )

    def test_decode_temperature_100f(self):
        """Verify decoding 0x79 back to ~37.7°C."""
        result = decode_valve_command("01796401")
        # 121 / 10 + 25.6 = 37.7
        assert result["temperature_celsius"] == pytest.approx(37.7, abs=0.1)


class TestFlowEncoding:
    """Flow encoding: API uses 0-200 scale, we convert from 0-100%.

    flow_byte = flow_percent * 2
    """

    def test_0_percent_flow(self):
        """0% flow encodes to 0x00."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=0,
            mode=ValveMode.SHOWER,
        )
        assert result[4:6] == "00"

    def test_50_percent_flow(self):
        """50% flow encodes to 0x64 (100 decimal)."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=50,
            mode=ValveMode.SHOWER,
        )
        assert result[4:6] == "64"

    def test_100_percent_flow(self):
        """100% flow encodes to 0xC8 (200 decimal)."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=100,
            mode=ValveMode.SHOWER,
        )
        assert result[4:6] == "C8"

    def test_flow_out_of_range(self):
        """Flow outside 0-100% raises ValueError."""
        with pytest.raises(ValueError, match="Flow must be 0-100"):
            encode_valve_command(
                temperature_celsius=38.0,
                flow_percent=101,
                mode=ValveMode.SHOWER,
            )

    def test_decode_50_percent_flow(self):
        """Verify decoding 0x64 back to 50%."""
        result = decode_valve_command("017C6401")
        assert result["flow_percent"] == 50


class TestValvePrefix:
    """Valve prefix identifies which valve in multi-zone systems.

    Primary valve: 0x01
    Secondary valves: 0x11, 0x21, 0x31, 0x41, 0x51, 0x61, 0x71
    """

    def test_primary_valve_prefix(self):
        """Primary valve uses prefix 0x01."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=50,
            mode=ValveMode.SHOWER,
            prefix=ValvePrefix.PRIMARY,
        )
        assert result[0:2] == "01"

    def test_secondary_valve_1_prefix(self):
        """Secondary valve 1 uses prefix 0x11."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=50,
            mode=ValveMode.SHOWER,
            prefix=ValvePrefix.SECONDARY_1,
        )
        assert result[0:2] == "11"

    def test_decode_prefix(self):
        """Verify prefix is decoded correctly."""
        result = decode_valve_command("117C6401")
        assert result["prefix"] == ValvePrefix.SECONDARY_1


class TestValveMode:
    """Valve mode indicates outlet state and operation.

    0x00 = OFF (all outlets off, session ends)
    0x01 = SHOWER (showerhead active)
    0x02 = TUB_FILLER (tub filler active)
    0x03 = TUB_HANDHELD (tub + handheld combo)
    0x40 = STOP (pause - water stops but session continues)
    """

    def test_shower_mode(self):
        """Shower mode encodes to 0x01."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=50,
            mode=ValveMode.SHOWER,
        )
        assert result[6:8] == "01"

    def test_tub_filler_mode(self):
        """Tub filler mode encodes to 0x02."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=50,
            mode=ValveMode.TUB_FILLER,
        )
        assert result[6:8] == "02"

    def test_stop_mode(self):
        """Stop/pause mode encodes to 0x40."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=50,
            mode=ValveMode.STOP,
        )
        assert result[6:8] == "40"

    def test_decode_mode(self):
        """Verify mode is decoded correctly."""
        result = decode_valve_command("017C6402")
        assert result["mode"] == ValveMode.TUB_FILLER


class TestCapturedCommands:
    """Test encoding/decoding of actual captured commands from traffic analysis."""

    @pytest.mark.parametrize("hex_cmd,expected", [
        # From captured traffic: 100°F, 100% flow, shower ON
        ("0179C801", {
            "prefix": ValvePrefix.PRIMARY,
            "temperature_celsius": 37.7,  # 100°F
            "flow_percent": 100,
            "mode": ValveMode.SHOWER,
        }),
        # 100°F, 50% flow, shower ON
        ("01796401", {
            "prefix": ValvePrefix.PRIMARY,
            "temperature_celsius": 37.7,
            "flow_percent": 50,
            "mode": ValveMode.SHOWER,
        }),
        # 100°F, 100% flow, STOP (pause)
        ("0179C840", {
            "prefix": ValvePrefix.PRIMARY,
            "temperature_celsius": 37.7,
            "flow_percent": 100,
            "mode": ValveMode.STOP,
        }),
    ])
    def test_decode_captured_commands(self, hex_cmd, expected):
        """Verify captured commands decode to expected values."""
        result = decode_valve_command(hex_cmd)
        assert result["prefix"] == expected["prefix"]
        assert result["temperature_celsius"] == pytest.approx(
            expected["temperature_celsius"], abs=0.1
        )
        assert result["flow_percent"] == expected["flow_percent"]
        assert result["mode"] == expected["mode"]


class TestHelperFunctions:
    """Test helper functions for common operations."""

    def test_create_off_command(self):
        """OFF command is all zeros."""
        assert create_off_command() == "00000000"

    def test_create_stop_command(self):
        """STOP command preserves temp/flow with mode 0x40."""
        result = create_stop_command(
            temperature_celsius=38.0,
            flow_percent=50,
        )
        assert result[6:8] == "40"  # Stop mode

    def test_create_outlet_command_showerhead(self):
        """Create command for showerhead outlet."""
        result = create_outlet_command(
            Outlet.SHOWERHEAD,
            temperature_celsius=38.0,
            flow_percent=50,
        )
        assert result[6:8] == "01"  # Shower mode

    def test_create_outlet_command_tub_filler(self):
        """Create command for tub filler outlet."""
        result = create_outlet_command(
            Outlet.TUB_FILLER,
            temperature_celsius=38.0,
            flow_percent=50,
        )
        assert result[6:8] == "02"  # Tub filler mode

    def test_outlet_to_mode_mapping(self):
        """Verify outlet to mode mapping."""
        assert outlet_to_mode(Outlet.SHOWERHEAD) == ValveMode.SHOWER
        assert outlet_to_mode(Outlet.TUB_FILLER) == ValveMode.TUB_FILLER
        assert outlet_to_mode(Outlet.HANDSHOWER) == ValveMode.SHOWER
        assert outlet_to_mode(Outlet.TUB_HANDHELD) == ValveMode.TUB_HANDHELD


class TestRoundTrip:
    """Test that encoding and decoding are inverse operations."""

    @pytest.mark.parametrize("temp_c,flow_pct,mode,prefix", [
        (38.0, 50, ValveMode.SHOWER, ValvePrefix.PRIMARY),
        (37.7, 100, ValveMode.TUB_FILLER, ValvePrefix.PRIMARY),
        (45.0, 75, ValveMode.STOP, ValvePrefix.SECONDARY_1),
        (30.0, 25, ValveMode.SHOWER, ValvePrefix.PRIMARY),  # Min ~25.6°C
    ])
    def test_encode_decode_roundtrip(self, temp_c, flow_pct, mode, prefix):
        """Encoding then decoding should return original values."""
        encoded = encode_valve_command(
            temperature_celsius=temp_c,
            flow_percent=flow_pct,
            mode=mode,
            prefix=prefix,
        )
        decoded = decode_valve_command(encoded)

        assert decoded["prefix"] == prefix
        assert decoded["temperature_celsius"] == pytest.approx(temp_c, abs=0.1)
        assert decoded["flow_percent"] == flow_pct
        assert decoded["mode"] == mode
