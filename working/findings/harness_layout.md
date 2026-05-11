---
name: Emulator + Frida + mitmproxy capture harness
description: How the APIM /token capture pipeline is wired — what's automated, what's still manual, and where artifacts land
type: reference
---

The capture harness was built on 2026-05-10 (branch `feat/emulator-token-capture`) to make the parked auth-rewrite work resumable end-to-end. Single command: `make harness` from `credential-extraction/`.

## What runs autonomously

1. **prereqs** — `harness.py` verifies adb, frida (in venv), mitmdump, openssl, and the project venv.
2. **secrets-check** — confirms the `.env` symlink resolves to a populated file.
3. **apk-verify** — `apk_fetch.py --verify` hashes the in-repo `konnect-apk/` against `manifest.json`.
4. **apk-patch** — `apk_patch.py` apktool-decompiles `base.apk`, replaces `Is.b.n()` body with `return false`, removes the broken `@null` resource ref, rebuilds, zipaligns, and apksigner-signs base + all splits with the same debug keystore. Output: `konnect-apk-patched/`.
5. **avd-setup** — `avd_setup.py` installs missing Android SDK components (emulator, system-image, build-tools) via sdkmanager, creates the `KohlerExtraction` AVD (Pixel 5, Android 11, google_apis, arm64-v8a) if missing, starts the emulator with `-writable-system`, waits for boot, runs `adb root` + `adb remount`.
6. **frida-setup** — `frida_setup.py` downloads the frida-server binary matching the host's frida-tools version, pushes to `/data/local/tmp/`, starts it detached.
7. **apk-install-patched** — `emulator_apk_install.py --patched` does `adb install-multiple -i com.android.vending` (the `-i` flag spoofs the installer-package so Pairip's license check is satisfied), then auto-grants `ACCESS_FINE_LOCATION` + `ACCESS_COARSE_LOCATION`.
8. **mitmproxy-setup** — `mitmproxy_setup.py` boots mitmdump briefly to generate the CA, computes the OpenSSL old-style subject hash, pushes to `/system/etc/security/cacerts/<hash>.0` with `adb root` + remount, sets the Android global `http_proxy` to `10.0.2.2:8080`.
9. **capture-pfx-password (conditional)** — `capture_pfx_password.py` only fires if `KOHLER_APIM_CLIENT_CERT_PASSWORD` is missing. Spawns Konnect under Frida, reads the `char[]` arg passed to `KeyStore.load(InputStream, char[])`, prints the recovered password.
10. **extract-client-cert** — `extract_client_cert.py` unzips `res/raw/app_certificate.p12` from `konnect-apk/base.apk` and converts it to a PEM via `openssl pkcs12 -provider legacy -provider default` (the .p12 uses RC2-40-CBC, disabled by default in OpenSSL 3.x). Output goes to `$KOHLER_APIM_CLIENT_CERT_PEM`.
11. **token-capture** — `token_capture.py` runs mitmdump with `--set client_certs=<pem>` (so upstream mTLS to the APIM gateway still works) + `save_stream_file`, launches Konnect via `frida -U -f com.kohler.hermoth -l frida_bypass.js`, auto-taps "Continue" on `LocationPermissionActivity` then "Sign In" on `AzureLoginActivity`, waits for Ctrl-C or `--wait-seconds`, parses the flow file for `~h (b2clogin.com|kohlerkonnect-apim) ~p /token`, writes structured JSON.

## What still needs manual interaction (today)

| Step | Why | How to automate later |
|------|-----|----------------------|
| Konnect login form inside the emulator | UI taps for email/password not recorded yet | After first successful capture, populate `KONNECT_SIGNIN_STEPS` in `konnect_signin.py` using `adb shell uiautomator dump` output. |
| Sign-In click → `/token` fire | The auto-tap fires the click but on a freshly-booted AVD with no cached state, Konnect's downstream call sometimes silently no-ops | Persist Konnect's account-bootstrap state between runs (or pre-populate it) |

## Where things live

- **Secrets:** `/Volumes/ring/env/kohler.env` (symlinked as repo's `.env`). Loaded by direnv (`.envrc` → `dotenv_if_exists`), Make (`-include .env`), and the Python scripts (via `env_lib.load_env`).
- **Binary cache:** `~/Library/Caches/kohler-anthem/`. Survives repo wipes. Sized for the ~70 MB Konnect XAPK (the `/Volumes/ring` sparse-bundle is too small).
- **Plan + findings:** `working/findings/auth_architecture_2026-05-10.md` for the live architecture writeup; `working/findings/kohler_api_auth_parked.md` is the older spike doc (superseded).

## Re-running individual steps

The harness orchestrator is thin — each script also works standalone. Common partial reruns:

```
make apk-verify                  # hash-check the in-repo APK
make apk-patch                   # re-patch + resign
make avd-setup                   # boot the AVD
make emulator-mitmproxy-setup    # re-install CA + proxy (e.g. after device reboot)
make capture-pfx-password        # recover PKCS12 password via Frida
make extract-client-cert         # PKCS12 → PEM
make emulator-token-capture      # capture without re-installing everything
```

The Make targets are documented in `make help` (in `credential-extraction/`).

## Tested?

- `make deps` — installs everything cleanly on a fresh machine (verified 2026-05-10).
- `make tools-check` — green.
- `make apk-fetch --verify` — green against the in-repo LFS-tracked APK.
- `make apk-patch` — produces a working installable patched bundle.
- `make harness --skip-capture` — runs all 10 setup stages green, idempotent on re-run.
- `make emulator-token-capture` — captures `/token/api/v1/token/` 201 with the service-account JWT (verified 2026-05-10).

If APKPure breaks (different anti-bot behavior, URL pattern change), the version detection and download URL constants are at the top of `apk_fetch.py`.
