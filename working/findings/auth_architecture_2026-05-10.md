---
name: Kohler auth architecture — discovered 2026-05-10
description: The actual Konnect auth model — APIM mTLS, service-account ROPC, B2C user sign-in. Captures end every prior unknown from the May spike.
type: project
---

**Status as of 2026-05-10**: APIM mTLS architecture is correctly reverse-engineered, but the "service-account JWT is what /commands/* accepts" conclusion is WRONG. See `commands_writes_403_2026-05-10.md` for the corrected picture: writes require **B2C_1A_signin-policy** tokens (acquired via interactive sign-in or refresh token), NOT the APIM-issued service-account JWT. The "switch to B2C_1A_signin" plan was NOT a red herring after all — it's the actual fix. The APIM mTLS path is real and the service-account JWT is real, but they're for app-level operations that don't include `/commands/*`.

## The complete auth picture

```
┌─────────┐     mTLS (app_certificate.p12)    ┌──────────┐
│ Konnect │ ────────────────────────────────► │ Kohler   │
│  app    │ ◄────────────────── access_token  │ APIM GW  │
└─────────┘                                   └────┬─────┘
     │                                              │
     │                                              ▼
     │                                  ┌────────────────────┐
     │                                  │ Azure B2C          │
     │                                  │ (ROPC service acct │
     │                                  │  admin.user@…)     │
     │                                  └────────────────────┘
     │
     │  User Sign In (B2C_1A_signin WebView, gated on access_token above)
     ▼
   …user identity flow…
```

The app authenticates ITSELF to Kohler's APIM gateway via:
1. **mTLS client certificate** — `res/raw/app_certificate.p12`, password `d6jaqQ1nJxFAuXs`.
   Subject: `C=us, ST=Wisconsin, O=Kohler Co., CN=apim-prod-us`. Uses RC2-40-CBC
   (needs OpenSSL legacy provider to decrypt with modern OpenSSL).
2. **APIM subscription key** (header `Ocp-Apim-Subscription-Key: ca2f50cbc01845e9af356f866b16c9f1`)

Once authenticated, the app does `GET https://az-amer-prod-kohlerkonnect-apim.azure-api.net/token/api/v1/token/` and receives a JWT access_token issued by the APIM gateway. The token is a **B2C ROPC token for `admin.user@kohler.com`** — a Kohler-internal service account, not the end user. The ROPC happens server-side at the APIM gateway; the app never sees the service account's password.

Decoded JWT payload:
```json
{
  "aud": "f5d87f3d-bdeb-4933-ab70-ef56cc343744",
  "iss": "https://konnectkohler.b2clogin.com/55ed507b-cce3-4176-a402-7fb9a456bbd8/v2.0/",
  "idp": "LocalAccount",
  "oid": "c143833c-88ff-48bc-9e12-04d65aa3ee59",
  "name": "admin.user@kohler.com",
  "emails": ["admin.user@kohler.com"],
  "tfp": "B2C_1_ROPC_Auth",
  "scp": "apiaccess",
  "azp": "8caf9530-1d13-48e6-867c-0f082878debc",
  "ver": "1.0"
}
```

Key facts:
- **B2C tenant ID**: `55ed507b-cce3-4176-a402-7fb9a456bbd8` (new info — different from the customer tenant `cfd22e16-...` we had)
- **API audience**: `f5d87f3d-bdeb-4933-ab70-ef56cc343744` (new)
- **Service-account OID**: `c143833c-88ff-48bc-9e12-04d65aa3ee59`
- **Scope**: `apiaccess`
- **App client_id** (`azp`): `8caf9530-1d13-48e6-867c-0f082878debc` — matches `auth_config_release.json`
- **Issuer policy**: `B2C_1_ROPC_Auth` — the legacy ROPC policy. NOT `B2C_1A_signin`.

## What this means for the auth-rewrite

The parked plan (`2026-05-09_b2c_1a_signin_auth_rewrite.md`) assumed we needed to switch from ROPC to `B2C_1A_signin` (PKCE/interactive). That was wrong. The reality is:

- The app's identity → ROPC via APIM, with mTLS as the actual credential check
- The user's identity → separate flow, opens after the app-side token is obtained

For `kohler-anthem` to call `/commands/*` endpoints, it must:
1. Present `app_certificate.p12` as mTLS client cert
2. Include the APIM subscription key in headers
3. GET `/token/api/v1/token/` to obtain the access_token
4. Include the access_token as `Authorization: Bearer <jwt>` on subsequent calls

The "403 on /commands/gcs/*" finding from the May spike is now explained: those endpoints require the app-issued JWT + mTLS, both of which the library was missing.

## Why this is GOOD news

