# Plan: wire B2C_1A_signin refresh_token into the HA integration

**Date:** 2026-05-11
**Status:** DRAFT (ready for implementation in `yon/ha-kohler-anthem`)
**Library version this depends on:** `kohler-anthem >= 0.2.0` (commit `a04ad58` on
`feat/emulator-token-capture` — not yet released as 0.2.0).

## Goal

Restore HA write operations (outlet on/off, temperature/flow set, presets,
warmup) that have been 403ing against `/platform/api/v1/commands/gcs/*`.
Root cause and fix are documented in
`working/findings/commands_writes_403_2026-05-10.md`. The library now
accepts a `b2c_refresh_token` in its `KohlerConfig` and routes
`/commands/*` writes through the B2C_1A_signin policy. The HA integration
needs to (1) collect the refresh_token from the user at setup and (2)
persist the rotated value after each write.

## Approach: user pastes the refresh_token at setup (Option 1)

We considered building the OAuth code flow into HA's `config_flow.py` but
Kohler's B2C app registration only whitelists `msauth://` and a Google
Home redirect URI — no localhost, so HA can't act as the OAuth callback
host. The "open URL, paste back" pattern is identical whether driven by a
CLI helper or HA's UI; we keep it in a CLI helper to avoid bloating the
integration.

The user runs `kohler-anthem`'s `dev/scripts/b2c_signin.py` once per
account (open URL → sign in → copy `msauth://` redirect URL → paste back
into the second invocation). The script prints the refresh_token. The
user pastes it into HA's integration setup form.

## Changes in `ha-kohler-anthem`

### 1. `manifest.json` — bump library requirement

```diff
-  "requirements": ["kohler-anthem==0.1.4"],
+  "requirements": ["kohler-anthem>=0.2.0"],
   "version": "0.2.2"
```

(Library version bump happens in `yon/kohler-anthem` separately — see
"Library release" below.)

### 2. `custom_components/kohler_anthem/const.py` — new config key

```diff
 CONF_TENANT_ID = "tenant_id"
+CONF_B2C_REFRESH_TOKEN = "b2c_refresh_token"
```

### 3. `custom_components/kohler_anthem/config_flow.py` — collect + validate the token

