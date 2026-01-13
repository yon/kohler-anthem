"""Constants for Kohler Anthem API.

All endpoints and infrastructure values centralized here.
Secrets and credentials are passed via KohlerConfig.
"""

# API Base URL
API_BASE = "https://api-kohler-us.kohler.io"

# API Endpoints (relative to API_BASE)
# Format strings use {customer_id}, {device_id} as placeholders
ENDPOINTS = {
    "customer_devices": "/devices/api/v1/device-management/customer-device/{customer_id}",
    "device_state": "/devices/api/v1/device-management/gcs-state/gcsadvancestate/{device_id}",
    "mobile_settings": "/platform/api/v1/mobile/settings",
    "preset_control": "/platform/api/v1/commands/gcs/controlpresetorexperience",
    "presets": "/devices/api/v1/device-management/gcs-preset/{device_id}",
    "valve_control": "/platform/api/v1/commands/gcs/solowritesystem",
    "warmup": "/platform/api/v1/commands/gcs/warmup",
}

# Device SKU
DEFAULT_SKU = "GCS"

# Temperature limits (Celsius)
TEMP_MIN_CELSIUS = 15.0
TEMP_MAX_CELSIUS = 48.8
TEMP_DEFAULT_CELSIUS = 37.7

# Temperature encoding
TEMP_BYTE_MAX = 232
TEMP_STEP = (TEMP_MAX_CELSIUS - TEMP_MIN_CELSIUS) / TEMP_BYTE_MAX  # ~0.146

# Flow limits
FLOW_MIN_PERCENT = 0
FLOW_MAX_PERCENT = 100
FLOW_DEFAULT_PERCENT = 100
FLOW_BYTE_MAX = 200

# Request timeout (seconds)
REQUEST_TIMEOUT = 30
