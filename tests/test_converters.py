"""Tests for unit converters."""

import pytest

from kohler_anthem import (
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    gallons_to_liters,
    liters_to_gallons,
)


class TestTemperatureConversion:
    """Test temperature conversion functions."""

    def test_celsius_to_fahrenheit_freezing(self) -> None:
        """Test 0°C = 32°F."""
        assert celsius_to_fahrenheit(0) == 32.0

    def test_celsius_to_fahrenheit_boiling(self) -> None:
        """Test 100°C = 212°F."""
        assert celsius_to_fahrenheit(100) == 212.0

    def test_celsius_to_fahrenheit_body_temp(self) -> None:
        """Test 37°C ≈ 98.6°F."""
        result = celsius_to_fahrenheit(37)
        assert abs(result - 98.6) < 0.1

    def test_fahrenheit_to_celsius_freezing(self) -> None:
        """Test 32°F = 0°C."""
        assert fahrenheit_to_celsius(32) == 0.0

    def test_fahrenheit_to_celsius_boiling(self) -> None:
        """Test 212°F = 100°C."""
        assert fahrenheit_to_celsius(212) == 100.0

    def test_round_trip_celsius(self) -> None:
        """Test round trip conversion preserves value."""
        original = 38.5
        converted = fahrenheit_to_celsius(celsius_to_fahrenheit(original))
        assert abs(converted - original) < 0.01


class TestVolumeConversion:
    """Test volume conversion functions."""

    def test_gallons_to_liters(self) -> None:
        """Test gallon to liter conversion."""
        result = gallons_to_liters(1)
        assert abs(result - 3.78541) < 0.001

    def test_liters_to_gallons(self) -> None:
        """Test liter to gallon conversion."""
        result = liters_to_gallons(3.78541)
        assert abs(result - 1.0) < 0.001

    def test_round_trip_gallons(self) -> None:
        """Test round trip conversion preserves value."""
        original = 5.0
        converted = liters_to_gallons(gallons_to_liters(original))
        assert abs(converted - original) < 0.01