* Add `CONF_B2C_REFRESH_TOKEN` to `STEP_USER_DATA_SCHEMA` as a required
  string field. Mark it `vol.Required` (writes won't work without it).
* Update `description_placeholders` so the HA form shows a link/explainer
  pointing to the README section describing how to obtain it via
  `b2c_signin.py`.
* In `_async_validate_and_create`, pass `b2c_refresh_token=` to
  `KohlerConfig(...)`.
* Validate by **actually performing a write** — call
  `client.start_warmup(tenant_id, device_id)` against a real device the
  user owns. If the call returns a `correlation_id`, auth is good. If it
  raises `AuthenticationError`, the refresh_token is invalid/revoked
  (show `invalid_b2c_refresh_token` error). The library will exhaust the
  refresh_token grant trying to refresh, so the error surfaces clearly.
  * Alternative if `start_warmup` is too intrusive to use as a probe:
    call `client._b2c_auth.refresh(client._session)` directly. It hits
    `/oauth2/v2.0/token` with the refresh_token; on success the token
    will silently refresh forever; on failure we get a clean error.
* Persist `b2c_refresh_token` into the config entry data so it's
  available at runtime.

### 4. `custom_components/kohler_anthem/__init__.py` — pass into KohlerConfig + persist rotation

* In the coordinator/setup, build `KohlerConfig` with
  `b2c_refresh_token=entry.data[CONF_B2C_REFRESH_TOKEN]`.
* After each successful write (or periodically), read
  `client.b2c_refresh_token` and compare to `entry.data[CONF_B2C_REFRESH_TOKEN]`.
  If different, update the config entry:

  ```python
  rotated = client.b2c_refresh_token
  if rotated and rotated != entry.data.get(CONF_B2C_REFRESH_TOKEN):
      hass.config_entries.async_update_entry(
          entry,
          data={**entry.data, CONF_B2C_REFRESH_TOKEN: rotated},
      )
  ```

  B2C rotates the refresh_token on every silent refresh; persisting the
  latest value means the integration survives HA restarts without
  needing the user to re-paste.

### 5. Reauth flow — for revoked or expired refresh_tokens

If `AuthenticationError` surfaces from a write, the refresh_token has
been revoked (or expired — rare). Add an `async_step_reauth` to
`KohlerAnthemConfigFlow` that re-prompts the user for a new
refresh_token only (other config stays the same). HA's reauth machinery
fires this automatically when a coordinator raises `ConfigEntryAuthFailed`.

### 6. Migration — existing config entries

Existing entries don't have `b2c_refresh_token` and will fail on writes.
Two options:

* **Easy:** on first failed write, the reauth flow above fires and the
  user pastes the refresh_token without losing other config.
* **Better:** add an entry migration (`async_migrate_entry`) that
  detects missing `b2c_refresh_token` and triggers reauth proactively
  the next time the integration loads. Bump `KohlerAnthemConfigFlow.VERSION`
  from 1 to 2.

Either works; (1) is simpler and gives the same UX from the user's POV.

### 7. README — document the seed step

In the setup section, add:

> Outlet/valve/preset controls require an additional one-time setup step
> (a B2C_1A_signin refresh_token). To obtain it, install the
> `kohler-anthem` library in a Python venv and run:
> 
> ```
> python -m kohler_anthem.b2c_signin url
> # Sign in via the browser that opens.
> # The redirect to `msauth://com.kohler.hermoth/...` fails to navigate
> # but the URL is visible in your browser's address bar.
> # Safari hides it — use Chrome, or open Safari's Web Inspector and
> # read the `Location:` response header.
> python -m kohler_anthem.b2c_signin exchange '<paste-msauth-url>'
> ```
> 
> The second command prints the refresh_token. Paste it into HA's
> integration setup form under "B2C Refresh Token".

This implies promoting `dev/scripts/b2c_signin.py` into a public,
package-included module — see "Library release" below.

## Library release: kohler-anthem 0.2.0

1. Promote `dev/scripts/b2c_signin.py` to `src/kohler_anthem/b2c_signin.py`
   so HA users can run it via `python -m kohler_anthem.b2c_signin ...`
   without cloning the repo. The dev/scripts copy can be kept as a thin
   shim or removed.
2. Bump `pyproject.toml` version from `0.1.4` to `0.2.0`.
3. CHANGELOG entry summarizing the new `b2c_refresh_token` field +
   `B2CSignInAuth` class.
4. Publish to PyPI.
5. Update HA integration's `manifest.json` requirements to the new pin.

## Testing checklist

- [ ] Unit tests for HA `config_flow` reauth path (mock library)
- [ ] Integration test: install HA, add config entry with refresh_token,
      toggle an outlet, verify state changes on the physical device
- [ ] Integration test: revoke the refresh_token via Kohler's portal (if
      possible) and confirm reauth flow fires + user can paste a new one
- [ ] Restart HA after a few writes; confirm the rotated refresh_token
      was persisted and writes still work without user intervention
- [ ] Verify that an entry created BEFORE this change migrates cleanly
      (no manual JSON-editing required)

## Open questions

1. **Refresh_token TTL.** Microsoft says B2C refresh_tokens last up to 90
   days (default) or whatever the policy configures. If Kohler's policy
   has a shorter TTL, the user will see reauth prompts more often. Test
   over a few weeks of HA uptime.
2. **`KOHLER_B2C_REFRESH_TOKEN` field naming in HA.** "B2C Refresh
   Token" is opaque to users. Consider "Kohler write-access token" or
   similar with a longer explanation in the help text.
3. **Browser-only sign-in via HA's frontend?** HA can technically open a
   browser tab and accept a paste — but it still requires the user to
   copy from the address bar after the msauth:// failure. Whether to
   build this into HA's config flow itself or keep the CLI helper as
   the canonical seed step is a UX call. CLI is simpler to maintain.

## Risks

* **B2C policy changes.** If Kohler rotates the B2C_1A_signin policy
  GUID/audience or the application client_id, the bundled defaults in
  `kohler-anthem` break for all users at once. Document the upgrade
  path in the library README.
* **Token revocation cascade.** If Kohler does a mass refresh_token
  revocation (security incident, etc.), every HA user with this
  integration has to re-do the seed step. Acceptable — same as resetting
  any OAuth integration.

## Sources

* Library implementation: `src/kohler_anthem/auth.py` (`B2CSignInAuth`),
  `src/kohler_anthem/client.py` (write routing).
* Live verification: `tests/integration/test_library_writes.py`.
* Architecture writeup: `working/findings/commands_writes_403_2026-05-10.md`.
* Memory: `~/.claude/projects/.../memory/auth_architecture.md`.
