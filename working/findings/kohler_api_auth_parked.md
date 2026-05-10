---
name: Kohler API auth state — parked
description: As of May 2026 the ROPC-token rewrite hypothesis is unverified; Phase 0 partial; resume with Android emulator + Frida traffic capture
type: project
originSessionId: 6eb6627b-90fe-4764-8452-4539341093ee
---
**Status as of 2026-05-10**: The auth rewrite plan in `working/plans/2026-05-09_b2c_1a_signin_auth_rewrite.md` is PARKED. Phase 0 spike completed but did not verify the central hypothesis.

**Why:** Why the original ROPC-rejection-on-/commands/* problem hasn't been fixed yet.
**How to apply:** Read the plan file's "Findings from 2026-05-10 Phase 0 attempt" section before doing any work on the auth rewrite. Don't merge the open auth-rewrite PRs as-is.

## Summary of what's verified

- ROPC tokens get HTTP 403 on every `/platform/api/v1/commands/{gcs,hub}/*` endpoint (uniform, body- and UA-independent). Reads + `mobile/settings` work fine.
- The B2C_1A_signin policy exists, accepts `/authorize` requests, but its `/token` endpoint **rejects PKCE-only flows** with `AADB2C90079: Clients must send a client_secret when redeeming a confidential grant`. So the app registration is configured as a confidential client.
- The Konnect iOS app currently works end-to-end. Whatever it sends to `/token` works; we couldn't capture it (iOS pins certs through the auth flow).
- Plan's specifics (URL pattern without `/tfp/`, `msauth.com.kohler.hermoth://auth` redirect, "no client_secret needed") are **wrong**. Actual MSAL config uses `/tfp/` and redirect `msauth://com.kohler.hermoth/<sig-hash>%3D` (literal `%3D`).

## Key APK locations (resume here)

- `credential-extraction/kohler-konnect-3.0.1-apk/base.apk` — needs `git-lfs pull` before unzip works (file is otherwise a 133-byte LFS pointer).
- `res/raw/auth_config_release.json` (in unzipped APK) — MSAL config: client_id, redirect, B2C authority URL.
- `res/raw/auth_certificate.pfx` and `app_certificate.p12` — likely used for cert-based JWT-bearer client auth at the token endpoint. Passwords unknown; common defaults all failed MAC verification.
- DEX strings like `client_assertion`, `JWT_BEARER`, `urn:ietf:params:oauth:client-assertion-type:jwt-bearer` confirm cert-based client auth is at least supported.

## Concrete next steps when resuming

The capture pipeline is **fully scripted** as of 2026-05-10 on `feat/emulator-token-capture`. To resume:

1. Put Genymotion Desktop trial creds in `/Volumes/ring/env/kohler.env`
   (`GENYMOTION_EMAIL`, `GENYMOTION_PASSWORD`).
2. `cd credential-extraction && make harness`.
3. Sign in to Konnect on the emulator when prompted (UI flow not yet
   recorded into `konnect_signin.py`; see `KONNECT_SIGNIN_STEPS` to fill in
   for fully hands-off runs).
4. The capture lands at
   `~/Library/Caches/kohler-anthem/token-captures/<timestamp>/token_capture.json`.
5. That JSON answers: `client_secret`? `client_assertion` + JWT-bearer? extra
   params? Update `KohlerOAuthAuth` in `src/kohler_anthem/auth.py` on
   `feat/b2c-1a-signin-auth` accordingly and fix the URLs/redirect in
   `KohlerOAuthConfig`.

See `credential-extraction/README.md` for the full pipeline + troubleshooting,
and `working/plans/2026-05-10_emulator_token_capture.md` for the build-out
plan.

## Open PRs (status)

- `yon/kohler-anthem#10` — health-check diagnostic, MERGED.
- `yon/kohler-anthem#12` — auth rewrite, **DO NOT MERGE** (specifics are wrong).
- `yon/ha-kohler-anthem#4` — companion HA component, **DO NOT MERGE** (depends on #12).

## Live credentials lookup

The user's working ROPC credentials (for read-side flow + as a baseline for `make health-check`) live in their Home Assistant install's `.storage/core.config_entries` file under the `kohler_anthem` domain entry. Fields: `username`, `password`, `client_id`, `apim_subscription_key`, `api_resource`, `tenant_id`. The HA `secrets.yaml` has the same five fields under `kohler_*` keys. There is no checked-in `credential-extraction/kohler-credentials.yaml`.

The active `device_id` is `gcs-sio3225nc9` (from HA's `core.device_registry`).

> Machine-specific: on the production LXC, those HA files are at `/opt/home-automation/homeassistant/config/.storage/...` and `/opt/home-automation/homeassistant/config/secrets.yaml`. From the developer Mac, access them via SSH or copy them locally for offline reading.
