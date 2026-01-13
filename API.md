# Kohler Anthem API Documentation

This document describes the Kohler Anthem cloud API discovered through traffic analysis of the mobile app.

## Authentication

Kohler uses Azure AD B2C with Resource Owner Password Credential (ROPC) flow.

### Token Endpoint

```
POST https://{tenant}.b2clogin.com/tfp/{tenant}.onmicrosoft.com/{policy}/oauth2/v2.0/token
```

Default values:
- Tenant: `konnectkohler`
- Policy: `B2C_1_ROPC_Auth`

### Request Body

```
grant_type=password
client_id={client_id}
username={email}
password={password}
scope=openid offline_access https://{tenant}.onmicrosoft.com/{api_resource}/apiaccess
```

### Response

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "id_token": "eyJ...",
  "expires_in": 3600
}
```

The `access_token` is a JWT containing the `oid` (object ID) claim used as `customer_id`.

---

## HTTP API

Base URL: `https://api-kohler-us.kohler.io`

All requests require:
- `Authorization: Bearer {access_token}`
- `Ocp-Apim-Subscription-Key: {apim_subscription_key}`
- `Content-Type: application/json`

### Device Discovery

```
GET /devices/api/v1/device-management/customer-device/{customer_id}
```

Returns customer info with nested homes and devices.

**Response:**
```json
{
  "customerId": "uuid",
  "homes": [
    {
      "homeId": "uuid",
      "homeName": "Home",
      "devices": [
        {
          "deviceId": "uuid",
          "logicalName": "Master Bath",
          "sku": "GCS",
          "capabilities": ["shower", "preset"]
        }
      ]
    }
  ]
}
```

### Device State

```
GET /devices/api/v1/device-management/gcs-state/gcsadvancestate/{device_id}
```

**Response:**
```json
{
  "id": "device_id",
  "deviceId": "device_id",
  "sku": "GCS",
  "tenantId": "customer_id",
  "connectionState": "Connected",
  "lastConnected": 1699999999,
  "state": {
    "currentSystemState": "normalOperation",
    "warmUpState": {
      "warmUp": "warmUpDisabled",
      "state": "warmUpNotInProgress"
    },
    "presetOrExperienceId": "0",
    "totalVolume": "0",
    "totalFlow": "0.0",
    "ready": "false",
    "valveState": [
      {
        "valveIndex": "1",
        "atFlow": "0",
        "atTemp": "0",
        "flowSetpoint": "0",
        "temperatureSetpoint": "0",
        "errorFlag": "0",
        "errorCode": "0",
        "pauseFlag": "0",
        "out1": "0",
        "out2": "0",
        "out3": "0",
        "outlets": []
      }
    ],
    "ioTActive": "Inactive"
  },
  "setting": {
    "valveSettings": [
      {
        "valve": "Valve1",
        "noOfOutlets": "3",
        "outletConfigurations": [
          {
            "outLetType": "11",
            "outLetId": "1",
            "maximumOutletTemperature": "48.8",
            "minimumOutletTemperature": "15.0",
            "defaultOutletTemperature": "37.7",
            "maximumFlowrate": "100",
            "minimumFlowrate": "0",
            "defaultFlowrate": "50"
          }
        ]
      }
    ],
    "flowControl": "Disabled"
  }
}
```

**State Values:**
| Field | Values |
|-------|--------|
| `connectionState` | `Connected`, `Disconnected` |
| `currentSystemState` | `normalOperation`, `showerInProgress` |
| `warmUpState.state` | `warmUpNotInProgress`, `warmUpInProgress` |
| `out1`, `out2`, `out3` | `"0"` (off), `"1"` (on) |

### Presets

```
GET /devices/api/v1/device-management/gcs-preset/{device_id}
```

**Response:**
```json
{
  "presets": [
    {
      "id": 1,
      "title": "Morning",
      "duration": 600,
      "state": "active",
      "isExperience": false,
      "valves": [
        {
          "valveIndex": 1,
          "out1": true,
          "out2": false,
          "out3": false,
          "temperatureSetpoint": 38.0,
          "flowSetpoint": 100
        }
      ]
    }
  ]
}
```

### Start/Stop Preset

```
POST /platform/api/v1/commands/gcs/controlpresetorexperience
```

