# Plan: Replace ROPC auth with B2C_1A_signin (OAuth Authorization Code + PKCE)

**Date:** 2026-05-09
**Status:** PHASE 0 PARTIAL — see "Findings from 2026-05-10 Phase 0 attempt" at bottom
**Affects:** `kohler-anthem` (library), `ha-kohler-anthem` (HA component)

---

## Problem Statement

As of early May 2026, Kohler's backend rejects ROPC-issued tokens on
`/platform/api/v1/commands/gcs/*` with HTTP 403. Reads (`/devices/api/...`)
and non-command writes (`POST /platform/api/v1/mobile/settings`) still pass.
Run `make health-check` for the live capability matrix.

**Diagnosed cause** (high confidence; `tests/integration/` in this repo
proves it on each run):

- The captured APIM subscription key is still valid (mobile/settings POST = 201).
- The JWT decodes cleanly with the expected `aud=<api_resource>`, `scp=apiaccess`,
  and `tfp=B2C_1_ROPC_Auth` claims.
- The 403 response carries ASP.NET-style headers (`x-frame-options`,
  `content-security-policy`, etc.) — i.e. it comes from the backend service,
  not from APIM.
- `https://konnectkohler.b2clogin.com/konnectkohler.onmicrosoft.com/B2C_1A_signin/v2.0/.well-known/openid-configuration`
  exists. The same `client_id` is registered for it (the authorize endpoint
  responds 200). The official mobile apps use this interactive policy.
- ROPC tokens lack the `acr`/`amr` auth-context claims that interactive
  flows produce. Microsoft has been deprecating ROPC; many backends have
  followed by gating state-changing operations on interactive tokens only.

**Fix path:** acquire tokens via OAuth 2.0 Authorization Code + PKCE against
`B2C_1A_signin`, mint a long-lived refresh token from the one-time
interactive sign-in, and use that refresh token for all subsequent traffic.
Same `client_id`, same `apim_subscription_key`, same scope (`apiaccess`).

---

## Acceptance Criteria

- [ ] After running `make health-check`, all `/commands/gcs/*` endpoints
      classify as `OK` (or `BAD_REQUEST` for empty-body probes), not
      `BACKEND_FORBIDDEN`.
- [ ] Existing reads continue to work (no regression on `read.*` probes).
- [ ] HA integration setup flow walks the user through one interactive
      browser sign-in; subsequent HA restarts do not require re-auth.
- [ ] Refresh token survives HA restarts (persisted in the config entry).
- [ ] When the refresh token expires or is revoked, HA surfaces a Repairs
      reauth notification rather than silently failing.
- [ ] All 113 existing unit tests still pass.
- [ ] New unit tests cover the PKCE flow, token storage, and refresh behavior.

---

## Tests to Write First (TDD)

### Library (`kohler-anthem`)

1. **`tests/test_auth_pkce.py`** (new)
   - `test_pkce_pair_generates_valid_verifier_and_challenge` — verifier is
     43-128 chars URL-safe; challenge is base64url SHA-256 of verifier.
   - `test_authorize_url_includes_required_params` — client_id, redirect_uri,
     scope, code_challenge, code_challenge_method=S256, response_type=code,
     state, nonce.
   - `test_authorize_url_uses_b2c_1a_signin_policy` — URL points at the
     interactive policy, not ROPC.
   - `test_exchange_code_for_token_persists_refresh_token` — mocks the
     token endpoint and asserts the storage callback is called with the
     refresh token.
   - `test_refresh_token_used_when_present` — stored refresh token short-
     circuits the interactive flow on subsequent connects.
   - `test_refresh_token_rotation` — when the IdP returns a new refresh
     token in the refresh response, the storage callback is called with
     the new value.
   - `test_refresh_failure_raises_reauth_required` — 400 invalid_grant
     translates to a `ReauthRequired` exception (new subclass of
     `AuthenticationError`) rather than a generic failure.

2. **`tests/integration/test_credentials_health.py`** (extend existing)
   - Once the new flow is wired, command-write probes flip from FAIL to
     PASS — same test file, same assertions, just no longer xfail.

### HA component (`ha-kohler-anthem`)

3. **`tests/test_config_flow.py`** (new)
   - `test_user_step_redirects_to_authorize_url`
   - `test_oauth_callback_creates_config_entry_with_refresh_token`
   - `test_reauth_step_replaces_refresh_token_without_creating_new_entry`
   - `test_yaml_import_aborts_with_migration_message` — old YAML config
     can no longer auto-import; user must redo OAuth.

