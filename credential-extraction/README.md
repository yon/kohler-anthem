# Credential extraction & B2C `/token` capture harness

This directory's tools do two related things:

1. **Capture the live `/token` POST** the Kohler Konnect app sends to
   `B2C_1A_signin` — the missing piece for the auth rewrite.
2. **Extract the static credentials** the app uses (client_id, APIM key,
   etc.) for read-only flows.

Both run against a rooted Genymotion emulator with Frida-based pinning
bypass and mitmproxy in the middle.

## Quick start

```bash
git clone <repo>
cd kohler-anthem
git lfs pull --include='credential-extraction/konnect-apk/'   # pull the Konnect APK
cd credential-extraction
make deps             # brew + pip — file-target driven; only installs what's missing
make secrets-init     # copies env.example → /Volumes/ring/env/kohler.env
make secrets-link     # creates .env symlink in repo root
$EDITOR /Volumes/ring/env/kohler.env   # fill in YOUR_VALUE_HERE blanks
make secrets-check    # verify required keys are populated
make harness          # run the whole pipeline
```

`make harness` is idempotent — re-running picks up where the last run left off
(emulator already exists? skip create. APK already cached at the latest
version? skip download). On Ctrl-C, every subprocess gets cleanly torn down.

Each run writes `~/Library/Caches/kohler-anthem/harness-runs/<ts>/` with
`run.log`, `versions.json`, and `summary.json` — diagnose failures from
those without re-running.

## What the harness does

1. Verifies tools + the env file are in place (`secrets-check`).
2. Verifies the in-repo Konnect APK (`credential-extraction/konnect-apk/`,
   git-LFS tracked) matches its `manifest.json` SHA-256s. If LFS hasn't
   been pulled, fails fast with a `git lfs pull` hint.
3. Signs into Genymotion by writing credentials to
   `~/.Genymobile/Genymotion/settings.json` (mode 0600) — NOT via `gmtool
   --password=…` argv, so the password doesn't show up in `ps`.
4. Creates and starts the `KohlerExtraction` Android 11 device.
5. Pushes the matching `frida-server` (version-locked to your installed
   `frida-tools`). Skips re-push if the on-device md5 already matches.
