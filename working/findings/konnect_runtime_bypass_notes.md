---
name: Konnect runtime bypass notes
description: All the operational knowledge for running the Kohler Konnect Android app inside a controlled (intercepting) environment — what defenses it has, what bypasses we use for each, and where to find the artifacts
type: reference
---

Konnect 3.0.1 has multiple defenses against running in an instrumented
environment. The harness combines bytecode-level patches with runtime Frida
hooks to bypass them. Each defense is listed with its symptom, the actual
mechanism, and the bypass.

## Defense layers (in order of execution)

### 1. Pairip license check → "Something went wrong. Check Google Play"

**Symptom**: app shows `Pairip` license-check dialog, dies. Logcat shows
`LicenseClient` activity.

**Mechanism**: Pairip's `LicenseClient.initializeLicenseCheck` queries
`getInstallerPackageName()`. If the result isn't `com.android.vending`, it
shows the Play Store dialog and exits.

**Bypass**:
- `adb install-multiple -i com.android.vending base.apk split_*.apk` — sets
  the installer package at install time. This is permanent until the user
  uninstalls.
- `frida_bypass.js` also hooks `LicenseClient.initializeLicenseCheck` and
  `performLocalInstallerCheck` as belt-and-suspenders, in case the
  installer-package setting is rejected (signing cert mismatch on the
  patched APK).

### 2. Konnect's custom root check → "This phone can't be used for Kohler Konnect app"

**Symptom**: app reaches SplashActivity, shows `AlertDialog` with the
rooted-or-altered text, doesn't advance.

**Mechanism**: `SplashActivity.onCreate` calls `new Is.b(this).n()` — the
class `Is.b` is a Konnect-internal root detector. `n()` ORs together calls
to `j()`, `h()`, `b("su")`, `c()`, `e()`, `l()`, `g()`, `f()`, etc. — each
checking for a different "rooted" indicator. On a typical AVD or Magisk
phone, several return true.

**Bypass attempts that DID NOT work**:
- Frida hook `Is.b.n.implementation = function() { return false; }` —
  installs successfully (we verified via `getDeclaredMethods()`), but
  doesn't fire when `Is.b.n` is called from `onCreate`. Tested with
  `Java.deoptimizeEverything()`, `Java.classFactory.loader` switched to the
  app's `PathClassLoader`, and explicit hooks on all the helper methods.
  Cause: ART JIT-inlined the helper methods directly into `n()`, and our
  per-method hooks don't get walked.
- Deleting `/system/xbin/su` — makes `b("su")` return false but the other
  checks (`c()` for test-keys build, `f()` for dangerous props, etc.) still
  return true.

**Bypass that WORKS**: apktool-level smali patch. Replace `Is.b.n()`'s body
with a static `return false`. See `credential-extraction/scripts/apk_patch.py`
and the saved smali in `credential-extraction/patches/`. The output is
`credential-extraction/konnect-apk-patched/`, installed via
`make apk-install-patched`.

Two gotchas during apktool rebuild:
1. apktool sees the original APK's `<meta-data android:resource="@null"/>`
   for `default_notification_icon` and rewrites it as `@null`, which then
   fails to rebuild. `apk_patch.py` strips that line.
2. The patched base.apk must be re-signed with a debug keystore, AND every
   split APK in the bundle must be re-signed with the **same** keystore —
   Android rejects bundles whose split signers don't match.

### 3. SSL pinning on app's HTTPS connections

**Symptom**: mitmproxy intercepts a connection, presents its CA, app refuses
("CertificateException" or similar in logcat).

**Mechanism**: Standard OkHttp + X509TrustManager pinning.

