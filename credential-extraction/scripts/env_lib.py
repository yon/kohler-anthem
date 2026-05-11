"""Shared env-file + path + process helpers for the credential-extraction harness.

The harness reads secrets and paths from a `.env` file in the project root,
which is normally a symlink to `/Volumes/ring/env/kohler.env`. Loading happens
here instead of relying on the shell environment so the scripts work the same
whether invoked from a fresh shell, from Make, or from CI.

Other niceties live here so the per-step scripts stay small:
  * `HarnessEnv.require()` — clear errors when keys are missing
  * `MissingEnvError` — caught by the orchestrator, not raised as SystemExit
  * `chmod_owner_only` / `secure_mkdir` — explicit 0o700/0o600 so we don't
    rely on the process umask
  * `find_*` — tool discovery that includes the project venv
  * `run` / `run_checked` — subprocess helpers with structured error output
  * `wait_for_port` — readiness probe (used instead of `time.sleep(N)`)
  * `RunContext` — per-harness-run logging directory under
    `<cache>/harness-runs/<timestamp>/`
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACTION_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = EXTRACTION_DIR.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
EXAMPLE_ENV_FILE = EXTRACTION_DIR / "env.example"
DEFAULT_CACHE_FALLBACK = EXTRACTION_DIR / ".build" / "cache"
VENV_DIR = PROJECT_ROOT / ".venv"

# Match `export KEY=value`, `KEY=value`, `KEY="value with spaces"`, etc.
# Comments (#) and blank lines are skipped. Values may be quoted.
_ENV_LINE = re.compile(
    r"""^
    (?:export\s+)?              # optional `export `
    (?P<key>[A-Za-z_][A-Za-z0-9_]*)
    \s*=\s*
    (?:
        "(?P<dq>(?:[^"\\]|\\.)*)" |   # double-quoted value
        '(?P<sq>(?:[^'\\]|\\.)*)' |   # single-quoted value
        (?P<bare>[^\s#]*)             # bare value (stops at whitespace/comment)
    )
    \s*(?:\#.*)?$
    """,
    re.VERBOSE,
)


class HarnessError(Exception):
    """Base for harness-specific errors. Caught by the orchestrator."""


class MissingEnvError(HarnessError):
    """One or more required env keys were not set."""

    def __init__(self, missing: list[str], env_file: Path) -> None:
        self.missing = list(missing)
        self.env_file = env_file
        super().__init__(
            f"missing required env vars: {', '.join(missing)} "
            f"(set in {env_file})"
        )


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a shell-style env file into a dict.

    Handles `export KEY=value` and quoted values. Ignores comments and blanks.
    Raises FileNotFoundError if path doesn't exist.
    """
    result: dict[str, str] = {}
    text = path.read_text()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        key = match.group("key")
        value = match.group("dq") or match.group("sq") or match.group("bare") or ""
        result[key] = value
    return result


@dataclass(frozen=True)
class HarnessEnv:
    """Parsed env values + resolved harness paths."""

    values: dict[str, str]
    env_file: Path
    cache_dir: Path
    env_file_resolved: Path

    def require(self, *keys: str) -> dict[str, str]:
        """Return values for keys; raise MissingEnvError if any are missing/empty."""
        missing = [k for k in keys if not self.values.get(k)]
        if missing:
            raise MissingEnvError(missing, self.env_file)
        return {k: self.values[k] for k in keys}

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def cache_subdir(self, name: str) -> Path:
        path = self.cache_dir / name
        secure_mkdir(path)
        return path

    def env_file_exists(self) -> bool:
        return self.env_file_resolved.exists()


def _expand(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


def load_env(env_file: Path | None = None) -> HarnessEnv:
    """Load the harness env file. Falls back to os.environ values where applicable.

    Order of precedence for each key:
      1. value in the env file (if file exists and key is set + non-empty)
      2. value in os.environ
      3. unset (caller can default or raise via .require)
    """
    target = env_file or DEFAULT_ENV_FILE
    resolved = target.resolve() if target.exists() else target
    file_values: dict[str, str] = {}
    if target.exists():
        file_values = parse_env_file(target)

    merged = dict(os.environ)
    merged.update({k: _expand(v) for k, v in file_values.items() if v})

    cache_raw = merged.get("KOHLER_HARNESS_CACHE", "").strip()
    cache_dir = Path(_expand(cache_raw)) if cache_raw else DEFAULT_CACHE_FALLBACK
    secure_mkdir(cache_dir)

    return HarnessEnv(
        values=merged,
        env_file=target,
        cache_dir=cache_dir,
        env_file_resolved=resolved,
    )


# --- permission helpers -----------------------------------------------------

def secure_mkdir(path: Path, mode: int = 0o700) -> None:
    """Create the directory (parents included) and force owner-only perms.

    Doesn't rely on the process umask. Re-applies mode on existing dirs in case
    they were created earlier with a looser umask.
    """
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(mode)


def chmod_owner_only(path: Path, mode: int = 0o600) -> None:
    """Force a file to owner-only readable/writable."""
    with contextlib.suppress(OSError):
        path.chmod(mode)


# --- tool discovery ---------------------------------------------------------

def find_tool(*candidates: str) -> str | None:
    """Return the first tool path that resolves. Accepts bare names or absolute paths."""
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_frida() -> str | None:
    return find_tool(str(VENV_DIR / "bin" / "frida"), "frida")


def find_mitmdump() -> str | None:
    return find_tool(str(VENV_DIR / "bin" / "mitmdump"), "mitmdump")


def find_adb() -> str | None:
    return find_tool("adb")


def find_openssl() -> str | None:
    return find_tool("openssl")


def find_apksigner() -> str | None:
    return find_tool(
        "apksigner",
        "/opt/homebrew/share/android-commandlinetools/build-tools/35.0.0/apksigner",
    )


def find_python() -> str:
    """Project venv Python if present, else sys.executable."""
    venv_python = VENV_DIR / "bin" / "python3"
    return str(venv_python) if venv_python.exists() else os.environ.get("PYTHON", "python3")


def venv_exists() -> bool:
    return (VENV_DIR / "bin" / "python3").exists()


# --- subprocess helpers -----------------------------------------------------

def run(
    cmd: list[str],
    *,
    check: bool = False,
    capture: bool = True,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess. capture=True keeps stdout/stderr; stdin sends a string in."""
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=capture,
        text=True,
        check=check,
        env=env,
        timeout=timeout,
    )


def run_checked(
    cmd: list[str],
    *,
    error_prefix: str = "",
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and raise HarnessError with full stdout/stderr on failure."""
    result = run(cmd, env=env, stdin=stdin, timeout=timeout)
    if result.returncode != 0:
        msg_parts = []
        if error_prefix:
            msg_parts.append(error_prefix)
        msg_parts.append(f"command: {' '.join(cmd)}")
        msg_parts.append(f"exit:    {result.returncode}")
        if result.stdout.strip():
            msg_parts.append(f"stdout:  {result.stdout.strip()}")
        if result.stderr.strip():
            msg_parts.append(f"stderr:  {result.stderr.strip()}")
        raise HarnessError("\n".join(msg_parts))
    return result


def adb_device_connected() -> bool:
    """Return True if at least one device shows `device` status."""
    adb = find_adb()
    if not adb:
        return False
    result = run([adb, "devices"])
    if result.returncode != 0:
        return False
    return any("\tdevice" in line for line in result.stdout.strip().splitlines()[1:])


def wait_for_port(host: str, port: int, *, timeout: float = 10.0) -> bool:
    """Block until a TCP port accepts connections, or timeout. Returns True if reachable."""
    deadline = dt.datetime.now() + dt.timedelta(seconds=timeout)
    while dt.datetime.now() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            pass
    return False


def port_in_use(port: int, *, host: str = "127.0.0.1") -> bool:
    """Return True if something is already listening on the port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


# --- per-run logging directory ---------------------------------------------

@dataclass(frozen=True)
class RunContext:
    """Per-harness-run output directory + log path.

    Created via `RunContext.new(env)`. Caller passes `run_ctx.log_path` to
    subprocess `stdout`/`stderr` (or use `tee_to_log`) so every step's output
    accumulates in one place.
    """

    run_dir: Path
    log_path: Path
    summary_path: Path
    versions_path: Path
    timestamp: str

    @classmethod
    def new(cls, env: HarnessEnv) -> RunContext:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = env.cache_subdir("harness-runs") / ts
        secure_mkdir(run_dir)
        return cls(
            run_dir=run_dir,
            log_path=run_dir / "run.log",
            summary_path=run_dir / "summary.json",
            versions_path=run_dir / "versions.json",
            timestamp=ts,
        )


def utc_now_iso() -> str:
    """Timezone-aware UTC ISO timestamp, compatible with Python 3.9+."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Write a file atomically (write to .tmp, fsync, rename) with owner-only perms."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    chmod_owner_only(path, mode)


def atomic_write_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    chmod_owner_only(path, mode)


def atomic_symlink(target: str, link_path: Path) -> None:
    """Atomically point `link_path` at `target` (which is a name relative to its parent)."""
    tmp = link_path.with_name(link_path.name + ".tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    tmp.symlink_to(target)
    os.replace(tmp, link_path)
