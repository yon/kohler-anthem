"""Valve hex encoding/decoding for Kohler Anthem.

The valve protocol uses 4-byte hex strings per valve:
    [prefix][temperature][flow][mode]

Where:
    - prefix: Valve identifier (0x01=primary, 0x11-0x71=secondary 1-7)
    - temperature: Celsius value as byte (e.g., 38°C = 0x26)
    - flow: Flow percentage 0-100 as byte
    - mode: Outlet state (0x00=off, 0x01=shower, 0x02=tub, 0x03=tub+handheld, 0x40=stop)
"""

from .models.enums import Outlet, ValveMode, ValvePrefix


def encode_valve_command(
    *,
    temperature_celsius: float,
    flow_percent: int,
    mode: ValveMode,
    prefix: ValvePrefix = ValvePrefix.PRIMARY,
) -> str:
    """Encode a valve command to hex string.

    Args:
        temperature_celsius: Target temperature in Celsius (15-49)
        flow_percent: Flow rate percentage (0-100)
        mode: Valve mode/outlet state
        prefix: Valve identifier prefix

    Returns:
        8-character hex string (4 bytes)

    Raises:
        ValueError: If parameters are out of valid range
    """
    if not 15 <= temperature_celsius <= 49:
        raise ValueError(f"Temperature must be 15-49°C, got {temperature_celsius}")
    if not 0 <= flow_percent <= 100:
        raise ValueError(f"Flow must be 0-100%, got {flow_percent}")

    temp_byte = int(temperature_celsius)
    flow_byte = flow_percent
    mode_byte = int(mode)
    prefix_byte = int(prefix)

    return f"{prefix_byte:02X}{temp_byte:02X}{flow_byte:02X}{mode_byte:02X}"


def decode_valve_command(hex_string: str) -> dict:
    """Decode a valve hex string to its components.

    Args:
        hex_string: 8-character hex string

    Returns:
        Dictionary with prefix, temperature_celsius, flow_percent, mode

    Raises:
        ValueError: If hex string is invalid
    """
    if len(hex_string) != 8:
        raise ValueError(f"Valve hex must be 8 characters, got {len(hex_string)}")

    try:
        prefix_byte = int(hex_string[0:2], 16)
        temp_byte = int(hex_string[2:4], 16)
        flow_byte = int(hex_string[4:6], 16)
        mode_byte = int(hex_string[6:8], 16)
    except ValueError as e:
        raise ValueError(f"Invalid hex string: {hex_string}") from e

    # Try to match to known enums
    try:
        prefix = ValvePrefix(prefix_byte)
    except ValueError:
        prefix = prefix_byte  # type: ignore[assignment]

    try:
        mode = ValveMode(mode_byte)
    except ValueError:
        mode = mode_byte  # type: ignore[assignment]

    return {
        "prefix": prefix,
        "temperature_celsius": temp_byte,
        "flow_percent": flow_byte,
        "mode": mode,
    }


def is_valve_off(hex_string: str) -> bool:
    """Check if valve hex string represents OFF state.

    Args:
        hex_string: 8-character hex string

    Returns:
        True if valve is off (all zeros)
    """
    return hex_string == "00000000"


def create_off_command() -> str:
    """Create a valve OFF command.

    Returns:
        Hex string for turning valve off
    """
    return "00000000"


def create_stop_command(
    *,
    temperature_celsius: float = 38.0,
    flow_percent: int = 50,
    prefix: ValvePrefix = ValvePrefix.PRIMARY,
) -> str:
    """Create a STOP command (water stops but session continues).

    Args:
        temperature_celsius: Current temperature setting
        flow_percent: Current flow setting
        prefix: Valve identifier

    Returns:
        Hex string for stop command
    """
    return encode_valve_command(
        temperature_celsius=temperature_celsius,
        flow_percent=flow_percent,
        mode=ValveMode.STOP,
        prefix=prefix,
    )


def outlet_to_mode(outlet: Outlet) -> ValveMode:
    """Convert outlet identifier to valve mode.

    Args:
        outlet: Outlet identifier

    Returns:
        Corresponding valve mode
    """
    mapping = {
        Outlet.SHOWERHEAD: ValveMode.SHOWER,
        Outlet.TUB_FILLER: ValveMode.TUB_FILLER,
        Outlet.HANDSHOWER: ValveMode.SHOWER,  # Same as showerhead
        Outlet.TUB_HANDHELD: ValveMode.TUB_HANDHELD,
    }
    return mapping.get(outlet, ValveMode.SHOWER)


def create_outlet_command(
    outlet: Outlet,
    *,
    temperature_celsius: float = 38.0,
    flow_percent: int = 50,
    prefix: ValvePrefix = ValvePrefix.PRIMARY,
) -> str:
    """Create command to turn on a specific outlet.

    Args:
        outlet: Which outlet to turn on
        temperature_celsius: Target temperature in Celsius
        flow_percent: Flow rate percentage
        prefix: Valve identifier

    Returns:
        Hex string for outlet command
    """
    mode = outlet_to_mode(outlet)
    return encode_valve_command(
        temperature_celsius=temperature_celsius,
        flow_percent=flow_percent,
        mode=mode,
        prefix=prefix,
    )
