# Credential extraction & APIM `/token` capture harness

This directory's tools do two related things:

1. **Capture the live `/token` GET** the Kohler Konnect app sends to the
   Kohler APIM gateway. Returns a service-account JWT that the library can
   use against `/commands/*` endpoints.
2. **Extract the static credentials** the app uses (APIM mTLS client cert,
   subscription keys, audience IDs).

Both run against a rooted Android Virtual Device (AVD) with bytecode-patched
Konnect, Frida-based pinning bypass, and mitmproxy in the middle.

## Quick start

```bash
git clone <repo>
cd kohler-anthem
git lfs pull --include='credential-extraction/konnect-apk/'   # pull the Konnect APK
cd credential-extraction
make deps             # brew + pip + SDK components — file-target driven; only installs what's missing
make secrets-init     # copies env.example → /Volumes/ring/env/kohler.env
make secrets-link     # creates .env symlink in repo root
$EDITOR /Volumes/ring/env/kohler.env   # fill in YOUR_VALUE_HERE blanks
make secrets-check    # verify required keys are populated
make harness          # run the whole pipeline
```

`make harness` is idempotent — re-running picks up where the last run left
off (AVD already exists? skip create. APK already patched? skip patch). On
Ctrl-C, every subprocess gets cleanly torn down.

Each run writes `~/Library/Caches/kohler-anthem/harness-runs/<ts>/` with
`run.log`, `versions.json`, and `summary.json` — diagnose failures from
those without re-running.

## What the harness does

1. **prereqs** — verifies adb, frida, mitmdump, openssl, venv are present.
2. **secrets-check** — `.env` symlink resolves to a populated file.
3. **apk-verify** — the in-repo `konnect-apk/` matches its `manifest.json`
   sha256s. If LFS hasn't been pulled, fails fast with a `git lfs pull` hint.
