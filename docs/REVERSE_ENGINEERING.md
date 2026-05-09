# Reverse Engineering Notes

How the Kohler Anthem API was reverse-engineered from the Kohler Konnect Android app.

## Architecture

The Kohler Anthem shower uses a cloud-only architecture:

```
Mobile App ──► Azure AD B2C ──► Authentication
     │
     ├──► api-kohler-us.kohler.io ──► REST API (commands)
     │
     └──► prd-hub.azure-devices.net ──► IoT Hub MQTT (status)
```

No local API exists. All communication is cloud-based.

## Tools Used

1. **APK Analysis** - Decompiled with jadx, searched for endpoints/models
2. **Frida** - Bypassed SSL pinning and root detection
3. **mitmproxy** - Captured actual API traffic

## APK Analysis

### Key Discoveries

**Package:** `com.kohler.hermoth`

**Authentication Config (msal_config.json):**
- Client ID: `$KOHLER_CLIENT_ID`
- Authority: `konnectkohler.b2clogin.com`
- Policy: `B2C_1A_signin` (interactive) or `B2C_1_ROPC_Auth` (password flow)

**API Patterns:**
- Base URL: `api-kohler-us.kohler.io`
- Commands: `/platform/api/v1/commands/gcs/{action}`
- Devices: `/devices/api/v1/device-management/customer-device/{id}`

**Data Models Found:**
- `AnthemWriteSoloStatusRequestModel` - Valve control
- `AnthemWritePresetStartRequestModel` - Preset start
- `MqttAnthemPresetDataModel` - MQTT status

### Statistics

- 509,792 strings extracted
- 4,318 Anthem-related classes
- 180 URLs found
- 50+ API endpoints discovered

## Frida Bypass

The app has multiple protections that must be bypassed:

### Required Bypasses

