"""Enums for Kohler Anthem API."""

from enum import Enum, IntEnum


class SystemState(str, Enum):
    """Device system state."""

    NORMAL = "normalOperation"
    SHOWER = "showerInProgress"


class WarmUpStatus(str, Enum):
    """Warmup status."""

    NOT_IN_PROGRESS = "warmUpNotInProgress"
    IN_PROGRESS = "warmUpInProgress"


class ConnectionState(str, Enum):
    """Device connection state."""

    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"


class ValvePrefix(IntEnum):
    """Valve identifier prefix byte."""

    PRIMARY = 0x01
    SECONDARY_1 = 0x11
    SECONDARY_2 = 0x21
    SECONDARY_3 = 0x31
    SECONDARY_4 = 0x41
    SECONDARY_5 = 0x51
    SECONDARY_6 = 0x61
    SECONDARY_7 = 0x71


class ValveMode(IntEnum):
    """Valve mode/outlet state byte."""

    OFF = 0x00
    SHOWER = 0x01
    TUB_FILLER = 0x02
    TUB_HANDHELD = 0x03
    STOP = 0x40


class OutletType(IntEnum):
    """Outlet type codes from device configuration."""

    HANDSHOWER = 1
    SHOWERHEAD = 11
    TUB_FILLER = 21


class Outlet(IntEnum):
    """Logical outlet identifiers for convenience methods."""

    SHOWERHEAD = 1
    TUB_FILLER = 2
    HANDSHOWER = 3
    TUB_HANDHELD = 4


class TemperatureUnit(str, Enum):
    """Temperature unit preference."""

    CELSIUS = "Celsius"
    FAHRENHEIT = "Fahrenheit"


class FlowUnit(str, Enum):
    """Flow unit preference."""

    GALLONS = "Gallons"
    LITERS = "Liters"
    STANDARD = "Standard"
