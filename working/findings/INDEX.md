# Findings index

Snapshot-in-time investigation notes — the *why* behind plan changes,
parked work, and discovered constraints. Different from `working/plans/`,
which holds prospective implementation plans. These notes also double as
Claude memory entries (the YAML frontmatter on each file is the memory
system's index schema; harmless for human readers).

| File | What it covers |
|------|----------------|
| [`kohler_api_auth_parked.md`](kohler_api_auth_parked.md) | May 2026 ROPC-rejection on `/commands/*`. Phase 0 spike done, blocked on iOS pinning, needs Android emulator + Frida next. |
| [`repo_layout.md`](repo_layout.md) | Where the three related repos live, their relationship, branching conventions. |
| [`apk_static_findings.md`](apk_static_findings.md) | What the Kohler Konnect 3.0.1 APK reveals about auth, endpoints, cert files. Avoid re-doing this analysis. |
| [`workflow_conventions.md`](workflow_conventions.md) | git-LFS quirks, worktree setup, where credentials live, build commands. |

When picking up auth-rewrite work after a break, start with
`kohler_api_auth_parked.md` — it has the resume path.
