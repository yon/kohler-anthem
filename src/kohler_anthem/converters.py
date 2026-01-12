"""Unit conversion helpers for temperature and flow."""


def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return (celsius * 9 / 5) + 32


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (fahrenheit - 32) * 5 / 9


def gallons_to_liters(gallons: float) -> float:
    """Convert US gallons to liters."""
    return gallons * 3.78541


def liters_to_gallons(liters: float) -> float:
    """Convert liters to US gallons."""
    return liters / 3.78541