4. **apk-patch** — apktool decompiles `base.apk`, replaces `Is.b.n()`'s body
   with `return false` (defeats Konnect's runtime root check that Frida hooks
   can't reach due to ART JIT inlining), strips a broken `@null` resource
   ref, rebuilds, zipaligns, and signs base + all splits with the same debug
   keystore. Output: `konnect-apk-patched/`.
5. **avd-setup** — installs missing Android SDK components (emulator,
   system-image, build-tools) via sdkmanager, creates the `KohlerExtraction`
   AVD (Pixel 5, Android 11, google_apis, arm64-v8a) if missing, boots it
   with `-writable-system`, waits for boot, runs `adb root` + `adb remount`.
6. **frida-setup** — downloads the `frida-server` version-matched to the
   host's `frida-tools`, pushes to `/data/local/tmp/frida-server`, starts
   detached. Skips re-push if the on-device md5 already matches.
7. **apk-install-patched** — `adb install-multiple -i com.android.vending`
   (the `-i` flag spoofs the installer-package so Pairip's license check is
   happy), then auto-grants `ACCESS_FINE_LOCATION` + `ACCESS_COARSE_LOCATION`
   so Konnect's `LocationPermissionActivity` doesn't block.
8. **mitmproxy-setup** — caches the mitmproxy CA (cert AND private key) in
   `~/Library/Caches/kohler-anthem/mitmproxy-ca/`, verifies validity, pushes
   to `/system/etc/security/cacerts/<subject-hash>.0`, sets the Android
   global proxy to `10.0.2.2:8080`.
9. **capture-pfx-password (conditional)** — only fires if
   `KOHLER_APIM_CLIENT_CERT_PASSWORD` is missing from the env. Spawns Konnect
   under Frida, reads the `char[]` arg to `KeyStore.load(InputStream,
   char[])`, prints the recovered password.
10. **extract-client-cert** — unzips `res/raw/app_certificate.p12` from
    `konnect-apk/base.apk`, decrypts with OpenSSL (`-provider legacy
    -provider default` for the RC2-40-CBC encryption), writes the PEM to
    `$KOHLER_APIM_CLIENT_CERT_PEM` at mode 0o600.
11. **token-capture** — launches `mitmdump` (with the extracted PEM as the
    upstream client cert, so mTLS to APIM still works) + `frida -U -f
    com.kohler.hermoth -l frida_bypass.js` in separate process groups.
    Auto-taps "Continue" on `LocationPermissionActivity` then "Sign In" on
    `AzureLoginActivity` — that click triggers the `GET /token/api/v1/token/`
    that captures the service-account JWT. On Ctrl-C (or `--wait-seconds`
    timeout), signals both process groups, parses `flows.mitm`, atomic-writes
    `<run>/token_capture.json`.

## Prerequisites

Everything below is installed by `make deps`:

| Tool | Source | Purpose |
|------|--------|---------|
| `adb` | `brew install --cask android-platform-tools` | Device control |
| `apktool` | `brew install apktool` | APK decompile/rebuild for the root-check patch |
| `jadx` | `brew install jadx` | APK decompiler (legacy static extraction) |
| `jq` | `brew install jq` | JSON processor |
| `mitmproxy` | `brew install mitmproxy` + venv | HTTPS interception + Python flow parser |
| `xz` | `brew install xz` | Decompress `frida-server` |
| `sdkmanager` + `avdmanager` + emulator | `brew install --cask android-commandlinetools` + `sdkmanager` | AVD lifecycle |
| `system-images;android-30;google_apis;arm64-v8a` | sdkmanager | The AVD's OS image |
| `build-tools;35.0.0` | sdkmanager | `zipalign` + `apksigner` for APK resigning |
| `openjdk` | `brew install openjdk` | `keytool` for the debug-keystore + JAVA_HOME |
| `frida-tools` | venv pip | App instrumentation |
| `openssl` | macOS bundled | mitmproxy CA hashing + PKCS12 → PEM conversion |

## Layout

```
/Volumes/ring/env/kohler.env        # ALL secrets (mode 0600). Symlinked here as .env.
~/Library/Caches/kohler-anthem/     # binary cache, owner-only perms
  mitmproxy-ca/                      # cached CA + private key (mode 0600)
  client-certs/                      # extracted APIM mTLS PEM
  konnect-apk-staging/               # scratch space for `make apk-update`
  token-captures/<timestamp>/        # one dir per /token-capture session
  harness-runs/<timestamp>/          # run.log + versions.json + summary.json
  ui-dumps/                          # uiautomator dumps + screenshots
  doctor/                            # diagnostic snapshots

credential-extraction/
  Makefile                          # entry point (see `make help`)
  env.example                        # checked-in template for kohler.env
  konnect-apk/                       # CANONICAL APK (git-LFS tracked)
    base.apk
    split_config.arm64_v8a.apk
    split_config.en.apk
    split_config.xxxhdpi.apk
    manifest.json                   # version + per-file sha256
  konnect-apk-patched/              # regenerable; .gitignored
    base.apk (patched + resigned)
    split_config.*.apk (resigned with the same debug key)
    manifest.json
  patches/
    Is_b_n_return_false.smali       # the patch we apply
  scripts/
    env_lib.py                      # shared lib: env, tools, perms, atomic I/O
    harness.py                      # master orchestrator + run logging
    apk_fetch.py                    # always-latest APK fetch + manifest verify
    apk_patch.py                    # apktool decompile + smali patch + resign
    avd_setup.py                    # AVD create/start/remount
    frida_setup.py                  # push frida-server (version-locked)
    emulator_apk_install.py         # install split APKs + permission grant
    mitmproxy_setup.py              # CA install + proxy + --uninstall
    capture_pfx_password.py         # Frida hook on KeyStore.load
    extract_client_cert.py          # PKCS12 → PEM for upstream mTLS
    token_capture.py                # mitmdump+Frida w/ process groups + UI drive
    konnect_signin.py               # safe-text auto-type (whitelist)
    record_konnect_signin.py        # UI recorder for sign-in automation
    secrets_init.py                 # scaffold env file
    secrets_link.py                 # create .env symlink
    secrets_check.py                # validate required keys
    doctor.py                       # diagnostics snapshot
    apim_capture.py                 # legacy: Frida-only APIM grab
    credentials_extract.py          # legacy: static APK extraction
    credentials_generate.py         # legacy: kohler-credentials.yaml
    frida_bypass.js                 # license/SSL/root/emulator bypass
    tools_check.py                  # prereq verification
    emulator_check.py               # emulator + frida-server check
```

## Make targets

```
First-time setup:
  make deps             Install brew + pip tools + SDK components (idempotent)
  make secrets-init     Scaffold env file from env.example
  make secrets-link     Symlink .env → /Volumes/ring/env/kohler.env
  make secrets-check    Verify required env keys are populated

Top-level:
  make harness          End-to-end APIM /token capture (AVD + patched APK + Frida + mTLS)
  make all              Legacy APIM-key extraction
  make doctor           One-shot diagnostics snapshot
  make ci-smoke         CI-safe steps (deps + tools-check)

Individual steps:
  make tools-check                 Verify tool presence
  make sdk-components              Install Android SDK components only
  make apk-verify                  Hash-check the in-repo APK
  make apk-update                  Refresh the in-repo APK from APKPure (review before commit)
  make apk-patch                   Apktool-patch + resign → konnect-apk-patched/
  make avd-setup                   Create + start the KohlerExtraction AVD
  make avd-recreate                Delete + recreate the AVD
  make emulator-setup              Alias for avd-setup
  make emulator-check              Check device + frida-server
  make emulator-frida-setup        Push frida-server
  make emulator-apk-install        Install the (unpatched) Konnect APK
  make apk-install-patched         Install the patched APK with -i com.android.vending
  make capture-pfx-password        Recover the PKCS12 password via Frida
  make extract-client-cert         PKCS12 → PEM for upstream mTLS
  make emulator-mitmproxy-setup    Install CA + set Android proxy
  make emulator-mitmproxy-clear    Clear Android proxy (CA stays)
  make emulator-mitmproxy-uninstall Remove CA + clear proxy (security hygiene)
  make emulator-konnect-signin     Pre-grant perms; print sign-in instructions
  make record-konnect-signin       Record sign-in UI for replay
  make emulator-token-capture      Run mitmdump+Frida to capture /token

Cleanup:
  make clean              Remove .build/
  make clean-emulator     Stop + delete the KohlerExtraction AVD
  make clean-cache        Wipe persistent cache (DANGEROUS — confirms)
  make clean-all          clean + clean-emulator (cache preserved)
```

## What you'll get

| Artifact | Path | When |
|----------|------|------|
| Konnect APK | `credential-extraction/konnect-apk/*.apk` (git-LFS) | checked in; `git lfs pull` |
| APK manifest | `credential-extraction/konnect-apk/manifest.json` | checked in |
| Patched APK | `credential-extraction/konnect-apk-patched/` | `make apk-patch` |
| mitmproxy CA | `~/Library/Caches/kohler-anthem/mitmproxy-ca/mitmproxy-ca-cert.pem` | `make emulator-mitmproxy-setup` |
| APIM client cert PEM | `~/Library/Caches/kohler-anthem/client-certs/app_certificate.pem` | `make extract-client-cert` |
| `/token` capture | `~/Library/Caches/kohler-anthem/token-captures/<timestamp>/token_capture.json` | `make emulator-token-capture` |
| Raw mitm flows | `<ts>/flows.mitm` | (same) |
| Frida log | `<ts>/frida.log` | (same) |
| Run summary | `~/Library/Caches/kohler-anthem/harness-runs/<ts>/{summary,versions,run.log}` | `make harness` |
| APIM key (legacy) | `.build/captured_apim_key.json` | `make emulator-apim-capture` |

## Security notes — read before regular use

**The emulator becomes MITM-trusted indefinitely.** `mitmproxy_setup.py`
installs the mitmproxy CA into `/system/etc/security/cacerts/`. Any process
on the host that listens on `10.0.2.2:8080` can decrypt the emulator's TLS
traffic until the cert is removed. Don't use the `KohlerExtraction` device
for unrelated work. Run `make emulator-mitmproxy-uninstall` when you're done
capturing — or `make clean-emulator` to delete the whole device.

**Captured tokens are real.** `token_capture.json` and `flows.mitm` contain
the live access_token, refresh_token, and any client-assertion JWT. They're
written mode 0600 in a 0700 directory under your home cache, but treat them
like passwords.

**The Konnect APK is git-LFS pinned in the repo, not pulled live.** The
checked-in version's SHA-256s are in `konnect-apk/manifest.json` and verified
on every `make apk-verify` (which `harness` depends on). To refresh from
APKPure, run `make apk-update` — it downloads to a staging area, refuses to
overwrite if the new bundle is missing ABI splits that the current one has,
and updates the manifest. Review the diff and `git lfs ls-files` before
committing.

**The `.env` symlink targets a file that `direnv`-style tools will load into
every shell.** That includes `KOHLER_PASSWORD` and any other sensitive keys.
If you run untrusted scripts in this repo's shell, those env vars are
visible to them.

## Running individual steps

Each step in `harness.py` is a standalone Make target — you can re-run any
one without redoing the whole pipeline. Common partial workflows:

```bash
# Emulator's already running and APK's installed; just (re)capture /token
make emulator-mitmproxy-setup
make emulator-token-capture

# Update APK to the latest, re-patch, reinstall on the running emulator
make apk-update              # downloads, ABI-checks, replaces konnect-apk/
git diff credential-extraction/konnect-apk/manifest.json   # review
make apk-patch               # re-patch the new APK
make apk-install-patched     # install the refreshed APK

# Diagnose a problem
make doctor    # snapshot of host + emulator state
cat ~/Library/Caches/kohler-anthem/harness-runs/<latest>/summary.json
```

## Troubleshooting

### `[MISSING] frida` from tools-check, but it's installed

frida-tools is installed in the **project venv** at `../.venv/bin/frida`,
not on PATH globally. The scripts and Makefile use `env_lib.find_frida()`
to resolve it. If you're calling something by hand, use the venv's binary.

### APKPure download fails / serves an arch-narrowed bundle

`make apk-update` is the only path that talks to APKPure. The default
harness flow uses the in-repo APK, so APKPure being down doesn't affect
normal runs. If `apk-update` fails or refuses (missing ABI splits), the
in-repo APK stays untouched.

### "APK content missing" / "LFS POINTER (not pulled)"

The Konnect APK is git-LFS-tracked. Either you cloned without LFS, or
LFS wasn't initialized. Recover with:

```bash
git lfs install      # one-time per-machine setup
git lfs pull --include='credential-extraction/konnect-apk/'
```

### mitmproxy CA install fails with "/system is still not writable"

The AVD needs to be booted with `-writable-system` (the `avd_setup.py`
script always passes this flag) and remounted as rw. If `make
emulator-mitmproxy-setup` fails:

```bash
adb root && adb remount
make emulator-mitmproxy-setup
```

If `adb remount` itself fails, the AVD boot flag was missing — recreate it
with `make avd-recreate`.

### Konnect crashes on "rooted device" detection or shows the "Please try
again" toast

`Is.b.n()` is patched at the bytecode level in `make apk-patch`, so the
in-app dialog "This phone can't be used for Kohler Konnect app" should not
appear. If it does:

1. Confirm the patched APK is installed: `adb shell pm dump
   com.kohler.hermoth | grep versionName`
2. Verify the install used the patched bundle:
   `cat ~/Library/Caches/kohler-anthem/harness-runs/<latest>/run.log | grep
   apk-install`
3. If still failing, rerun `make apk-patch && make apk-install-patched`.

For Frida-side bypass updates (License/SSL/Build-properties/SystemProperties/
TelephonyManager), see `frida_bypass.js`. Watch `frida.log` in the active
token-capture session dir to see which bypass fired.

### "HASH MISMATCH" from apk-verify

The on-disk APK doesn't match what `manifest.json` says it should be. Either
the file was corrupted/edited, or `manifest.json` is stale. Recover with:

```bash
git checkout credential-extraction/konnect-apk/
git lfs pull --include='credential-extraction/konnect-apk/'
make apk-verify
```

### Port 8080 already in use

A stray `mitmdump` from a prior run is still listening. `lsof -i :8080` to
find the PID, then kill it. The harness's `mitmproxy_setup.py` already
attempts cleanup on Ctrl-C, but it can be bypassed by a hard kill.

## How the auth-rewrite work uses these outputs

The captured `/token` request from the APIM gateway (`GET
https://az-amer-prod-kohlerkonnect-apim.azure-api.net/token/api/v1/token/`)
returns a service-account JWT for `admin.user@kohler.com`. With:

- the extracted mTLS client cert PEM (`KOHLER_APIM_CLIENT_CERT_PEM`),
- the APIM subscription key (`KOHLER_APIM_TOKEN_KEY`),

the library can call APIM directly — no per-user OAuth flow needed for
`/commands/*` endpoints. See `working/findings/auth_architecture_2026-05-10.md`
for the full architecture writeup.
