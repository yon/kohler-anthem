"""Unit tests for credential-extraction/scripts/apk_fetch.py."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import apk_fetch
import env_lib
import pytest

# ---------------------------------------------------------------------------
# _version_from_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        # base64-encoded `_fn` (winudf CDN pattern)
        (
            "https://d-31.winudf.com/b/XAPK/abc?_fn=S09ITEVSIEtvbm5lY3RfMy4wLjNfQVBLUHVyZS54YXBr",
            "3.0.3",
        ),
        # plain `_fn`
        (
            "https://d.apkpure.com/b/XAPK/x?_fn=KOHLER Konnect_2.4.1_APKPure.xapk",
            "2.4.1",
        ),
        # 4-part version
        (
            "https://x/y?_fn=Foo_10.20.30.40_release.xapk",
            "10.20.30.40",
        ),
        # No version anywhere
        ("https://x/y?_fn=junk", None),
        # No _fn at all
        ("https://x/y?other=1", None),
        # Empty url
        ("", None),
    ],
)
def test_version_from_url(url: str, expected: str | None) -> None:
    assert apk_fetch._version_from_url(url) == expected


def test_version_re_validates() -> None:
    assert apk_fetch.VERSION_RE.match("1.2.3")
    assert apk_fetch.VERSION_RE.match("10.20")
    assert not apk_fetch.VERSION_RE.match("v1.2.3")
    assert not apk_fetch.VERSION_RE.match("not-a-version")


# ---------------------------------------------------------------------------
# _abis_in_dir — detects both `config.<abi>.apk` and `split_config.<abi>.apk`
# ---------------------------------------------------------------------------

def _touch(parent: Path, name: str) -> Path:
    p = parent / name
    p.write_bytes(b"x")
    return p


def test_abis_in_dir_split_config_style(tmp_path: Path) -> None:
    _touch(tmp_path, "base.apk")
    _touch(tmp_path, "split_config.arm64_v8a.apk")
    _touch(tmp_path, "split_config.en.apk")  # not an ABI
    assert apk_fetch._abis_in_dir(tmp_path) == ["arm64-v8a"]


def test_abis_in_dir_apkpure_config_style(tmp_path: Path) -> None:
    _touch(tmp_path, "base.apk")
    _touch(tmp_path, "config.armeabi_v7a.apk")
    _touch(tmp_path, "config.xhdpi.apk")  # not an ABI
    assert apk_fetch._abis_in_dir(tmp_path) == ["armeabi-v7a"]


def test_abis_in_dir_empty(tmp_path: Path) -> None:
    _touch(tmp_path, "base.apk")
    assert apk_fetch._abis_in_dir(tmp_path) == []


def test_abis_in_dir_multiple(tmp_path: Path) -> None:
    _touch(tmp_path, "split_config.arm64_v8a.apk")
    _touch(tmp_path, "config.x86_64.apk")
    assert apk_fetch._abis_in_dir(tmp_path) == ["arm64-v8a", "x86_64"]


# ---------------------------------------------------------------------------
# _is_lfs_pointer
# ---------------------------------------------------------------------------

def test_is_lfs_pointer_detects_pointer(tmp_path: Path) -> None:
    pointer = tmp_path / "pointer.apk"
    pointer.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:abc123\n"
        "size 100\n"
    )
    assert apk_fetch._is_lfs_pointer(pointer) is True


def test_is_lfs_pointer_returns_false_for_real_file(tmp_path: Path) -> None:
    real = tmp_path / "real.apk"
    real.write_bytes(b"PK\x03\x04\x00\x00\x00")
    assert apk_fetch._is_lfs_pointer(real) is False


# ---------------------------------------------------------------------------
# _sha256
# ---------------------------------------------------------------------------

def test_sha256_known_value(tmp_path: Path) -> None:
    f = tmp_path / "x"
    f.write_bytes(b"hello")
    # echo -n hello | shasum -a 256
    expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert apk_fetch._sha256(f) == expected


# ---------------------------------------------------------------------------
# load_manifest / verify_repo_apk
# ---------------------------------------------------------------------------

def _build_manifest_dir(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """Create a synthetic APK dir + manifest.json with correct hashes."""
    apk_dir = tmp_path / "konnect-apk"
    apk_dir.mkdir()
    apks: dict[str, str] = {}
    for name, content in files.items():
        path = apk_dir / name
        path.write_bytes(content)
        apks[name] = "sha256:" + apk_fetch._sha256(path)
    manifest = {
        "package": "com.kohler.hermoth",
        "version": "9.9.9",
        "source": "test",
        "abis_present": [],
        "apks": apks,
    }
    (apk_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return apk_dir


def test_load_manifest_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(env_lib.HarnessError, match="manifest missing"):
        apk_fetch.load_manifest(tmp_path / "no-such.json")


def test_verify_repo_apk_happy_path(tmp_path: Path) -> None:
    apk_dir = _build_manifest_dir(tmp_path, {
        "base.apk": b"PK\x03\x04base content",
        "split_config.arm64_v8a.apk": b"PK\x03\x04split content",
    })
    result = apk_fetch.verify_repo_apk(apk_dir=apk_dir)
    assert result.ok is True
    assert result.version == "9.9.9"


def test_verify_repo_apk_detects_hash_mismatch(tmp_path: Path) -> None:
    apk_dir = _build_manifest_dir(tmp_path, {
        "base.apk": b"PK\x03\x04original",
    })
    # Tamper after the manifest was written
    (apk_dir / "base.apk").write_bytes(b"PK\x03\x04tampered")
    result = apk_fetch.verify_repo_apk(apk_dir=apk_dir)
    assert result.ok is False
    assert any("HASH MISMATCH" in note for note in result.notes)


def test_verify_repo_apk_detects_lfs_pointer(tmp_path: Path) -> None:
    apk_dir = _build_manifest_dir(tmp_path, {
        "base.apk": b"PK\x03\x04real",
    })
    # Replace with an LFS pointer
    (apk_dir / "base.apk").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 100\n"
    )
    result = apk_fetch.verify_repo_apk(apk_dir=apk_dir)
    assert result.ok is False
    assert any("LFS POINTER" in note for note in result.notes)


def test_verify_repo_apk_detects_missing(tmp_path: Path) -> None:
    apk_dir = _build_manifest_dir(tmp_path, {
        "base.apk": b"PK\x03\x04real",
    })
    (apk_dir / "base.apk").unlink()
    result = apk_fetch.verify_repo_apk(apk_dir=apk_dir)
    assert result.ok is False
    assert any("MISSING" in note for note in result.notes)


# ---------------------------------------------------------------------------
# _extract_bundle
# ---------------------------------------------------------------------------

def test_extract_bundle_handles_xapk(tmp_path: Path) -> None:
    bundle = tmp_path / "x.xapk"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("base.apk", b"APK1")
        zf.writestr("config.en.apk", b"APK2")
        zf.writestr("manifest.xml", b"not-an-apk")
    out = tmp_path / "extracted"
    assert apk_fetch._extract_bundle(bundle, out) is True
    assert (out / "base.apk").read_bytes() == b"APK1"
    assert (out / "config.en.apk").read_bytes() == b"APK2"
    assert not (out / "manifest.xml").exists()


def test_extract_bundle_handles_single_apk(tmp_path: Path) -> None:
    """A malformed-zip file with the right magic gets copied as `base.apk`."""
    bundle = tmp_path / "tiny.apk"
    bundle.write_bytes(b"PK\x03\x04incomplete-zip")
    out = tmp_path / "extracted"
    assert apk_fetch._extract_bundle(bundle, out) is True
    assert (out / "base.apk").exists()
