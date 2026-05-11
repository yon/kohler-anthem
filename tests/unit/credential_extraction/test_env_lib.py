"""Unit tests for credential-extraction/scripts/env_lib.py."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import env_lib
import pytest

# ---------------------------------------------------------------------------
# parse_env_file
# ---------------------------------------------------------------------------

def test_parse_env_file_simple(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_text(
        "# leading comment\n"
        "KEY1=value1\n"
        "export KEY2=value2\n"
        "\n"
        "# blank line above\n"
        "KEY3=\"quoted value\"\n"
        "KEY4='single quoted'\n"
    )
    result = env_lib.parse_env_file(file)
    assert result == {
        "KEY1": "value1",
        "KEY2": "value2",
        "KEY3": "quoted value",
        "KEY4": "single quoted",
    }


def test_parse_env_file_inline_comments_and_empty_values(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_text(
        "PRESENT=yes\n"
        "EMPTY=\n"
        "EXPORT_EMPTY=\n"
        "EXPORT_WITH_COMMENT=abc   # trailing comment\n"
    )
    result = env_lib.parse_env_file(file)
    assert result["PRESENT"] == "yes"
    assert result["EMPTY"] == ""
    assert result["EXPORT_EMPTY"] == ""
    assert result["EXPORT_WITH_COMMENT"] == "abc"


def test_parse_env_file_skips_malformed_lines(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_text("not an assignment\nKEY=ok\n=missing-key\n")
    result = env_lib.parse_env_file(file)
    assert result == {"KEY": "ok"}


# ---------------------------------------------------------------------------
# load_env / HarnessEnv.require
# ---------------------------------------------------------------------------

def test_load_env_missing_file_returns_env_with_empty_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KOHLER_HARNESS_CACHE", raising=False)
    monkeypatch.setenv("KOHLER_HARNESS_CACHE", str(tmp_path / "cache"))
    nonexistent = tmp_path / "no-env"
    env = env_lib.load_env(env_file=nonexistent)
    assert env.env_file == nonexistent
    # os.environ value still flows through
    assert env.cache_dir == tmp_path / "cache"


def test_load_env_env_file_overrides_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = tmp_path / "kohler.env"
    file.write_text("KOHLER_HARNESS_CACHE=" + str(tmp_path / "from-file") + "\nKEY=fromfile\n")
    monkeypatch.setenv("KEY", "fromenv")
    monkeypatch.setenv("KOHLER_HARNESS_CACHE", str(tmp_path / "from-environ"))
    env = env_lib.load_env(env_file=file)
    assert env.values["KEY"] == "fromfile"
    assert env.cache_dir == tmp_path / "from-file"


def test_load_env_expands_home_and_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = tmp_path / "kohler.env"
    file.write_text("KOHLER_HARNESS_CACHE=$HOME/test-cache\nPLAIN=$HOME/x\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    env = env_lib.load_env(env_file=file)
    assert env.cache_dir == tmp_path / "test-cache"
    assert env.values["PLAIN"] == str(tmp_path / "x")


def test_harness_env_require_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOHLER_HARNESS_CACHE", str(tmp_path / "cache"))
    env = env_lib.load_env(env_file=tmp_path / "missing")
    with pytest.raises(env_lib.MissingEnvError) as exc:
        env.require("X", "Y")
    assert set(exc.value.missing) >= {"X", "Y"}


def test_harness_env_require_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOO", "bar")
    monkeypatch.setenv("KOHLER_HARNESS_CACHE", str(tmp_path / "cache"))
    env = env_lib.load_env(env_file=tmp_path / "missing")
    assert env.require("FOO") == {"FOO": "bar"}


# ---------------------------------------------------------------------------
# secure_mkdir / chmod_owner_only / atomic_write_*
# ---------------------------------------------------------------------------

def test_secure_mkdir_sets_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "secrets-dir"
    env_lib.secure_mkdir(target)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o700


def test_chmod_owner_only_sets_0o600(tmp_path: Path) -> None:
    file = tmp_path / "x"
    file.write_text("data")
    file.chmod(0o644)
    env_lib.chmod_owner_only(file)
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_atomic_write_text_atomic_and_secure(tmp_path: Path) -> None:
    target = tmp_path / "secret.json"
    env_lib.atomic_write_text(target, '{"k":"v"}')
    assert target.read_text() == '{"k":"v"}'
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    # No leftover .tmp file
    assert not (tmp_path / "secret.json.tmp").exists()


def test_atomic_symlink_replaces_existing(tmp_path: Path) -> None:
    real_a = tmp_path / "a"
    real_b = tmp_path / "b"
    real_a.mkdir()
    real_b.mkdir()
    link = tmp_path / "latest"
    env_lib.atomic_symlink("a", link)
    assert os.readlink(link) == "a"
    env_lib.atomic_symlink("b", link)
    assert os.readlink(link) == "b"


# ---------------------------------------------------------------------------
# wait_for_port / port_in_use
# ---------------------------------------------------------------------------

def test_port_in_use_returns_false_for_random_high_port() -> None:
    # 65500 is almost never bound
    assert env_lib.port_in_use(65500) is False


def test_wait_for_port_times_out_quickly() -> None:
    # 65501 is almost never bound; wait should time out within ~1s
    import time
    start = time.time()
    assert env_lib.wait_for_port("127.0.0.1", 65501, timeout=1.0) is False
    assert time.time() - start < 3
