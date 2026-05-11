---
name: Why /commands/* writes 403 — definitive answer
description: Decompile + empirical proof that Kohler's `/commands/*` endpoints require tokens issued by the B2C_1A_signin policy. ROPC tokens (tfp=B2C_1_ROPC_Auth) pass reads but fail writes. The capture-harness's APIM service-account JWT is also rejected.
type: project
---

**Status as of 2026-05-10**: Root cause of HA integration write 403s fully diagnosed. Implementation plan: switch library to use B2C_1A_signin policy tokens via MSAL Python with a HA config-flow browser sign-in. See plan: `working/plans/2026-05-10_b2c_1a_signin_auth_rewrite.md` (resurrected).

## The decisive evidence

Konnect 3.0.1's OkHttp `Authenticator` (`Ji/C6578b.java:155`) calls `IMultipleAccountPublicClientApplication.acquireTokenSilentAsync(...)` with the authority `B2C_1A_signin`:

```java
.withScopes(c0113a.b())
.forAccount(iAccount)
.fromAuthority(c0113a.a("B2C_1A_signin"))
.withCallback(new a(objectRef, countDownLatch))
.build()
```

The resulting access token is stored as `auth_token` in secure prefs. The `xi/C8633a.java` interceptor reads that key and adds `Authorization: Bearer <auth_token>` to every outbound request — including `/commands/*`. So the policy that issues the JWT that authorizes `/commands/*` writes is **B2C_1A_signin**.

The msal_config.json bundled in the APK confirms the authority:

```json
{
  "client_id": "8caf9530-1d13-48e6-867c-0f082878debc",
  "authorities": [{
    "type": "B2C",
    "authority_url": "https://konnectkohler.b2clogin.com/tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin/"
  }]
}
```

## What we tried that DIDN'T work

Probed against the live API with every token + connector combination we could obtain:

| Token type (tfp claim) | mTLS via `app_certificate.p12`? | `/devices/*` | `/commands/gcs/*` |
|---|---|---|---|
| ROPC user JWT (`B2C_1_ROPC_Auth`, correct scope) | no | 200 OK | **403** |
| ROPC user JWT (`B2C_1_ROPC_Auth`, correct scope) | yes | 200 OK | **403** |
| APIM service-account JWT (`B2C_1_ROPC_Auth`, oid=c143833c-…) | no | 403 | **403** |
| APIM service-account JWT (`B2C_1_ROPC_Auth`, oid=c143833c-…) | yes | 403 | **403** |

Backend RBAC keys on the `tfp` claim. Both available token types have `tfp=B2C_1_ROPC_Auth`. The library can produce *neither* of the policies the backend will accept for `/commands/*`.

The harness's earlier "captured the service-account JWT, this is the answer!" diagnosis was wrong. The harness never actually saw a successful `/commands/*` call — the auto-tap on Sign In fired the click but Konnect's downstream call silently no-op'd. We confused the `/token/api/v1/token/` JWT-fetch call (which works on the APIM mTLS path) with the auth that `/commands/*` consumes.

## What we tried that DIDN'T work (Native Auth)

The Microsoft MSAL Native Auth SDK is bundled in the APK — initially we hoped this meant Kohler's B2C tenant had Native Auth enabled (which would allow username+password POSTs without a browser). It does NOT. Probing `https://konnectkohler.b2clogin.com/{tenant,/tfp/tenant}/B2C_1A_signin/oauth2/v2.0/initiate` returns 404. ROPC against `B2C_1A_signin` returns `server_error` (the policy is interactive-only). Konnect's bundled MSAL library is for the standard interactive flow; `acquireTokenSilent` works because the user signed in once via the OAuth interactive flow.

## Why non-updating users still work

They've completed a one-time interactive `B2C_1A_signin` sign-in (custom-policy flow with email/password, possibly with OOB code) which seeded the MSAL account cache. From then on, `acquireTokenSilent` refreshes the token using the cached refresh token. No new interactive sign-in needed unless the refresh token is revoked.

## The fix: B (msal-python with config-flow browser sign-in)

Have HA's config flow drive an interactive B2C sign-in via Microsoft's official `msal` Python library:

```python
from msal import PublicClientApplication

app = PublicClientApplication(
    client_id="8caf9530-1d13-48e6-867c-0f082878debc",
    authority="https://konnectkohler.b2clogin.com/tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin",
    validate_authority=False,  # B2C policies don't return the standard metadata
)
result = app.acquire_token_interactive(
    scopes=["https://konnectkohler.onmicrosoft.com/f5d87f3d-bdeb-4933-ab70-ef56cc343744/apiaccess"],
)
# result["access_token"] — for /commands/*
# result["refresh_token"] — to seed silent refresh later
```

After the one-time interactive sign-in:

```python
accounts = app.get_accounts(username=...)
result = app.acquire_token_silent(scopes=[...], account=accounts[0])
```

For HA: bundle this in the integration's `config_flow.py`. User runs through the sign-in once during integration setup (browser opens, they enter credentials), the resulting refresh token is persisted in HA's config entry, the library silently refreshes thereafter. Matches what every other Azure-AD-B2C HA integration does.

## What the library needs to change

1. **Add `msal>=1.20` to dependencies.**
2. **Split `KohlerAuth` into two flows:**
   * Existing ROPC path stays for back-compat / reads (it works; switching reads to B2C_1A_signin is optional).
   * New `B2C_1A_signin` flow via `msal.PublicClientApplication` that loads a refresh token from `KohlerConfig` and silently refreshes.
3. **Add `refresh_token` (and `account_username` for cache identity) to `KohlerConfig`.**
4. **Route writes (`/commands/*`) through the B2C_1A_signin token.** Reads can stay on ROPC for now.
5. **HA integration's `config_flow.py`** drives `acquire_token_interactive` once and stores the refresh token.

## Open questions for next session

1. **Will reads also need to migrate to B2C_1A_signin?** If yes, eventually drop ROPC entirely. If no, both tokens coexist forever. Probably worth migrating once writes work to simplify the auth code.
2. **Does the APIM mTLS service-account path have any remaining use?** It still works at `/token/api/v1/token/` and might be needed for app-level operations we haven't found. Keep the bundled cert + `acquire_apim_token()` scaffolding for now; revisit later.
3. **Is there a B2C custom-policy version of ROPC** (rather than interactive) that we missed? `B2C_1A_RopcAuth_signin` or similar custom-policy name? Worth grepping the APK once more.

## Sources

* Decompiled OkHttp Authenticator: `credential-extraction/.build/decompiled/sources/Ji/C6578b.java:155`
* Two-token interceptor: `credential-extraction/.build/decompiled/sources/xi/C8633a.java`
* Token-fetch interceptor (APIM key only): `credential-extraction/.build/decompiled/sources/xi/C8634b.java`
* MSAL config (production): `credential-extraction/.build/decompiled/resources/res/raw/msal_config.json`
* Live probe results: matrix above; reproducible via `tests/integration/test_credentials_health.py`