6. Installs the Konnect APK with an ABI pre-flight (warns if the device's
   ABI isn't in the bundle).
7. Caches the mitmproxy CA (cert AND private key) in
   `~/Library/Caches/kohler-anthem/mitmproxy-ca/` so the same CA survives
   restarts. Verifies validity, computes the OpenSSL old-style subject
   hash, pushes to `/system/etc/security/cacerts/<hash>.0`, verifies the
   file exists, sets the Android global proxy.
8. Launches `mitmdump` + `frida -U -f com.kohler.hermoth -l frida_bypass.js`
   in separate process groups. Waits for the mitmdump port to accept
   connections (not a fixed sleep) before launching Frida.
9. Waits for you to sign in inside the emulator.
10. On Ctrl-C, signals both process groups, lets mitmdump flush, parses the
    flow file (resilient to partial flows), atomic-writes
    `<run>/token_capture.json`.

## Prerequisites

### Automated by `make deps`

| Tool | Why |
|------|-----|
| `gmtool` (Genymotion Desktop) | Rootable Android emulator |
| `adb` (android-platform-tools) | Device control |
| `jadx` | APK decompiler |
| `jq` | JSON processor |
| `mitmproxy` (also `mitmdump`) | HTTPS interception |
| `xz` | Decompress `frida-server` |
| `frida-tools` (pip, into project venv) | App instrumentation |
| `mitmproxy` (pip, into project venv) | Python API for parsing flows |
| `openssl` | mitmproxy CA hash + validity check (macOS bundles it) |

### Manual: Genymotion account sign-up

`brew install --cask genymotion` installs the binary. To activate the trial,
you need a Genymotion account; sign up once at
https://www.genymotion.com/account/login/ for the 30-day Desktop trial, then
put credentials in `/Volumes/ring/env/kohler.env`:

```env
export GENYMOTION_EMAIL=you@example.com
export GENYMOTION_PASSWORD=...
export GENYMOTION_LICENSE_KEY=     # optional, only if you bought a license
```

`gmtool admin create` returns `A license is required` on the free
Personal-use tier — the Desktop trial is what unlocks the harness automation.

## Layout

```
/Volumes/ring/env/kohler.env        # ALL secrets (mode 0600). Symlinked here as .env.
~/Library/Caches/kohler-anthem/     # binary cache, owner-only perms
  mitmproxy-ca/                      # cached CA + private key (mode 0600)
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
  scripts/
    env_lib.py                      # shared lib: env, tools, perms, atomic I/O
    harness.py                      # master orchestrator + run logging
    apk_fetch.py                    # always-latest APK + signing pin
    genymotion_signin.py            # password off argv
    emulator_setup.py               # gmtool admin create/start
    frida_setup.py                  # push frida-server (version-locked)
    emulator_apk_install.py         # install split APKs + ABI preflight
    mitmproxy_setup.py              # CA install + proxy + --uninstall
    token_capture.py                # mitmdump+Frida w/ process groups
    konnect_signin.py               # safe-text auto-type (whitelist)
    record_konnect_signin.py        # UI recorder for sign-in automation
    secrets_init.py                 # scaffold env file
    secrets_link.py                 # create .env symlink
    secrets_check.py                # validate required keys
    doctor.py                       # diagnostics snapshot
    apim_capture.py                 # legacy: Frida-only APIM grab
    credentials_extract.py          # legacy: static APK extraction
    credentials_generate.py         # legacy: kohler-credentials.yaml
    frida_bypass.js                 # license/SSL/root/emulator/proxy bypass
    tools_check.py                  # prereq verification
    emulator_check.py               # emulator + frida-server check
```

## Make targets

```
First-time setup:
  make deps             Install brew + pip tools (idempotent)
  make secrets-init     Scaffold env file from env.example
  make secrets-link     Symlink .env → /Volumes/ring/env/kohler.env
  make secrets-check    Verify required env keys are populated

Top-level:
  make harness          Full B2C_1A_signin /token capture pipeline
  make all              Legacy APIM-key extraction
  make doctor           One-shot diagnostics snapshot
  make ci-smoke         CI-safe steps (deps + tools-check)

Individual steps:
  make tools-check                 Verify tool presence
  make apk-verify                  Hash-check the in-repo APK
  make apk-update                  Refresh the in-repo APK from APKPure (manual, review before commit)
  make genymotion-signin           Sign in to Genymotion
  make emulator-setup              Create + start KohlerExtraction device
  make emulator-check              Check device + frida-server
  make emulator-frida-setup        Push frida-server
  make emulator-apk-install        Install Konnect APK
  make emulator-mitmproxy-setup    Install CA + set Android proxy
  make emulator-mitmproxy-clear    Clear Android proxy (CA stays)
  make emulator-mitmproxy-uninstall Remove CA + clear proxy (security hygiene)
  make emulator-konnect-signin     Pre-grant perms; print sign-in instructions
  make record-konnect-signin       Record sign-in UI for replay
  make emulator-token-capture      Run mitmdump+Frida to capture /token

Cleanup:
  make clean              Remove .build/
  make clean-emulator     Stop + delete the KohlerExtraction device
  make clean-cache        Wipe persistent cache (DANGEROUS — confirms)
  make clean-all          clean + clean-emulator (cache preserved)
```

## What you'll get

| Artifact | Path | When |
|----------|------|------|
| Konnect APK | `credential-extraction/konnect-apk/*.apk` (git-LFS) | checked in; `git lfs pull` |
| APK manifest | `credential-extraction/konnect-apk/manifest.json` | checked in |
| mitmproxy CA | `~/Library/Caches/kohler-anthem/mitmproxy-ca/mitmproxy-ca-cert.pem` | `make emulator-mitmproxy-setup` |
| `/token` capture | `~/Library/Caches/kohler-anthem/token-captures/<timestamp>/token_capture.json` | `make emulator-token-capture` |
| Raw mitm flows | `<ts>/flows.mitm` | (same) |
| Frida log | `<ts>/frida.log` | (same) |
| Run summary | `~/Library/Caches/kohler-anthem/harness-runs/<ts>/{summary,versions,run.log}` | `make harness` |
| APIM key (legacy) | `.build/captured_apim_key.json` | `make emulator-apim-capture` |

## Security notes — read before regular use

**The emulator becomes MITM-trusted indefinitely.** `mitmproxy_setup.py`
installs the mitmproxy CA into `/system/etc/security/cacerts/`. Any process
on the host that listens on `10.0.3.2:8080` can decrypt the emulator's TLS
traffic until the cert is removed. Don't use the `KohlerExtraction` device
for unrelated work. Run `make emulator-mitmproxy-uninstall` when you're done
capturing — or `make clean-emulator` to delete the whole device.

**Captured tokens are real.** `token_capture.json` and `flows.mitm` contain
the live access_token, refresh_token, authorization code, and any
`client_assertion` JWT. They're written mode 0600 in a 0700 directory under
your home cache, but treat them like passwords.

**The Genymotion license key is briefly visible in `ps`.** `gmtool license
register <key>` is argv-only — there's no stdin variant. Account email /
password are written to `settings.json` (mode 0600), not passed on argv.

**The Konnect APK is git-LFS pinned in the repo, not pulled live.** The
checked-in version's SHA-256s are in `konnect-apk/manifest.json` and verified
on every `make apk-verify` (which `harness` and `emulator-apk-install`
depend on). To refresh from APKPure, run `make apk-update` — it downloads
to a staging area, refuses to overwrite if the new bundle is missing ABI
splits that the current one has, and updates the manifest. Review the diff
and `git lfs ls-files` before committing.

**The `.env` symlink targets a file that `direnv`-style tools will load into
every shell.** That includes `KOHLER_PASSWORD` and `GENYMOTION_PASSWORD`.
If you run untrusted scripts in this repo's shell, those env vars are
visible to them.

## Running individual steps

Each step in `harness.py` is a standalone Make target — you can re-run any
one without redoing the whole pipeline. Common partial workflows:

```bash
# Emulator's already running and APK's installed; just (re)capture /token
make emulator-mitmproxy-setup
make emulator-token-capture

# Update APK to the latest, reinstall on the running emulator
make apk-update              # downloads, ABI-checks, replaces konnect-apk/
git diff credential-extraction/konnect-apk/manifest.json   # review
make emulator-apk-install    # install the refreshed APK

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

Genymotion's Android 11+ image sometimes requires `adb disable-verity` +
`adb reboot` before `/system` can be remounted writable. The harness will
tell you to do this:

```bash
adb root && adb disable-verity && adb reboot
# wait for boot to complete
make emulator-mitmproxy-setup
```

### Konnect crashes on "rooted device" detection

`frida_bypass.js` covers the known detection paths (Is.b, File.* checks,
Build properties, SystemProperties, TelephonyManager, proxy detection, SSL
pinning). If a new detection is added in a future APK version, add the
relevant hook to `frida_bypass.js`. To see what's failing, watch
`frida.log` in the active token-capture session dir.

### Genymotion trial expired

`make genymotion-signin` will report the trial state. Options:

- Buy a paid Desktop license, set `GENYMOTION_LICENSE_KEY`.
- Sign up a new account (different email) — Genymotion enforces one trial
  per account, not per machine.
- Switch to a different rooted emulator (Android Studio AVD + Magisk root)
  — would require rewriting the gmtool-specific scripts.

### "HASH MISMATCH" from apk-verify

The on-disk APK doesn't match what `manifest.json` says it should be. Either
the file was corrupted/edited, or `manifest.json` is stale. Recover with:

```bash
git checkout credential-extraction/konnect-apk/
git lfs pull --include='credential-extraction/konnect-apk/'
make apk-verify
```

## How the auth-rewrite work uses these outputs

The captured `/token` request answers the open question from the May 2026
spike: which client-auth mechanism does Konnect actually use against
`B2C_1A_signin`?

The captured `request_body_parsed` tells us whether to implement:

- `client_secret` (look for `client_secret=...` in the body)
- `client_assertion` + JWT-bearer (look for `client_assertion`,
  `client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer`,
  signed with `auth_certificate.pfx`)
- Something else entirely

Once that's known, update `KohlerOAuthAuth.acquire_token()` in
`src/kohler_anthem/auth.py` on the `feat/b2c-1a-signin-auth` branch and
re-run `make health-check` against `/commands/gcs/*` to verify the 403 is
gone.

See `working/findings/kohler_api_auth_parked.md` and
`working/plans/2026-05-10_emulator_token_capture.md` for the broader
context.
