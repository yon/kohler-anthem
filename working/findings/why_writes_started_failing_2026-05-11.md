---
name: Why HA integration writes started returning 403
description: Postmortem — Kohler made two server-side changes that broke the library's ROPC flow. Reads survived on cached tokens; writes 403'd on new RBAC.
type: project
---

**Short version:** Kohler tightened backend authorization on `/commands/*` (the
write endpoints) to require tokens issued by the `B2C_1A_signin` policy. The
library has always issued tokens via `B2C_1_ROPC_Auth`. Both policies issue
JWTs against the same audience and scope, so the difference is invisible
until you decode the `tfp` claim — but the backend keys its RBAC on exactly
that claim, so ROPC tokens started getting 403'd. Independently, Kohler also
renamed the API resource, which broke fresh ROPC token acquisitions.

## What the library was doing

```
KohlerAuth.authenticate(session)
  → POST https://konnectkohler.b2clogin.com/tfp/konnectkohler.onmicrosoft.com/B2C_1_ROPC_Auth/oauth2/v2.0/token
    grant_type=password
    client_id=8caf9530-...
    scope=openid offline_access https://konnectkohler.onmicrosoft.com/api-mob/access/apiaccess
  → returns access_token with claims:
      "tfp": "B2C_1_ROPC_Auth"
      "aud": "f5d87f3d-bdeb-4933-ab70-ef56cc343744"
      "scp": "apiaccess"

Every request:
  Authorization: Bearer <that token>
  Ocp-Apim-Subscription-Key: <library's APIM key>
```

This worked across reads (`/devices/api/v1/*`, `/platform/api/v1/mobile/*`)
**and writes** (`/platform/api/v1/commands/gcs/*`) for the lifetime of the
integration up until Kohler's change.

## What Kohler changed

Two changes, made server-side, on independent timelines:

### Change A — renamed the API resource

The library's OAuth scope was constructed against
`https://konnectkohler.onmicrosoft.com/api-mob/access`. Kohler retired that
form and now only accepts the application **GUID** form
(`https://konnectkohler.onmicrosoft.com/f5d87f3d-bdeb-4933-ab70-ef56cc343744`).

**Effect:** Fresh ROPC token requests with the old scope started returning:

```
AADB2C90205: This application does not have sufficient permissions
against this web resource to perform the operation.
```

Long-running HA instances that had cached an access_token + refresh_token
issued before this change kept working **for reads**, because:

* The cached `access_token` was already valid (the resource it was issued
  against is what the backend now expects too — Kohler is just enforcing
  the new naming at the token endpoint, not on the backend).
* Refresh requests sent the cached `refresh_token`, which B2C honored as
  long as the original consent was still recorded — even if the new scope
  form would have been rejected at the authorize step.

But any process restart that lost the cached refresh_token, or any
re-auth after a token revocation, would fail at the `/oauth2/v2.0/token`
step itself. Symptom: `AuthenticationError: invalid_request:
AADB2C90205...`.

### Change B — backend RBAC keys on the `tfp` claim

Kohler added (or tightened) a check on `/platform/api/v1/commands/gcs/*`
that rejects tokens unless their `tfp` claim is `B2C_1A_signin`. The
library's ROPC tokens have `tfp=B2C_1_ROPC_Auth` — wrong policy from the
backend's new perspective.

**Effect:** Every write started returning:

```
HTTP 403
{"detail": null, "error": null, "statusCode": 403, "message": "Forbidden"}
```

regardless of whether the token was freshly issued or cached. The probe
in `tests/integration/_probe.py` classifies this as
`BACKEND_FORBIDDEN — backend RBAC denied (token type or roles)`.

Reads kept working because `/devices/*` and `/platform/api/v1/mobile/*`
accept both `tfp` values — Kohler only tightened the `/commands/*` path.

## Why Kohler probably made these changes

* **Phasing out ROPC.** Microsoft has been deprecating ROPC for years
  (it doesn't allow MFA, doesn't support modern consent screens,
  bypasses Conditional Access). Many Azure AD B2C tenants are required
  to disable it as a security baseline. Kohler's official Android app
  uses the interactive `B2C_1A_signin` policy via MSAL, so they can
  enforce the new policy at the backend without affecting their own
  users.
* **Resource GUID migration.** Microsoft's tooling and many enterprise
  configurations prefer the GUID identifier for app registrations
  because it survives renames. Kohler may have changed the friendly
  name at some point and retired the old scope form.

Neither change is announced anywhere we can find. They surfaced through
empirical 403 responses on the integration.

## How the library handles both changes now

* **Change A:** `KohlerConfig.api_resource` defaults to the GUID
  (`f5d87f3d-bdeb-4933-ab70-ef56cc343744`). The `auth_scope` property
  accepts either form (GUID or full URL) and normalizes it correctly.
  Fresh ROPC token acquisition works again.
* **Change B:** New `B2CSignInAuth` class does silent refresh against
  the `B2C_1A_signin` policy using a stored `refresh_token`. The
  `KohlerAnthemClient._request()` routes `/commands/*` writes through
  this token; reads stay on ROPC. The refresh_token is seeded once per
  user via `python -m kohler_anthem.b2c_signin` — a manual OAuth code flow
  (Kohler's app registration only whitelists `msauth://` and a Google
  Home redirect, so MSAL's `acquire_token_interactive` can't complete
  from a dev machine — see `commands_writes_403_2026-05-10.md` for the
  detail).

## What this means for HA users

* Existing HA installs that haven't been restarted in months will keep
  reading state but writes have been silently 403ing the entire time.
* Restarting HA (or losing the cached token for any reason) breaks
  reads too — until the user updates the library to a version that
  uses the GUID scope.
* To restore writes: update to `kohler-anthem >= 0.2.0`, run the
  one-time `b2c_signin.py` seed step, and update the HA integration's
  config entry with the resulting `b2c_refresh_token`. After that,
  silent refresh keeps it alive (B2C rotates the refresh_token; the
  library tracks and exposes the rotation via
  `KohlerAnthemClient.b2c_refresh_token` for HA to persist).

## Forward-looking risk

* **Refresh_token TTL.** B2C refresh_tokens last up to 90 days by
  default. Kohler may have configured the policy with a shorter TTL.
  When the refresh_token finally expires (or is revoked server-side),
  the library raises `AuthenticationError` and the user has to re-run
  the seed step.
* **More tightening.** Kohler might extend the `tfp=B2C_1A_signin`
  requirement to reads next, breaking the ROPC read path. The fix
  would be to route reads through `B2CSignInAuth` too — a single-line
  change to `client.py`. Watch for `BACKEND_FORBIDDEN` showing up on
  read endpoints.
* **Policy migration.** Kohler could rename `B2C_1A_signin` to
  something else. The library's `KohlerConfig.b2c_signin_policy`
  field is overridable; if Kohler announces a new policy name, users
  can set it without a library release.
