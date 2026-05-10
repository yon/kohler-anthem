---
name: Repo layout
description: Three related code locations for the Kohler Anthem integration
type: project
---

The Kohler integration spans three locations:

- **`yon/kohler-anthem`** — Python library (`kohler-anthem` on PyPI). Library code in `src/kohler_anthem/`, tests in `tests/`, integration probes in `tests/integration/`. The `dev/scripts/` dir has dev-only diagnostics (`health_check.py`, `oauth_login.py`).
- **`yon/ha-kohler-anthem`** — sibling repo, Home Assistant custom component. Lives at `custom_components/kohler_anthem/`. Depends on the library via `manifest.json`'s `requirements` array.
- **`credential-extraction/`** (subdir of `kohler-anthem`) — Frida + Genymotion tooling for extracting `client_id`, `apim_subscription_key`, `api_resource` from the Konnect APK. Contains `frida_bypass.js` with SSL-pinning + root + emulator + license bypass already implemented.

> **Local checkout paths vary by machine.** Production LXC: `/opt/{kohler-anthem,ha-kohler-anthem}`. Developer Mac: `~/src/github.com/yon/{kohler-anthem,ha-kohler-anthem}`. All path references in these findings are **repo-relative** (e.g., `src/kohler_anthem/auth.py`) unless explicitly noted as machine-specific.

Both repos use git-LFS for binaries (the APK in `credential-extraction/` is LFS-backed). On a fresh checkout, install `git-lfs` and run `git lfs pull` before APK files become usable.

Both repos use a `.worktrees/` directory at the repo root for git worktrees (already gitignored).