---

## Approach

### Phase 1 — Library: dual-flow auth (`kohler-anthem`)

**Goal:** the library can authenticate via either ROPC (legacy, kept for
reads-only fallback) or PKCE+refresh (new default for full access). Existing
public API (`KohlerAnthemClient`, `KohlerConfig`) stays backward-compatible
for reads; controls require the new flow.

#### 1.1. New `KohlerOAuthConfig` (additive)

In `src/kohler_anthem/config.py`, add a new dataclass alongside `KohlerConfig`:

```python
@dataclass
class KohlerOAuthConfig:
    """OAuth Authorization Code + PKCE configuration for B2C_1A_signin."""
    client_id: str
    apim_subscription_key: str
    api_resource: str
    redirect_uri: str = "msauth.com.kohler.hermoth://auth"  # mirrors official app
    auth_tenant: str = "konnectkohler.onmicrosoft.com"
    auth_policy: str = "B2C_1A_signin"

    @property
    def authorize_url(self) -> str: ...
    @property
    def token_url(self) -> str: ...
    @property
    def auth_scope(self) -> str:
        return f"openid offline_access https://{self.auth_tenant}/{self.api_resource}/apiaccess"
```

Note: `B2C_1A_signin` does **not** use the `tfp/` URL prefix that ROPC uses.
The OIDC discovery doc shows `/{tenant}/{policy}/oauth2/v2.0/...` directly.
Verify by hitting the discovery URL in the diagnostic before relying on it:

```
https://konnectkohler.b2clogin.com/konnectkohler.onmicrosoft.com/B2C_1A_signin/v2.0/.well-known/openid-configuration
```

Confirmed live as of 2026-05-09.

#### 1.2. New `KohlerOAuthAuth` (additive)

In `src/kohler_anthem/auth.py`, add a class parallel to `KohlerAuth`:

```python
class KohlerOAuthAuth:
    """OAuth Authorization Code + PKCE against B2C_1A_signin."""

    def __init__(
        self,
        config: KohlerOAuthConfig,
        *,
        token_store: TokenStore,
    ) -> None: ...

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Return (verifier, challenge). Challenge is S256."""

    def build_authorize_url(self, *, state: str, code_challenge: str) -> str:
        """Return the URL the user opens in a browser for sign-in."""

    async def exchange_code_for_token(
        self,
        session: aiohttp.ClientSession,
        *,
        code: str,
        code_verifier: str,
    ) -> TokenInfo:
        """Trade the authorization code for tokens; persist via token_store."""

    async def ensure_valid_token(self, session: aiohttp.ClientSession) -> str:
        """Use stored refresh token; refresh if expiring; raise ReauthRequired
        if the refresh token itself is invalid."""
```

`TokenStore` is a small protocol the caller implements (HA stores in the
config entry; CLI stores in a file). Library never persists secrets itself.

```python
class TokenStore(Protocol):
    async def load(self) -> Optional[TokenInfo]: ...
    async def save(self, token: TokenInfo) -> None: ...
```

#### 1.3. New exception

`exceptions.py`: add `ReauthRequired(AuthenticationError)` so consumers can
trigger an interactive re-sign-in flow without confusing it with transient
network errors.

#### 1.4. `KohlerAnthemClient` accepts either auth strategy

Constructor change (additive — keep the old positional signature):

```python
class KohlerAnthemClient:
    def __init__(
        self,
        config: KohlerConfig | KohlerOAuthConfig,
        *,
        timeout: int = REQUEST_TIMEOUT,
        token_store: Optional[TokenStore] = None,  # required when config is OAuth
    ) -> None:
        if isinstance(config, KohlerOAuthConfig):
            if token_store is None:
                raise ValueError("KohlerOAuthConfig requires a token_store")
            self._auth = KohlerOAuthAuth(config, token_store=token_store)
        else:
            self._auth = KohlerAuth(config)
```

`_request()` is unchanged — it just calls `_auth.ensure_valid_token`.

#### 1.5. Standalone CLI for interactive sign-in (helps testing)

`dev/scripts/oauth_login.py`:
- Generates a PKCE pair.
- Opens the authorize URL in the default browser.
- Spins up a local HTTP server on `127.0.0.1:<random>` to receive the
  redirect, OR (if the redirect URI is the custom scheme) prints the
  authorize URL and asks the user to paste the redirected URL.