1. **Emulator Detection** - Spoof Build properties as Samsung Galaxy S21
2. **Root Detection** - Hook `Is.b.n()` (Kohler's obfuscated root check)
3. **SSL Pinning** - Hook TrustManagerImpl to accept all certificates

### Frida Command

```bash
frida -D 127.0.0.1:6555 -f com.kohler.hermoth -l scripts/frida_ssl_bypass.js
```

Key: Use spawn mode (`-f`) to hook before app initialization.

### Bypasses That Weren't Needed

- Native access()/stat() hooks
- Firebase App Check / Play Integrity
- Proxy detection
- Package manager checks

## mitmproxy Capture

### Setup

1. Start mitmproxy on host:
   ```bash
   mitmweb --listen-host 0.0.0.0 --listen-port 8080
   ```

2. Configure Android to use proxy

3. Install mitmproxy CA cert on Android

4. Run Frida to bypass SSL pinning

5. Use Kohler app and capture traffic

### Key Values Captured

| Value | Source |
|-------|--------|
| APIM Subscription Key | `Ocp-Apim-Subscription-Key` header |
| Device ID | Device discovery response |
| Tenant ID | JWT token claims |

## IoT Hub MQTT

### Connection String

Not returned by REST API. Must capture from app via Frida.

Format:
```
HostName=prd-hub.azure-devices.net;DeviceId={id};SharedAccessKey={key}
```

The SharedAccessKey changes per session (provisioned dynamically).

### Message Flow

- Mobile app connects as: `Android_{customer_id}_{suffix}`
- Shower device ID: `gcs-{serial}`
- Status updates via telemetry messages
- Commands via Direct Methods (`ExecuteControlCommand`)

## Auth Flow: ROPC vs B2C_1A_signin

Kohler's B2C tenant exposes two policies, both visible at:
`https://konnectkohler.b2clogin.com/konnectkohler.onmicrosoft.com/{policy}/v2.0/.well-known/openid-configuration`

| Policy | Type | What it issues |
|--------|------|----------------|
| `B2C_1_ROPC_Auth` | Resource Owner Password Credentials (legacy) | Tokens with `tfp=B2C_1_ROPC_Auth` and `scp=apiaccess`. No `acr`/`amr` auth-context claims. |
| `B2C_1A_signin` | Custom Identity Experience Framework (interactive) | Tokens with extra auth-context claims. Used by the official iOS/Android apps. |

The library currently uses ROPC because it's the simplest flow to script
from a captured `client_id` + username/password. **However, as of early
May 2026, Kohler's backend rejects ROPC-issued tokens on
`/platform/api/v1/commands/gcs/*` with HTTP 403** while still accepting
them on read endpoints and on `/platform/api/v1/mobile/settings`.

### How to confirm this is what's happening

Run the health check:

```bash
make health-check
```

If reads + `mobile/settings` return `OK` and the three `/commands/gcs/*`
endpoints return `BACKEND_FORBIDDEN` (HTTP 403), this is exactly the
ROPC-rejection pattern. The diagnostic prints an interpretation pointing
at the auth-flow rewrite plan.

### Why the diagnostic distinguishes APIM-403 from backend-403

A 403 from APIM (e.g., subscription key revoked or unauthorized for the
product) carries APIM's gateway error envelope. A 403 from the backend
(ASP.NET Web API) carries CSP / x-frame-options / referrer-policy headers
and `{"detail":null,"error":null,"statusCode":403,"message":"Forbidden"}`.
That distinction lets us separate "key problem" from "token-type problem"
without guessing.

### Empty-body classifier trick

For endpoints we can't safely call (would actually turn the shower on),
the diagnostic POSTs `{}`. If the caller has access, validation runs
*after* auth and returns 400. If the caller is forbidden, the backend
returns 403 *before* validation. So:

- 200/201/400 → access granted
- 403 → access denied

This is the classifier `tests/integration/_probe.py` uses.

### The fix path

OAuth Authorization Code + PKCE against `B2C_1A_signin`. Same `client_id`,
same `apim_subscription_key`. The library ships both flows side by side:
``KohlerConfig`` for the legacy ROPC path (reads-only fallback) and
``KohlerOAuthConfig`` + a caller-provided ``TokenStore`` for the interactive
path. The OAuth endpoints differ from ROPC:

- ROPC URL pattern: `…/tfp/{tenant}/B2C_1_ROPC_Auth/oauth2/v2.0/token`
- B2C_1A_signin pattern: `…/{tenant}/B2C_1A_signin/oauth2/v2.0/{authorize,token}`
  (no `tfp/` prefix)

#### Interactive sign-in helper

```bash
make oauth-login OAUTH_TOKENS=~/.kohler-tokens.json
```

This generates a PKCE pair, opens the browser to the authorize URL, captures
the redirect on a loopback HTTP server, and writes the resulting access /
refresh tokens to the JSON file. After that:

```bash
python dev/scripts/health_check.py \
    --yaml credential-extraction/kohler-credentials.yaml \
    --oauth-tokens ~/.kohler-tokens.json
```

…probes every endpoint with the OAuth-issued bearer. The `/commands/gcs/*`
rows should classify as `OK` / `BAD_REQUEST` (i.e. auth passed; only the
empty body was rejected) instead of `BACKEND_FORBIDDEN`.

The original implementation plan lives at
[`working/plans/2026-05-09_b2c_1a_signin_auth_rewrite.md`](../working/plans/2026-05-09_b2c_1a_signin_auth_rewrite.md).

## Dead Ends

### Endpoints That Don't Work

- `kohlerproduat.onmicrosoft.com` - Doesn't exist (documentation error)
- `prd-apim.kohler.com` - DNS doesn't resolve
- `writesolostatus` endpoint - Returns 404
- `writepresetstart` endpoint - Returns 404

### APK Patching

Tried patching APK with frida-gadget but app has integrity checking. Frida server is more reliable.

## Files

| File | Purpose |
|------|---------|
| `scripts/frida_ssl_bypass.js` | Frida SSL/root bypass script |
| `scripts/test_quick_dirty.py` | API test script |
| `scripts/comprehensive_apk_analysis.py` | APK string extraction |
| `apk_analysis_results.json` | Extracted APK data |
