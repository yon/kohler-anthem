"""Tests for valve encoding/decoding."""

import pytest

from kohler_anthem import (
    Outlet,
    ValveMode,
    ValvePrefix,
    create_off_command,
    create_outlet_command,
    create_stop_command,
    decode_valve_command,
    encode_valve_command,
    is_valve_off,
    outlet_to_mode,
)


class TestEncodeValveCommand:
    """Test valve encoding."""

    def test_basic_encoding(self) -> None:
        """Test basic valve encoding."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=100,
            mode=ValveMode.SHOWER,
            prefix=ValvePrefix.PRIMARY,
        )
        assert result == "01266401"

    def test_tub_filler(self) -> None:
        """Test tub filler mode encoding."""
        result = encode_valve_command(
            temperature_celsius=40.0,
            flow_percent=50,
            mode=ValveMode.TUB_FILLER,
        )
        assert result == "01283202"

    def test_stop_mode(self) -> None:
        """Test stop mode encoding."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=100,
            mode=ValveMode.STOP,
        )
        assert result == "01266440"

    def test_off_mode(self) -> None:
        """Test off mode encoding."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=0,
            mode=ValveMode.OFF,
        )
        assert result == "01260000"

    def test_secondary_valve(self) -> None:
        """Test secondary valve prefix."""
        result = encode_valve_command(
            temperature_celsius=38.0,
            flow_percent=100,
            mode=ValveMode.SHOWER,
            prefix=ValvePrefix.SECONDARY_1,
        )
        assert result == "11266401"

    def test_temperature_out_of_range_low(self) -> None:
        """Test temperature below minimum."""
        with pytest.raises(ValueError, match="Temperature must be 15-49"):
            encode_valve_command(
                temperature_celsius=10.0,
                flow_percent=50,
                mode=ValveMode.SHOWER,
            )

    def test_temperature_out_of_range_high(self) -> None:
        """Test temperature above maximum."""
        with pytest.raises(ValueError, match="Temperature must be 15-49"):
            encode_valve_command(
                temperature_celsius=55.0,
                flow_percent=50,
                mode=ValveMode.SHOWER,
            )

    def test_flow_out_of_range(self) -> None:
        """Test flow above maximum."""
        with pytest.raises(ValueError, match="Flow must be 0-100"):
            encode_valve_command(
                temperature_celsius=38.0,
                flow_percent=150,
                mode=ValveMode.SHOWER,
            )


class TestDecodeValveCommand:
    """Test valve decoding."""

    def test_basic_decoding(self) -> None:
        """Test basic valve decoding."""
        result = decode_valve_command("01266401")
        assert result["prefix"] == ValvePrefix.PRIMARY
        assert result["temperature_celsius"] == 38
        assert result["flow_percent"] == 100
        assert result["mode"] == ValveMode.SHOWER

    def test_decode_tub_filler(self) -> None:
        """Test decoding tub filler command."""
        result = decode_valve_command("01283202")
        assert result["temperature_celsius"] == 40
        assert result["flow_percent"] == 50
        assert result["mode"] == ValveMode.TUB_FILLER

    def test_decode_off(self) -> None:
        """Test decoding off command."""
        result = decode_valve_command("00000000")
        assert result["flow_percent"] == 0
        assert result["mode"] == ValveMode.OFF

    def test_decode_invalid_length(self) -> None:
        """Test invalid hex string length."""
        with pytest.raises(ValueError, match="must be 8 characters"):
            decode_valve_command("0126")

    def test_decode_invalid_hex(self) -> None:
        """Test invalid hex characters."""
        with pytest.raises(ValueError, match="Invalid hex string"):
            decode_valve_command("GGGGGGGG")


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_valve_off_true(self) -> None:
        """Test is_valve_off returns True for off."""
        assert is_valve_off("00000000") is True

    def test_is_valve_off_false(self) -> None:
        """Test is_valve_off returns False for active."""
        assert is_valve_off("01266401") is False

    def test_create_off_command(self) -> None:
        """Test creating off command."""
        assert create_off_command() == "00000000"

    def test_create_stop_command(self) -> None:
        """Test creating stop command."""
        result = create_stop_command(temperature_celsius=38.0, flow_percent=100)
        assert result == "01266440"

    def test_outlet_to_mode_showerhead(self) -> None:
        """Test outlet to mode mapping for showerhead."""
        assert outlet_to_mode(Outlet.SHOWERHEAD) == ValveMode.SHOWER

    def test_outlet_to_mode_tub_filler(self) -> None:
        """Test outlet to mode mapping for tub filler."""
        assert outlet_to_mode(Outlet.TUB_FILLER) == ValveMode.TUB_FILLER

    def test_outlet_to_mode_handshower(self) -> None:
        """Test outlet to mode mapping for handshower."""
        assert outlet_to_mode(Outlet.HANDSHOWER) == ValveMode.SHOWER

    def test_create_outlet_command(self) -> None:
        """Test creating outlet command."""
        result = create_outlet_command(
            Outlet.SHOWERHEAD,
            temperature_celsius=38.0,
            flow_percent=100,
        )
        assert result == "01266401"