- Exchanges the code for tokens and writes them to a JSON file.
- Prints the resulting refresh token + a sample `make health-check`
  invocation that uses it.

This is also what the test for `test_exchange_code_for_token_persists_refresh_token`
will mock against.

### Phase 2 — HA component: OAuth config flow (`ha-kohler-anthem`)

#### 2.1. Replace `config_flow.py`

Use HA's built-in `config_entry_oauth2_flow.AbstractOAuth2FlowHandler`.
HA handles the redirect dance, token persistence, and reauth prompts —
we just provide an `AbstractOAuth2Implementation` that knows the B2C
URLs.

```python
from homeassistant.helpers import config_entry_oauth2_flow

class KohlerAnthemImplementation(
    config_entry_oauth2_flow.LocalOAuth2Implementation,
):
    @property
    def authorize_url(self) -> str: return AUTHORIZE_URL
    @property
    def token_url(self) -> str: return TOKEN_URL
    @property
    def extra_authorize_data(self) -> dict[str, str]:
        return {"scope": SCOPE, "response_mode": "query"}

class KohlerAnthemConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    DOMAIN = DOMAIN
    @property
    def logger(self) -> logging.Logger: return _LOGGER
    @property
    def extra_authorize_data(self) -> dict: return {"scope": SCOPE}
    async def async_step_user(self, user_input=None):
        # Collect APIM key + api_resource + client_id (still per-user values
        # since they came from Frida capture; unlike a public OAuth provider).
        # Then jump to the OAuth dance.
```

Note: HA's OAuth2 helper assumes `client_id`/`client_secret` are config-time
constants. Kohler uses a public client with no secret (PKCE), and the
`client_id` comes from credential extraction. We'll either:

(a) Subclass `LocalOAuth2Implementation` and override `_token_request` to
    pass `code_verifier` instead of `client_secret`, OR
(b) Use `application_credentials` integration so the user enters
    client_id once at integration-install time.

(a) is simpler for a single-user integration; (b) is more idiomatic.
**Decision: go with (a) initially**, reassess when adding multi-account
support.

#### 2.2. Persist tokens in the config entry

HA's OAuth helper does this automatically: tokens land in
`config_entry.data["token"]` and are refreshed by
`config_entry_oauth2_flow.OAuth2Session`.

`__init__.py` change:

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    impl = await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, impl)
    token_store = HASessionTokenStore(session)
    config = KohlerOAuthConfig(
        client_id=entry.data[CONF_CLIENT_ID],
        apim_subscription_key=entry.data[CONF_APIM_KEY],
        api_resource=entry.data[CONF_API_RESOURCE],
    )
    client = KohlerAnthemClient(config, token_store=token_store)
    ...
