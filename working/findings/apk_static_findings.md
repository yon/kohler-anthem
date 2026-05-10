---
name: APK static analysis findings
description: What the Kohler Konnect 3.0.1 APK reveals — endpoints, hosts, auth artifacts
type: project
originSessionId: 6eb6627b-90fe-4764-8452-4539341093ee
---
**Why:** Avoid re-doing static analysis next session.
**How to apply:** Reference these when planning the next phase of work.

From unzipping `credential-extraction/kohler-konnect-3.0.1-apk/base.apk` (~81 MB, LFS-backed) and grep'ing dex strings + `res/raw/`:

## API hosts the app references

- `https://api-kohler-us.kohler.io` — what the library currently uses. Reads + `mobile/settings` work; commands 403.
- `https://az-amer-prod-kohlerkonnect-apim.azure-api.net` — alternate APIM gateway. Same paths return 404 (different routing config). Probably either internal-only or with different `Ocp-Apim-Subscription-Key` requirements.
- `https://konnectkohler.b2clogin.com` — B2C tenant.
- `https://api.kohler.bycopilot.com` and `https://report.kohler.bycopilot.com` — Kohler's "Co-Pilot" smart home platform. Unrelated to Anthem auth.

## All `/platform/api/v1/commands/gcs/*` endpoints in the APK

The library knows: `warmup`, `controlpresetorexperience`, `solowritesystem`. The APK strings additionally reference: `createpreset`, `factoryreset`, `uiconfigsuccess`, `writeoutletconfig`, `writepreset`, `writeuiconfig`. All 403 with ROPC tokens. `solowritesystem` only appears templated (`/platform/api/{version}/commands/gcs/solowritesystem`); `v2` returns 404.

## Parallel `/commands/hub/*` family

For the "Hub" product line (different Kohler product). Also 403 with ROPC. Endpoints include: `valvecontrol`, `steamcontrol`, `shower/experience/control`, `steam/experience/control`, `favorite/control`, `iceshower/experience/control`.

## Other product-line command families

`/commands/{dtvplus,evo,blade,faucet,sfc}/*` — Kohler has many product lines. Anthem is `gcs`. Not relevant unless cross-product code paths matter.

## MSAL / OAuth

- `res/raw/auth_config_release.json` (verified live):
  ```json
  {
    "client_id": "8caf9530-1d13-48e6-867c-0f082878debc",
    "authorization_user_agent": "MULTIPLE",
    "redirect_uri": "msauth://com.kohler.hermoth/2DuDM2vGmcL4bKPn2xKzKpsy68k%3D",
    "authorities": [{
      "type": "B2C",
      "authority_url": "https://konnectkohler.b2clogin.com/tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin/",
      "default": true
    }]
  }
  ```
  Note `tfp/` prefix and literal `%3D` in redirect URI.

- Other env configs in `res/raw/`: `auth_config_dev.json`, `auth_config_uat.json`, `auth_config_staging.json`, `auth_config_uk.json`, `auth_config_india.json`, `auth_config_se.json`. None contain a client_secret.

- DEX has all the strings for cert-based JWT-bearer client auth: `client_assertion`, `client_assertion_type`, `urn:ietf:params:oauth:client-assertion-type:jwt-bearer`, `JWT_BEARER`, `DEFAULT_CLIENT_ASSERTION_TYPE`.

- DEX also contains the literal string `Executing ROPC token command...` directly adjacent to `ExecuteControlCommand`. So the app does use ROPC tokens in some role — likely IoT Hub MQTT auth, not the `/commands/*` HTTP path.

## Cert files

- `res/raw/auth_certificate.pfx` (2429 bytes, PKCS12) — almost certainly used for JWT-bearer client auth.
- `res/raw/app_certificate.p12` (2477 bytes) — purpose unclear; possibly mTLS to backend.
- Both have unknown passwords. Tested empty + common defaults; all fail MAC verification.

## IoT Hub / MQTT

DEX contains the full Azure IoT Hub MQTT topic patterns (`$iothub/methods/POST/`, `$iothub/twin/PATCH/properties/desired/`, etc.) and class references like `com.microsoft.azure.sdk.iot.device.transport.mqtt.MqttDirectMethod`. The shower itself implements an `ExecuteControlCommand` direct method. The library's `mqtt.py` connects as the *device* (subscribes to inbound, doesn't invoke); the cloud-to-device side is not implemented.

No direct `azure-devices.net` references in the dex. So the iOS app does NOT talk directly to Azure IoT Hub for cloud-to-device messaging — it goes through Kohler's backend (the `/commands/*` HTTP API). This means switching from HTTP to MQTT direct-methods is NOT a viable workaround; the auth problem must still be solved.
