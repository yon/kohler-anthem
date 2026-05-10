"""Unit tests for konnect_signin.py — text-safety + env expansion."""

from __future__ import annotations

import konnect_signin as ks
import pytest


@pytest.mark.parametrize(
    "text,is_safe",
    [
        ("sijroc-6hiZbi-cipjas", True),
        ("Plain123", True),
        ("foo@bar.com", True),    # @ is in the whitelist (emails are common usernames)
        ("with space", False),    # space → must be substituted, not in regex
        ("evil; rm -rf /", False),
        ("$(rm -rf /)", False),
        ("`whoami`", False),
        ("has'quote", False),
        ("has\"doublequote", False),
        ("", False),
    ],
)
def test_safe_text_re(text: str, is_safe: bool) -> None:
    assert bool(ks.SAFE_TEXT_RE.match(text)) is is_safe


def test_adb_text_rejects_unsafe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(ks, "run", lambda cmd, **kw: calls.append(cmd))
    with pytest.raises(ValueError, match="unsupported by safe auto-type"):
        ks.adb_text("/path/to/adb", "evil; rm -rf /")
    assert calls == []  # no command should have been run


def test_adb_text_runs_for_safe_input(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return FakeResult()

    monkeypatch.setattr(ks, "run", fake_run)
    ks.adb_text("/path/to/adb", "Plain123")
    assert len(calls) == 1
    assert calls[0][:5] == ["/path/to/adb", "shell", "input", "text", "'Plain123'"] or \
        calls[0][:4] == ["/path/to/adb", "shell", "input", "text"]


def test_expand_env_refs() -> None:
    env = {"KOHLER_USERNAME": "alice@x.com", "KOHLER_PASSWORD": "secret"}
    assert ks.expand_env_refs("$KOHLER_USERNAME", env) == "alice@x.com"
    assert ks.expand_env_refs("hello $KOHLER_USERNAME world", env) == "hello alice@x.com world"
    # Undefined refs left alone
    assert ks.expand_env_refs("$UNDEFINED_VAR", env) == "$UNDEFINED_VAR"
    # Plain text passes through
    assert ks.expand_env_refs("no refs here", env) == "no refs here"
