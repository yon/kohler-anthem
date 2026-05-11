#!/usr/bin/env python3
"""One-shot diagnostics snapshot for the credential-extraction harness.

Captures: tool versions, env-file presence + key list (values redacted),
emulator state, frida-server state on the device, mitmproxy CA presence
on the device, current Android proxy setting, cache layout, recent run
summaries.

Writes a Markdown report to `<cache>/doctor/<timestamp>.md` and prints the
same content. Useful when debugging a failed run or filing a bug report.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_lib import (
    PROJECT_ROOT,
    VENV_DIR,
    adb_device_connected,
    atomic_write_text,
    find_adb,
    find_frida,
    find_mitmdump,
    find_openssl,
    load_env,
    run,
    venv_exists,
)

ANDROID_CACERT_DIR = "/system/etc/security/cacerts"


def section(title: str, lines: list[str]) -> str:
    body = "\n".join(lines)
    return f"## {title}\n\n{body}\n"


def tool_versions() -> list[str]:
    out: list[str] = []
    for name, finder in [
        ("adb", find_adb),
        ("frida", find_frida),
        ("mitmdump", find_mitmdump),
        ("openssl", find_openssl),
    ]:
        path = finder()
        if not path:
            out.append(f"- **{name}**: NOT FOUND")
            continue
        result = run([path, "--version"], timeout=5)
        ver = ((result.stdout or result.stderr).strip().splitlines() or [""])[0]
        out.append(f"- **{name}**: {ver}  (`{path}`)")
    out.append(f"- **venv**: {'present' if venv_exists() else 'MISSING'} at `{VENV_DIR}`")
    return out


def env_status() -> list[str]:
    env = load_env()
    out = [
        f"- env file: `{env.env_file}` → `{env.env_file_resolved}`",
        f"- exists:   {env.env_file_exists()}",
        f"- cache:    `{env.cache_dir}`",
    ]
    if env.env_file_exists():
        keys = sorted(k for k in env.values if k.startswith("KOHLER_"))
        out.append(f"- keys present: {', '.join(keys) if keys else '(none)'}")
    return out


def avd_state() -> list[str]:
    """Inventory configured AVDs via avdmanager, if installed."""
    avdmanager = next(
        (p for p in [
            "/opt/homebrew/share/android-commandlinetools/cmdline-tools/latest/bin/avdmanager",
            "/usr/local/share/android-commandlinetools/cmdline-tools/latest/bin/avdmanager",
        ] if Path(p).is_file()),
        None,
    )
    if not avdmanager:
        return ["- avdmanager not found — install `make deps`"]
    listing = run([avdmanager, "list", "avd", "-c"])
    return [f"- AVDs: ```\n{listing.stdout.strip() or '(none)'}\n```"]


def device_state() -> list[str]:
    adb = find_adb()
    if not adb:
        return ["- adb not available — skipping"]
    if not adb_device_connected():
        return ["- no device connected via adb"]
    out: list[str] = []
    for label, args in [
        ("device", ["shell", "getprop", "ro.product.model"]),
        ("abi", ["shell", "getprop", "ro.product.cpu.abi"]),
        ("android", ["shell", "getprop", "ro.build.version.release"]),
        ("frida-server", ["shell", "pgrep", "-x", "frida-server"]),
        ("http_proxy", ["shell", "settings", "get", "global", "http_proxy"]),
        ("kohler app", ["shell", "pm", "list", "packages", "com.kohler.hermoth"]),
    ]:
        result = run([adb, *args])
        value = (result.stdout or result.stderr).strip() or "(empty)"
        out.append(f"- **{label}**: {value}")
    cacerts = run([adb, "shell", "ls", ANDROID_CACERT_DIR])
    out.append(
        f"- cacerts present: ```\n{(cacerts.stdout or cacerts.stderr).strip()[:1500]}\n```"
    )
    return out


def cache_layout(env_dir: Path) -> list[str]:
    if not env_dir.exists():
        return [f"- cache directory does not exist: `{env_dir}`"]
    out = [f"- root: `{env_dir}`"]
    for sub in sorted(env_dir.iterdir()):
        if not sub.is_dir():
            continue
        files = sorted(sub.iterdir())[:8]
        names = ", ".join(p.name for p in files) or "(empty)"
        out.append(f"- `{sub.name}/`: {names}")
    return out


def recent_runs(env_dir: Path, limit: int = 5) -> list[str]:
    runs_dir = env_dir / "harness-runs"
    if not runs_dir.exists():
        return ["- no harness-runs/ directory yet"]
    entries = sorted(runs_dir.iterdir(), reverse=True)[:limit]
    out: list[str] = []
    for entry in entries:
        summary = entry / "summary.json"
        if summary.exists():
            try:
                data = json.loads(summary.read_text())
                steps = data.get("steps", [])
                fails = [s["name"] for s in steps if s.get("exit_code", 0) != 0]
                marker = "OK" if data.get("overall_exit") == 0 else f"FAIL ({', '.join(fails)})"
                out.append(f"- {entry.name}: {marker}")
            except Exception as exc:
                out.append(f"- {entry.name}: summary parse error: {exc}")
        else:
            out.append(f"- {entry.name}: no summary.json")
    return out


def main() -> int:
    print()
    print("=" * 60)
    print("Harness doctor")
    print("=" * 60)
    print()

    env = load_env()
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    doctor_dir = env.cache_subdir("doctor")
    report_path = doctor_dir / f"{ts}.md"

    sections = [
        section("Versions", tool_versions()),
        section("Env / Secrets", env_status()),
        section("AVD", avd_state()),
        section("Device", device_state()),
        section("Cache layout", cache_layout(env.cache_dir)),
        section("Recent harness runs", recent_runs(env.cache_dir)),
    ]
    report = f"# Doctor report — {ts}\n\nproject: `{PROJECT_ROOT}`\n\n" + "\n".join(sections)
    atomic_write_text(report_path, report)
    print(report)
    print()
    print(f"  Report saved: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