```

`HASessionTokenStore` adapts the HA OAuth2Session to our library's
`TokenStore` protocol.

#### 2.3. Reauth flow

When the library raises `ReauthRequired`, the integration should call
`entry.async_start_reauth(hass)`, which HA wires into the standard
Repairs UX. The `async_step_reauth` and `async_step_reauth_confirm`
methods come for free from `AbstractOAuth2FlowHandler`.

#### 2.4. Migration

For users on the old ROPC config entry:

- On `async_setup_entry`, detect the old shape (presence of
  `CONF_PASSWORD` in `entry.data`) and call
  `entry.async_start_reauth(hass)` immediately, with a message in
  `strings.json` explaining the policy change.
- The reauth flow walks them through OAuth and replaces the stored
  data — the unique_id (username) stays, so no entity loss.
- Remove `CONF_PASSWORD` from the entry data on successful migration.

#### 2.5. YAML import path

The legacy `async_step_import` in `config_flow.py` can no longer succeed
(YAML can't carry an interactive token). Make it abort with
`reason="manual_oauth_required"` and add a strings entry pointing the
user to the integration's UI flow.

### Phase 3 — Update integration tests

After phases 1–2 land:

- The 3 currently-failing assertions in
  `tests/integration/test_credentials_health.py` should flip to passing
  on machines where the OAuth-based credentials are configured.
- Add a parallel set of probes for the new auth flow that explicitly
  uses `B2C_1A_signin` end-to-end, so we keep visibility on the legacy
  ROPC path as long as Kohler still supports it for reads.

### Phase 4 — Docs

- `kohler-anthem/docs/REVERSE_ENGINEERING.md`: add a section on the
  ROPC vs interactive policy distinction (this should be done as part of
  the diagnostic-suite work, not the rewrite).
- `kohler-anthem/credential-extraction/README.md`: note that for
  full control access, the OAuth flow is required and credentials only
  need to be extracted once (client_id, api_resource, apim_key) — the
  user/password fields go away.
- `ha-kohler-anthem/README.md`: setup section gets a new
  screenshot/walkthrough of the browser sign-in step.

---

## Files to Modify

### `kohler-anthem`

| File | Change |
|------|--------|
| `src/kohler_anthem/config.py` | + `KohlerOAuthConfig` dataclass |
| `src/kohler_anthem/auth.py` | + `KohlerOAuthAuth`, + `TokenStore` protocol |
| `src/kohler_anthem/client.py` | Accept either config type; route to right auth |
| `src/kohler_anthem/exceptions.py` | + `ReauthRequired` |
| `src/kohler_anthem/__init__.py` | Re-export new types |
| `tests/test_auth_pkce.py` | NEW — unit tests for PKCE + refresh |
| `tests/integration/_probe.py` | + probe variant for OAuth-issued tokens |
| `tests/integration/test_credentials_health.py` | Drop `xfail` once flow lands |
| `dev/scripts/oauth_login.py` | NEW — interactive sign-in helper |

### `ha-kohler-anthem`

| File | Change |
|------|--------|
| `custom_components/kohler_anthem/config_flow.py` | Rewrite to use `AbstractOAuth2FlowHandler` |
| `custom_components/kohler_anthem/__init__.py` | Use OAuth2Session; migration on setup |
| `custom_components/kohler_anthem/const.py` | + AUTHORIZE_URL, TOKEN_URL, SCOPE |
| `custom_components/kohler_anthem/strings.json` | + reauth + migration strings |
| `custom_components/kohler_anthem/translations/en.json` | mirror strings.json |
| `custom_components/kohler_anthem/manifest.json` | bump version (e.g., 0.3.0) |
| `tests/test_config_flow.py` | NEW |

---

## Verification

- [ ] `cd kohler-anthem && make check` (existing 113 unit tests + new PKCE tests)
- [ ] `cd kohler-anthem && make health-check` after completing the OAuth login —
      command-write probes show OK/BAD_REQUEST instead of BACKEND_FORBIDDEN.
- [ ] In HA: remove the kohler_anthem integration, re-add it via the UI,
      complete the browser sign-in, then toggle a Kohler light and verify
      the device responds.
- [ ] Restart HA — entities reconnect without re-prompting for sign-in
      (refresh token survives).
- [ ] Manually expire/revoke the refresh token (e.g., delete it from
      `core.config_entries`) and verify HA surfaces a Repairs notification
      rather than silently failing.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `B2C_1A_signin` is a custom policy and may have requirements (custom redirect URI scheme, specific scopes, app-registration claims) we can't see from outside | Validate empirically: try a hand-rolled PKCE flow with `dev/scripts/oauth_login.py` BEFORE rewriting library code. If the flow doesn't work, this entire plan is invalid and we need to capture the iOS app's auth traffic via Frida/mitmproxy to see what the official client does. **Do this first as a Phase 0 spike.** |
| Custom redirect URI (`msauth.com.kohler.hermoth://auth`) doesn't work from a non-mobile context | Try `http://localhost:<port>/` or `urn:ietf:wg:oauth:2.0:oob` (out-of-band copy/paste). If neither is registered, we may need an alternate `client_id` for desktop use, which would require a fresh credential capture |
| Refresh token TTL is short (some B2C policies issue 24h-only refresh tokens) | Probe the token response: if `refresh_token_expires_in` is short, document the re-auth cadence and surface it in the integration |
| Kohler eventually deprecates `B2C_1_ROPC_Auth` and reads break too | The diagnostic suite catches this immediately. The OAuth flow already covers reads, so no separate fix is needed |
| HA's OAuth2 helper assumptions don't match B2C's PKCE flow | Fall back to a hand-rolled config flow that does the OAuth dance manually and persists tokens to `entry.data["token"]` in the same shape HA expects |

---

## Phase 0: De-risk before committing to the rewrite

**Before writing any production code**, do this 30-minute spike:

1. Manually craft an authorize URL for `B2C_1A_signin` with the existing
   client_id and a `urn:ietf:wg:oauth:2.0:oob` redirect.
