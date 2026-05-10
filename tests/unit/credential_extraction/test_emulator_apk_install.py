"""Unit tests for emulator_apk_install.py — ABI matcher."""

from __future__ import annotations

from pathlib import Path

import emulator_apk_install as eai


def _touch_apk(parent: Path, name: str) -> Path:
    p = parent / name
    p.write_bytes(b"x")
    return p


def test_check_abi_match_unknown_abi_passes(tmp_path: Path) -> None:
    _touch_apk(tmp_path, "base.apk")
    ok, _msg = eai.check_abi_match(tmp_path, "weird-abi")
    assert ok is True


def test_check_abi_match_no_apks_fails(tmp_path: Path) -> None:
    ok, msg = eai.check_abi_match(tmp_path, "arm64-v8a")
    assert ok is False
    assert "no APKs" in msg


def test_check_abi_match_no_abi_splits_passes(tmp_path: Path) -> None:
    """If there are no ABI-specific splits at all, the base APK is universal."""
    _touch_apk(tmp_path, "base.apk")
    _touch_apk(tmp_path, "config.en.apk")
    _touch_apk(tmp_path, "config.xhdpi.apk")
    ok, _msg = eai.check_abi_match(tmp_path, "arm64-v8a")
    assert ok is True


def test_check_abi_match_matching_split_passes(tmp_path: Path) -> None:
    _touch_apk(tmp_path, "base.apk")
    _touch_apk(tmp_path, "config.arm64_v8a.apk")
    _touch_apk(tmp_path, "config.armeabi_v7a.apk")
    ok, msg = eai.check_abi_match(tmp_path, "arm64-v8a")
    assert ok is True
    assert "arm64-v8a matches" in msg


def test_check_abi_match_missing_split_fails(tmp_path: Path) -> None:
    _touch_apk(tmp_path, "base.apk")
    _touch_apk(tmp_path, "config.armeabi_v7a.apk")
    ok, msg = eai.check_abi_match(tmp_path, "x86_64")
    assert ok is False
    assert "x86_64" in msg
    assert "armeabi_v7a" in msg
