# Findings index

Snapshot-in-time investigation notes — the *why* behind plan changes,
parked work, and discovered constraints. Different from `working/plans/`,
which holds prospective implementation plans. These notes also double as
Claude memory entries (the YAML frontmatter on each file is the memory
system's index schema; harmless for human readers).

| File | What it covers |
|------|----------------|
| [`kohler_api_auth_parked.md`](kohler_api_auth_parked.md) | May 2026 ROPC-rejection on `/commands/*`. Phase 0 spike done; capture pipeline now fully scripted (see below). |
| [`repo_layout.md`](repo_layout.md) | Where the three related repos live, their relationship, branching conventions. |
| [`apk_static_findings.md`](apk_static_findings.md) | What the Kohler Konnect 3.0.1 APK reveals about auth, endpoints, cert files. Avoid re-doing this analysis. |
| [`workflow_conventions.md`](workflow_conventions.md) | git-LFS quirks, worktree setup, where credentials live, build commands. |
| [`harness_layout.md`](harness_layout.md) | Where the emulator/Frida/mitmproxy capture harness lives, what's automated vs manual, where artifacts go. |
| [`auth_architecture_2026-05-10.md`](auth_architecture_2026-05-10.md) | Partial auth model: APIM mTLS + service-account ROPC. **Superseded for the /commands/* question** by `commands_writes_403_2026-05-10.md` — the service-account JWT does NOT unlock writes. Still valid for the /token endpoint architecture. |
| [`commands_writes_403_2026-05-10.md`](commands_writes_403_2026-05-10.md) | **Definitive answer** to why /commands/* returns 403: writes require B2C_1A_signin-policy tokens (acquired interactively via MSAL). Decompile + empirical probe matrix included. The fix is the original "B2C_1A_signin auth rewrite" (path B with msal-python). |
| [`why_writes_started_failing_2026-05-11.md`](why_writes_started_failing_2026-05-11.md) | **Postmortem** explaining the user-visible symptom (HA reads OK, writes 403). Two Kohler-side changes: (A) api_resource renamed → fresh ROPC fails AADB2C90205, (B) /commands/* RBAC now requires `tfp=B2C_1A_signin` → cached ROPC writes 403. Both fixed in 0.2.0. |
| [`konnect_runtime_bypass_notes.md`](konnect_runtime_bypass_notes.md) | How we got Konnect to run on a non-rooted-looking emulator: apktool smali patch, Pairip workaround, mitmproxy upstream client cert config. |

When picking up auth-rewrite work after a break, start with
`commands_writes_403_2026-05-10.md` — it has the full root-cause analysis
and the implementation plan for path B (`msal`-based interactive sign-in).