**Request:**
```json
{
  "deviceId": "device_id",
  "sku": "GCS",
  "presetId": "1",
  "command": "start"
}
```

Command values: `start`, `stop`

### Warmup Control

```
POST /platform/api/v1/commands/gcs/warmup
```

**Request:**
```json
{
  "deviceId": "device_id",
  "sku": "GCS",
  "presetId": "1",
  "command": "start"
}
```

### Valve Control

```
POST /platform/api/v1/commands/gcs/solowritesystem
```

**Request:**
```json
{
  "deviceId": "device_id",
  "sku": "GCS",
  "tenantId": "customer_id",
  "gcsValveControlModel": {
    "primaryValve1": "0179C801",
    "secondaryValve1": "00000000",
    "secondaryValve2": "00000000",
    "secondaryValve3": "00000000",
    "secondaryValve4": "00000000",
    "secondaryValve5": "00000000",
    "secondaryValve6": "00000000",
    "secondaryValve7": "00000000"
  }
}
```

#### Valve Hex Command Format

Each valve command is an 8-character hex string (4 bytes):

```
[prefix][temperature][flow][mode]
```

| Byte | Description | Values |
|------|-------------|--------|
| Prefix | Valve ID | `01` = primary, `11`-`71` = secondary 1-7 |
| Temperature | Encoded temp | `(celsius - 25.6) * 10` |
| Flow | Flow rate | `0`-`200` (0-100% scaled by 2) |
| Mode | Outlet/state | See below |

**Mode Values:**
| Hex | Mode |
|-----|------|
| `00` | Off |
| `01` | Showerhead |
| `02` | Tub Filler |
| `03` | Tub + Handheld |
| `40` | Stop (pause) |

**Examples:**
| Command | Meaning |
|---------|---------|
| `0179C801` | Primary valve, 37.7°C, 100% flow, showerhead on |
| `01796402` | Primary valve, 37.7°C, 50% flow, tub filler on |
| `00000000` | Off |

**Temperature Encoding:**
```
temp_byte = (celsius - 25.6) * 10
celsius = temp_byte / 10 + 25.6

Example: 37.7°C -> (37.7 - 25.6) * 10 = 121 = 0x79
```

### Mobile Settings (IoT Hub Credentials)

```
POST /platform/api/v1/mobile/settings
```

**Request:**
```json
{
  "tenantId": "customer_id",
  "mobileDeviceId": "unique_id",
  "username": "AppName",
  "os": "Android",
  "devicePlatform": "FirebaseCloudMessagingV1",
  "deviceHandle": "fcm_token",
  "tags": ["FirmwareUpdate"]
}
```

**Response:**
```json
{
  "ioTHubSettings": {
    "ioTHub": "prd-hub.azure-devices.net",
    "deviceId": "mqtt_client_id",
    "username": "prd-hub.azure-devices.net/mqtt_client_id/?api-version=2021-04-12",
    "password": "SharedAccessSignature sr=prd-hub.azure-devices.net&sig=...&se=...",
    "connectionString": "HostName=prd-hub.azure-devices.net;DeviceId=...;SharedAccessSignature=..."
  }
}
```

---

## MQTT API (Azure IoT Hub)

Real-time state updates are delivered via Azure IoT Hub over MQTT.

### Connection

| Parameter | Value |
|-----------|-------|
| Host | `ioTHubSettings.ioTHub` (e.g., `prd-hub.azure-devices.net`) |
| Port | `8883` (TLS) |
| Client ID | `ioTHubSettings.deviceId` |
| Username | `ioTHubSettings.username` |
| Password | `ioTHubSettings.password` (SAS token) |

### Topics

**Subscribe to device messages:**
```
devices/{device_id}/messages/devicebound/#
```

**Subscribe to direct methods:**
```
$iothub/methods/POST/#
```

### Direct Method Responses

When receiving a direct method call on `$iothub/methods/POST/{method_name}/?$rid={request_id}`, respond with:

```
Topic: $iothub/methods/res/200/?$rid={request_id}
Payload: {"status": "received"}
```

### State Update Messages

Messages on `devices/{device_id}/messages/devicebound/#` contain JSON state updates matching the device state structure from the HTTP API.
