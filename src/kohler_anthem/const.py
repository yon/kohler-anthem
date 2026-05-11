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

# APIM mTLS service-account auth (the path Konnect uses to authorize
# /commands/* writes). The library presents `app_certificate.p12` (bundled
# in _data/) over mTLS to APIM, which issues a service-account JWT for
# admin.user@kohler.com. That JWT is what Kohler's /commands/* endpoints
# accept; the ROPC user JWT is rejected with 403.
APIM_HOST = "az-amer-prod-kohlerkonnect-apim.azure-api.net"
APIM_TOKEN_URL = f"https://{APIM_HOST}/token/api/v1/token/"
# Subscription key required by the /token/* endpoint family. Distinct from
# the API subscription key the rest of the library uses (which goes through
# api-kohler-us.kohler.io). Constant across all Konnect installs — embedded
# in every public APK.
APIM_TOKEN_SUBSCRIPTION_KEY = "ca2f50cbc01845e9af356f866b16c9f1"
# The bundled client cert's PKCS12 password. Recovered via Frida hook on
# KeyStore.load(); same constant in every public APK.
APIM_CLIENT_CERT_PASSWORD = "d6jaqQ1nJxFAuXs"
# Endpoint prefix(es) that require the mTLS + service-account JWT path.
# Reads (/devices/, /platform/api/v1/mobile/settings) still work with the
# ROPC user JWT today; only /commands/* needs the new path.
APIM_WRITE_ENDPOINT_PREFIX = "/platform/api/v1/commands/"