- The library doesn't need user credentials at all for app-level operations. The mTLS cert + APIM key are enough to act on behalf of admin.user@kohler.com.
- The user's actions (controlling THEIR specific devices) probably use the same access_token with `customer_id`/`tenant_id` query params, all gated on the app-level identity.
- We have all the inputs now: cert + password, APIM key, audience, issuer.
- Token lifetime: 3600s (exp - iat = 1778462795 - 1778459195 = 3600). Need a refresh strategy.

## Sources

- mitmproxy capture session `~/Library/Caches/kohler-anthem/token-captures/20260510_202950/` — the 201 response containing the JWT
- Frida bypass `KeyStore.load(InputStream, char[])` hook captured the PKCS12 password at runtime
- Konnect APK base.apk → `res/raw/app_certificate.p12` (extracted, in `~/Library/Caches/kohler-anthem/client-certs/app_certificate.pem`)

## User-side sign-in: MSAL Native Auth (NOT a WebView)

**Discovered late in the 2026-05-10 session via dex string scan**: Konnect uses Microsoft's new **MSAL Native Auth** SDK, not the classic interactive WebView flow. The relevant class is bundled inside the APK at:

```
com/microsoft/identity/common/java/nativeauth/providers/NativeAuthOAuth2Configuration
```

with these endpoint suffix constants:
- `SIGN_IN_INITIATE_ENDPOINT_SUFFIX = "/oauth2/v2.0/initiate"`
- `SIGN_IN_CHALLENGE_ENDPOINT_SUFFIX = "/oauth2/v2.0/challenge"`
- `SIGN_IN_INTROSPECT_ENDPOINT_SUFFIX = "/oauth2/v2.0/introspect"`

Plus the standard `/oauth2/v2.0/token` and `/oauth2/v2.0/authorize`.

**Why this matters**: MSAL Native Auth doesn't open a browser/CCT — it does an in-app email/password/OOB-code flow against B2C native-auth endpoints. The B2C tenant must have an "External Identities" config (CIAM) with native-auth enabled. That explains:
- Why we never saw a Chrome Custom Tab open on Sign-In click
- Why the parked plan's "switch to B2C_1A_signin PKCE/WebView" was wrong — there's NO WebView in the new flow
- Why direct GET/POST against `https://konnectkohler.b2clogin.com/konnectkohler.onmicrosoft.com/<policy>/oauth2/v2.0/initiate` returns 404 — those endpoints likely require additional native-auth-specific config and/or live behind the APIM gateway

**For the auth rewrite**: the library has two valid approaches:
1. **Use the service-account JWT we captured** (simplest — covers `/commands/*`). Library identifies as the app; user's actions ride on the user's tenant_id/customer_id query params.
2. **Reproduce the MSAL Native Auth flow** (more complete — gives a user-bound token). POST username → initiate → challenge → token. Microsoft's library is open-source; the protocol is documented at https://learn.microsoft.com/en-us/entra/identity-platform/concept-native-authentication.

The first approach is far simpler and should be tried first.

## Open questions for next session

1. **What unlocks `auth_certificate.pfx`?** Different password than `app_certificate.p12`. Still unknown. May be for a separate purpose (per-device cert? Per-customer? Provisioning?). Or unused legacy.
2. **What's the full Konnect user-sign-in URL pattern?** Native Auth library is in the APK; URL construction logic should be reversible from `NativeAuthOAuth2Configuration.smali`. Likely something like `https://az-amer-prod-kohlerkonnect-apim.azure-api.net/<tenant>/<policy>/oauth2/v2.0/initiate` with the APIM key + mTLS cert.
3. **Service-account password rotation**: if Kohler rotates the embedded `admin.user@kohler.com` ROPC password, the APIM-issued tokens stop working. The library should treat the 401/403 → retry-with-fresh-token path as standard.
4. **Other `/token/api/v1/*` endpoints**: probably more in the APIM map. `CustomerDevice` was spotted. Worth listing.
5. **Sign In click fires correctly but downstream call silently errors**: confirmed late in session. The toast "This operation could not be completed, Please try again" is a known internal error toast. The click handler:
   - Calls `GET /token/api/v1/token/` → 201 with a fresh service-account JWT (we capture this)
   - Then tries to do something else (probably load per-user state OR start the MSAL Native Auth /initiate flow)
   - Errors silently before making a second network call (no second mitmproxy hit)
   - Shows the toast
   The most likely cause: the legacy ROPC user `29northway@milliped.com` may no longer be registered in Kohler's current B2C tenant (different tenant ID than the customer's tenant; possibly migrated). Or there's a per-customer config call that returns "user not found" cached in SharedPreferences. A new user that signs up via the app should work, but that's outside the harness's scope.
6. **Konnect bundles MSAL Native Auth library but the /initiate endpoint isn't reachable** at `b2clogin.com/{tenant}/{policy}/oauth2/v2.0/initiate` even via mTLS through APIM. Probably hosted at a different APIM-mapped path we haven't found. The library is open-source — protocol is in `NativeAuthOAuth2Configuration.smali` if a future session wants to decode the exact URL.
