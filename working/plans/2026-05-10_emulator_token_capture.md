# Plan: Set up emulator pipeline to capture B2C_1A_signin /token request

**Date:** 2026-05-10
**Status:** READY TO RUN — blocked only on Genymotion account sign-in (one-time)
**Task:** Build out the emulator + mitmproxy + Frida pipeline so we can capture the Kohler Konnect app's actual `/token` POST against B2C_1A_signin. Resumes the work parked on 2026-05-10 (see `working/findings/kohler_api_auth_parked.md` and the "Findings from 2026-05-10" section of `2026-05-09_b2c_1a_signin_auth_rewrite.md`).

## Why this work

The B2C_1A_signin policy rejects PKCE-only `/token` requests with `AADB2C90079: client_secret required`. The iOS Konnect app works, so there's a request shape we can't see from outside. APK static analysis strongly suggests certificate-based JWT-bearer client auth (`client_assertion`, `JWT_BEARER`, `urn:ietf:params:oauth:client-assertion-type:jwt-bearer` in DEX). The next investigative step is to **capture the live request** via Android emulator + mitmproxy + Frida SSL-pinning bypass.

## Acceptance criteria

- [x] Pipeline is reproducible: re-running `make harness` from a clean machine works (modulo one-time Genymotion sign-up)
- [x] Findings written up in `working/findings/` for the next session
- [ ] `make emulator-token-capture` runs end-to-end and writes `~/Library/Caches/kohler-anthem/token-captures/<timestamp>/token_capture.json` containing the full `/token` POST headers, body params, and response — **needs Genymotion sign-in + Konnect sign-in**
- [ ] The capture clearly shows which client-auth mechanism the app uses (`client_secret`, `client_assertion`+JWT, or something else)

## Approach

This extends the existing credential-extraction pipeline (which captures the APIM key via Frida-only). The /token capture adds mitmproxy to the picture so we get the actual HTTPS wire bytes.

1. **Install tooling** (homebrew + pip)
   - `brew install --cask genymotion` — 30-day Desktop trial (Personal Edition lacks `gmtool` CLI)
   - `brew install android-platform-tools jadx jq mitmproxy xz`
   - `pip install frida-tools` (in the project venv per existing convention)
2. **User signs into Genymotion** (one-time, interactive — can't automate)
3. **Run existing automated steps**: `make emulator-setup`, `make emulator-frida-setup`, `make emulator-apk-install`
4. **New: mitmproxy setup** (`scripts/mitmproxy_setup.py`)
   - First-run mitmdump to generate `~/.mitmproxy/mitmproxy-ca-cert.cer`
   - Convert to Android system-cert format (subject hash `.0` filename)
   - Push to `/system/etc/security/cacerts/` on emulator (requires `adb root` + `adb remount`)
   - Configure emulator HTTPS proxy → `10.0.3.2:8080` (Genymotion gateway address)
5. **New: token capture** (`scripts/token_capture.py`)
   - Start `mitmdump` with filter `~d b2clogin.com` and a save-flow addon writing to `.build/mitm_flows/`
   - Launch Konnect via `frida -U -f com.kohler.hermoth -l frida_bypass.js`
   - Wait for the user to sign in
   - On Ctrl-C, parse the mitmdump output, extract any `/token` flows, write structured JSON to `.build/captured_token_request.json`
6. **Verify** with the existing checks (`make tools-check`, `make emulator-check`) plus a dry-run lint/format
7. **Update README** with the new flow + the new Make targets

## Files to modify / create

- `credential-extraction/scripts/mitmproxy_setup.py` — NEW (system-cert install + proxy config)
- `credential-extraction/scripts/token_capture.py` — NEW (capture orchestration)
- `credential-extraction/Makefile` — add `emulator-mitmproxy-setup`, `emulator-token-capture`, and update `deps` to include mitmproxy
- `credential-extraction/README.md` — document the new flow
- `working/plans/2026-05-10_emulator_token_capture.md` — this file

## Verification

- [ ] `make tools-check` passes (after install)
- [ ] `make emulator-check` shows device + frida-server
- [ ] mitmdump captures HTTPS traffic from a known site (sanity check)
- [ ] Konnect signs in successfully through the proxy
- [ ] `/token` POST appears in mitmdump output

## Risks & open questions

- **System-cert install may fail on Genymotion**: some Android 11+ images don't accept `/system/etc/security/cacerts/` writes even with root. Fallback: configure Konnect to trust user certs (won't work — pinned), OR rely entirely on Frida's `TrustManagerImpl.verifyChain` bypass and use mitmproxy in transparent mode. The existing `frida_bypass.js` already has the TrustManager bypass (lines 86-119), so if the system-cert path is blocked we can still capture traffic.
- **Konnect app uses certificate transparency / additional pinning**: would require additional Frida hooks beyond what's already in place. Address if it shows up.
- **Trial expires**: 30-day window. Document the date the trial started in README so future-us knows when it lapses.
- **Genymotion sign-up requires user (one-time)**: account creation needs browser/email — can't be automated. After sign-in, `gmtool config --email --password` (via `genymotion_signin.py`) handles everything else.
- **`gmtool admin templates` no longer exists in Genymotion 3.10**: `emulator_setup.py` falls back to a known list of templates. If "Samsung Galaxy S10" + Android 11.0 stops being available, update the constants near the top of that script.

## What's verified

- Genymotion 3.10.0 installed via `brew install --cask genymotion` — same binary as the website download, includes `gmtool`, uses QEMU for Apple Silicon (no VirtualBox needed).
- `gmtool license info` reports `Personal use` by default. `gmtool admin create` returns `A license is required to use this feature` in Personal mode — confirms the Desktop trial is required to drive the harness via gmtool.
- `make apk-fetch` successfully downloaded Konnect 3.0.3 XAPK (~73 MB) from APKPure and extracted 4 split APKs into `~/Library/Caches/kohler-anthem/konnect-apk/3.0.3/`.
- `make tools-check` is green.

## Handoffs to the user

- **Sign into Genymotion** (one-time, after install) — required to activate the trial
- **Sign into Konnect app** in the emulator during `make emulator-token-capture` — required because the whole point is to capture *that flow*
- All other steps run autonomously

## What to do with the captured data

Once `.build/captured_token_request.json` exists, the resumed work continues in PR #12 / `feat/b2c-1a-signin-auth`:

- Fix URL pattern (`/tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin/`) in `KohlerOAuthConfig`
- Fix redirect URI (`msauth://com.kohler.hermoth/2DuDM2vGmcL4bKPn2xKzKpsy68k%3D`)
- Implement whatever client-auth mechanism the capture reveals (probably JWT-bearer w/ PFX-derived cert) in `KohlerOAuthAuth.acquire_token()`
- Re-run `make health-check` against `/commands/gcs/*` to verify the 403 is gone