**Bypass**: `frida_bypass.js` hooks `javax.net.ssl.SSLContext.init` and
`com.android.org.conscrypt.TrustManagerImpl.verifyChain` to no-op. Both fire
frequently in logcat ("SSLContext.init bypassed", "TrustManagerImpl.verifyChain
bypassed for: <host>"). Combined with the mitmproxy CA installed into
`/system/etc/security/cacerts/<hash>.0`, every TLS connection from the app
is interceptable.

### 4. APIM mTLS — "Invalid client certificate"

**Symptom**: mitmproxy CAN intercept the TLS handshake but the gateway
returns `HTTP/1.1 403 Invalid client certificate` and the body is empty.
Konnect's UI shows "This operation could not be completed, Please try
again." and doesn't open the B2C sign-in WebView.

**Mechanism**: Kohler's APIM gateway
(`az-amer-prod-kohlerkonnect-apim.azure-api.net`) requires mutual TLS —
the client must present a valid X.509 certificate during the TLS handshake.
The cert is `res/raw/app_certificate.p12` (extracted from `base.apk`).
Subject: `C=us, ST=Wisconsin, O=Kohler Co., CN=apim-prod-us`.

**Bypass**: configure mitmproxy with `--set client_certs=<pem>` so it
presents the cert when proxying upstream to APIM. The PEM is generated from
the .p12 by `credential-extraction/scripts/extract_client_cert.py`. The
password (`d6jaqQ1nJxFAuXs`) was captured via Frida hooks on `KeyStore.load`.

Note: the PKCS12 uses RC2-40-CBC encryption, which modern OpenSSL 3.x
disables by default. The extract script passes `-provider legacy
-provider default` to enable it.

### 5. Proxy detection (mostly absent in Konnect, but worth knowing)

Konnect doesn't appear to actively detect proxies — it honors the Android
system proxy setting and routes through it normally. **Important**: a
previous version of `frida_bypass.js` had a "proxy detection bypass" section
that hid `System.getProperty("http.proxyHost")` etc. from the app. That was
counterproductive — Konnect's OkHttp uses those properties to DECIDE
whether to proxy, so hiding them made traffic skip mitmproxy entirely. The
bypass is disabled (kept as a labeled comment block in `frida_bypass.js`).

## Operational sequence (end-to-end)

```bash
# One-time setup (per machine)
brew install --cask android-commandlinetools          # sdkmanager + avdmanager + cmdline-tools
brew install openjdk                                   # JDK for keytool / sdkmanager
brew install apktool mitmproxy android-platform-tools jadx jq xz
sdkmanager "platform-tools" "emulator" "build-tools;35.0.0" \
           "system-images;android-30;google_apis;arm64-v8a"
avdmanager create avd -n KohlerExtraction \
    -k "system-images;android-30;google_apis;arm64-v8a" -d pixel_5

# Per-session
emulator -avd KohlerExtraction -writable-system -no-snapshot &  # boot
cd credential-extraction
make secrets-link                       # .env → /Volumes/ring/env/kohler.env
make apk-patch                          # one-time per Konnect APK version
make apk-install-patched                # one-time per emulator
make emulator-frida-setup
make emulator-mitmproxy-setup
make capture-pfx-password               # one-time, captures into env
make extract-client-cert                # converts .p12 → PEM for mitmproxy
make emulator-token-capture             # main capture loop
# tap Sign In in the emulator window
# Ctrl-C when done
```

## File locations

| Artifact | Where |
|----------|-------|
| Original APK (unsigned by Kohler) | `credential-extraction/konnect-apk/` (LFS) |
| Patched APK (signed by us) | `credential-extraction/konnect-apk-patched/` |
| Smali patch reference | `credential-extraction/patches/Is_b_n_return_false.smali` |
| mTLS PEM (cert + key) | `~/Library/Caches/kohler-anthem/client-certs/app_certificate.pem` (mode 0600) |
| Captured `/token/api/v1/token/` JWTs | `~/Library/Caches/kohler-anthem/token-captures/<ts>/flows.mitm` |
| All secrets | `/Volumes/ring/env/kohler.env` |
| frida_bypass.js | `credential-extraction/scripts/frida_bypass.js` |

## What the harness can capture today

End-to-end (from a clean state): mTLS to APIM works, the GET
`/token/api/v1/token/` returns the **service-account JWT** (B2C ROPC token
for `admin.user@kohler.com`). See `auth_architecture_2026-05-10.md` for the
decoded payload and what it tells us about the rewrite plan.

The actual user sign-in via the B2C_1A_signin WebView wasn't yet driven to
completion in the 2026-05-10 session — the WebView didn't appear to open
after the 201 was received. Likely Konnect needs additional state (per-
customer config from another APIM call) before opening the WebView. The
mTLS-and-cert-cleared pipeline is in place; just need to follow Konnect's
next API call after the 201 in a future session.
