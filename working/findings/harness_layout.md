---
name: Emulator + Frida + mitmproxy capture harness
description: How the B2C_1A_signin /token capture pipeline is wired — what's automated, what's still manual, and where artifacts land
type: reference
---

The capture harness was built on 2026-05-10 (branch `feat/emulator-token-capture`) to make the parked auth-rewrite work resumable end-to-end. Single command: `make harness` from `credential-extraction/`.

## What runs autonomously

1. **Tool checks** — `tools_check.py` verifies gmtool, adb, frida (in venv), mitmdump, jadx, jq, openssl.
2. **APK download** — `apk_fetch.py` pulls the latest Konnect APK from APKPure's CDN. Detects version from the base64-encoded `_fn=` query param on the redirect target. Falls back to cached previous version, then to the legacy checked-in `kohler-konnect-3.0.1-apk/` dir.
3. **Genymotion sign-in** — `genymotion_signin.py` runs `gmtool config --email --password` using creds from `/Volumes/ring/env/kohler.env`.
4. **Emulator create + start** — `emulator_setup.py` (Samsung Galaxy S10 / Android 11 / 4 GB RAM).
5. **Frida-server push** — `frida_setup.py` downloads the right frida-server binary from GitHub releases for the device's ABI, pushes to `/data/local/tmp/`, starts it.
6. **APK install** — `emulator_apk_install.py` does `adb install-multiple` of the split APKs from `~/Library/Caches/kohler-anthem/konnect-apk/latest/`.
7. **mitmproxy cert + proxy** — `mitmproxy_setup.py` boots mitmdump briefly to generate the CA, computes the OpenSSL old-style subject hash, pushes to `/system/etc/security/cacerts/<hash>.0` with `adb root` + remount, then sets the Android global `http_proxy` to `10.0.3.2:8080`.
8. **mitmdump + Frida + parse** — `token_capture.py` runs mitmdump with `save_stream_file`, launches Konnect via `frida -U -f com.kohler.hermoth -l frida_bypass.js`, waits for Ctrl-C, parses the flow file for `~d b2clogin.com ~p /token` POSTs, writes structured JSON.

## What still needs manual interaction (today)

| Step | Why | How to automate later |
|------|-----|----------------------|
| Genymotion account sign-up | Their service requires email verification once | Use the same account in `GENYMOTION_EMAIL` going forward; trial limit is per-account. |
| Konnect login flow inside the emulator | UI taps not recorded yet | After first successful capture, populate `KONNECT_SIGNIN_STEPS` in `konnect_signin.py` using `adb shell uiautomator dump` output. Then `make harness` becomes truly hands-off. |

## Where things live

- **Secrets:** `/Volumes/ring/env/kohler.env` (symlinked as repo's `.env`). Loaded by direnv (`.envrc` → `dotenv_if_exists`) and Make (`-include .env`) and the Python scripts (via `env_lib.load_env`).
- **Binary cache:** `~/Library/Caches/kohler-anthem/`. Survives repo wipes. Sized for the ~70 MB Konnect XAPK (the `/Volumes/ring` sparse-bundle is too small).
- **Plan + findings:** `working/plans/2026-05-10_emulator_token_capture.md`, `working/findings/kohler_api_auth_parked.md`.

## Re-running individual steps

The harness orchestrator is thin — each script also works standalone. Common partial reruns:

```
make apk-fetch                   # latest APK only
make emulator-mitmproxy-setup    # re-install CA + proxy (e.g. after device reboot)
make emulator-token-capture      # capture without re-installing everything
```

The Make targets are documented in `make help` (in `credential-extraction/`).

## Tested?

- `make tools-check` — green on a clean machine after `make deps`.
- `make apk-fetch` — successfully downloaded Konnect 3.0.3 XAPK from APKPure on 2026-05-10.
- `make genymotion-signin` — verified failure mode when env is missing (clear error message + sign-up link).
- `make harness` end-to-end — **not yet** run because Genymotion creds need a human sign-up; will happen on first real use.

If APKPure breaks (different anti-bot behavior, URL pattern change), the version detection and download URL constants are at the top of `apk_fetch.py`.