2. Open it in a browser, sign in.
3. Copy the resulting `code` from the redirect URL.
4. Exchange it via `curl` for a token at the `B2C_1A_signin` token endpoint
   (with the `code_verifier`).
5. Use that token to hit `POST /platform/api/v1/commands/gcs/solowritesystem`
   with an empty body.
6. **Acceptance**: response is 400 (validation error — auth passed) instead
   of 403.

If step 6 succeeds, the rest of the plan is sound. If it doesn't, do not
commit further effort to the rewrite — instead capture the official app's
sign-in flow with Frida or mitmproxy to see exactly what authorize/token
parameters it uses (response_type, prompt, redirect_uri, additional
parameters like `nonce` or `acr_values`), and update the plan.

---

## Rollback

If the rewrite ships and Kohler reverses their backend change (or breaks
the new flow), users can roll back by checking out the prior tag of
`ha-kohler-anthem` and downgrading the `kohler-anthem` library to 0.1.4.
The old ROPC config flow is preserved on the `legacy-ropc` branch (cut
this branch from `main` immediately before starting Phase 1).

---

## Out of scope for this plan

- Multi-account support
- Migrating away from Frida-extracted credentials entirely (e.g., using
  an OAuth public-client flow that doesn't require any captured values).
  This would be ideal but requires Kohler to publish a developer
  registration program.
- Local API support (Kohler's device firmware doesn't expose one).

---

## Findings from 2026-05-10 Phase 0 attempt

A Phase 0 spike was run interactively against the live API. The plan's
*direction* (interactive flow needed) is plausible but its *specifics*
turned out to be wrong in several places. Open PRs implementing the
plan are partially based on these wrong specifics and should not be
merged as-is.

### What was confirmed empirically

- ROPC tokens (`B2C_1_ROPC_Auth` policy) get **HTTP 403** from the
  backend on every `/platform/api/v1/commands/{gcs,hub}/*` endpoint.
  Reads (`/devices/api/...`) and `POST /platform/api/v1/mobile/settings`
  still work fine. 403 body is uniform:
  `{"detail":null,"error":null,"statusCode":403,"message":"Forbidden"}`.
- The 403 is not body- or User-Agent-dependent. Tested with empty `{}`,
  realistic `{deviceId, tenantId}`, and four UAs including the iOS app's
  format. Same 403 every time. No `WWW-Authenticate` response header.
- The `B2C_1A_signin` policy *exists* and accepts `/authorize` requests,
  but its `/token` endpoint **rejects the standard PKCE-only flow** with
  `AADB2C90079: Clients must send a client_secret when redeeming a
  confidential grant`. This contradicts the plan's assumption that
  `B2C_1A_signin` is a public-client (PKCE-only) policy.
- The Kohler iOS Konnect app **currently works** end-to-end. So the
  problem isn't Kohler-side outage — there is a working request shape
  we just can't see from outside.

### What we got wrong in the original plan

| Claim in plan | Actual |
|---------------|--------|
| `B2C_1A_signin` uses no `tfp/` URL prefix | The MSAL config in the APK uses `https://konnectkohler.b2clogin.com/tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin/`. Both forms exist; the `/tfp/` form is what's actually validated. |
| Default redirect URI: `msauth.com.kohler.hermoth://auth` | Actual MSAL redirect: `msauth://com.kohler.hermoth/2DuDM2vGmcL4bKPn2xKzKpsy68k%3D` (note: literal `%3D` at end, must be sent as `%253D` in the query string). |
| App is a public client; PKCE only | App registration is configured **confidential** (requires client_secret OR cert-based JWT-bearer). |
| Same `client_id` works without changes | The client_id is the same, but the auth mechanism the app uses (probably JWT-bearer with the `auth_certificate.pfx` from `res/raw/`) is not PKCE-only. |

### What the APK reveals

Static analysis of `credential-extraction/kohler-konnect-3.0.1-apk/base.apk`
(unzipped to `/tmp/apk-extract/` during this spike — git-LFS pulled the
real APK):

- `res/raw/auth_config_release.json` contains the MSAL config — confirms
  client_id and the `/tfp/...B2C_1A_signin/` authority URL.
- `res/raw/auth_certificate.pfx` and `res/raw/app_certificate.p12` exist
  with **unknown passwords**. Empty password and several common defaults
  (`kohler`, `kohler123`, `changeit`, etc.) all fail MAC verification.
- DEX strings include `client_assertion`, `client_assertion_type`,
  `urn:ietf:params:oauth:client-assertion-type:jwt-bearer`, `JWT_BEARER`
  — strongly suggesting the app uses **certificate-based JWT-bearer
  client authentication** when redeeming codes at the token endpoint.
  The PFX password / cert reading code path was not located in this
  spike.
- DEX strings include `ExecuteControlCommand` and `Executing ROPC token
  command...` — the app's own logging suggests it does still use ROPC
  tokens in some context, possibly only for IoT Hub MQTT auth.
- Found `/platform/api/v1/commands/hub/*` — a parallel command family
  (`/hub/valvecontrol`, `/hub/shower/experience/control`, etc.). Same
  403 as `/gcs/*`, so this is not the missing piece.
- Found `/platform/api/v1/commands/gcs/{createpreset,factoryreset,
  uiconfigsuccess,writeoutletconfig,writepreset,writeuiconfig}` — more
  GCS endpoints the library doesn't know about. Same 403 on all.
- `solowritesystem` is present in DEX only as a templated string
  (`/platform/api/{version}/commands/gcs/solowritesystem`); other
  endpoints have both literal and templated forms. Tried `v2`: 404.
  Endpoint isn't moved.
- Alternate APIM gateway hostname found: `az-amer-prod-kohlerkonnect-apim.azure-api.net`.
  All paths 404 there with the existing APIM key — different routing
  config. Not the missing piece either.

### Why we couldn't go further

Verifying the actual auth mechanism requires capturing the official
Konnect app's `/token` request. Attempts:

- **Mac mitmproxy + iOS Konnect app**: blocked by SSL pinning even on
  the auth flow.
- **Brute-forced redirect URI on B2C_1A_signin from Mac browser**:
  produced an authorization code (Google account-linking redirect URI
  is also registered for the app), but token exchange failed at
  `client_secret required`.
- **Static dex string search for cert password / hardcoded
  client_secret**: nothing obvious.

### Concrete next steps (when this is picked up)

1. **Capture the iOS app's `/token` request via Android emulator + Frida
   bypass.** The credential-extraction toolchain already has
   `frida_bypass.js` with SSL-pinning bypass installed (lines 86-119
   bypass `X509TrustManager` and `TrustManagerImpl`). Re-run that
   pipeline (`make emulator-setup` etc.) but route the emulator's
   traffic through a mitmproxy. The capture should reveal:
   - Whether the app sends `client_secret` (and what it is)
   - Whether the app sends `client_assertion` (a JWT signed with the
     PFX cert's private key) plus `client_assertion_type=jwt-bearer`
   - The exact authorize URL parameters (any non-standard params we
     don't know about, e.g. `acr_values`, `prompt`, custom claims)
   - The exact redirect URI being sent
2. **If the answer is JWT-bearer**: locate where the app reads the
   PFX file. The cert password is either hardcoded near that code path,
   constructed at runtime from app constants (e.g. derived from package
   signing hash), or generated/fetched on first launch. mitmproxy
   capture might show a "fetch cert password" call too.
3. **If the answer is `client_secret`**: it's likely fetched dynamically
   from a Kohler endpoint we haven't found, or derived from device
   binding. Capture will show this.

### Recommended action on open PRs

- **`yon/kohler-anthem` PR #10** (`feat/integration-health-check`) —
  the diagnostic infrastructure stands on its own and is unaffected by
  these findings. Already merged ✓.
- **`yon/kohler-anthem` PR #12** (`feat/b2c-1a-signin-auth`) — based
  on wrong URL pattern and wrong redirect URI, plus assumes pure PKCE.
  **Should not be merged.** Either close it or convert to draft and
  link to these findings.
- **`yon/ha-kohler-anthem` PR #4** (`feat/b2c-1a-signin-auth`) — depends
  on the library PR. **Should not be merged.** Same disposition.

### Time spent on this Phase 0 attempt

~3-4 hours of interactive work on 2026-05-10. Bulk went into discovery
of the wrong-redirect-URI / wrong-URL-prefix / client_secret-required
sequence. Static APK analysis (post-LFS-pull) was the most productive
part and is reusable for the next attempt.

### Status: PARKED

The hypothesis "switch to B2C_1A_signin" is not yet falsified, but the
implementation specifics are wrong and the actual mechanism requires
mobile-traffic capture to determine. Resume with the Android emulator
capture pipeline.
