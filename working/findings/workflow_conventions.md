---
name: Workflow conventions for kohler-anthem
description: git-LFS quirks, worktree setup, where credentials live, build commands
type: project
---

**Why:** Avoid re-discovering these every session.
**How to apply:** Reference at session start when working on either repo.

## git-LFS

The `kohler-anthem` repo's `.gitattributes` declares `*.apk` as LFS-tracked. If `git-lfs` isn't installed, git operations fail with "git-lfs filter-process: not found", APK files appear as 133-byte ASCII pointers, and `git worktree add` fails. Fixes:

- Install (Debian/Ubuntu): `apt-get install -y git-lfs && git lfs install --local --force` — git-lfs ships separately from git on most distros.
- Install (macOS): `brew install git-lfs && git lfs install`
- Or temporarily disable filters per-call (no install needed): `git -c filter.lfs.process= -c filter.lfs.smudge=cat -c filter.lfs.required=false worktree add ...`
- After install, run `git lfs pull` to materialize the binaries.

## Worktrees

- Both repos gitignore `.worktrees/` at the repo root. Use that directory for git worktrees.
- Use the `EnterWorktree` native tool when the base ref is `origin/main`; fall back to `git worktree add` for stacked worktrees off feature branches.

## Credentials

- `credential-extraction/kohler-credentials.yaml` — gitignored, **not present** on a fresh checkout. Recreate via `make credentials-generate` (in the `credential-extraction/` subdir) or read directly from HA storage (below).
- HA's `.storage/core.config_entries` (under domain `kohler_anthem`) has the working credentials. Fields: `username`, `password`, `client_id`, `apim_subscription_key`, `api_resource`, `tenant_id`. The `password` field is plaintext.
- HA's `secrets.yaml` has the same five fields available as `kohler_*` keys.
- `device_id` for the user's shower: `gcs-sio3225nc9` (from HA device registry, identifier tuple `["kohler_anthem", "gcs-sio3225nc9"]`).
- > **Machine-specific paths.** On the production LXC, HA config lives at `/opt/home-automation/homeassistant/config/`. From the developer Mac, access via SSH or copy locally for offline reading.

## Build / test commands

In **`yon/kohler-anthem`**:
- `make check` — lint + typecheck + tests (Python). 113 tests baseline; +16 PKCE tests on the auth-rewrite branch.
- `make health-check` — live diagnostic against Kohler API (requires creds via env or YAML).
- `make oauth-login OAUTH_TOKENS=path/to/file.json` — interactive sign-in helper (only on auth-rewrite branch; currently broken because of plan-spec issues).

In **`yon/ha-kohler-anthem`**:
- `make check` — ruff lint (only).
- `make test` (on auth-rewrite branch) — 13 helper unit tests.

## Branches

- `main` — both repos.
- `legacy-ropc` — both repos. Snapshot of `main` as of 2026-05-09, right before the auth rewrite started, kept as rollback insurance.
- `feat/b2c-1a-signin-auth` — both repos. The auth-rewrite work. PR #12 on kohler-anthem and #4 on ha-kohler-anthem. **Specifics are wrong; don't merge.** Both PRs converted to draft on 2026-05-10 with explanatory comments.
