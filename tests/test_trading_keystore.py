"""
Tests for ``tao_swarm.trading.keystore`` — Argon2id + AES-256-GCM
encrypted hot-key storage.

Coverage:

- Round-trip: init + unlock returns the original seed.
- Wrong password: surfaces a ``WrongPasswordError``, not the
  underlying GCM ``InvalidTag``, so timing attackers can't
  distinguish "wrong password" from "tampered file".
- Tampered ciphertext: same handling as wrong password.
- Format errors: missing file, bad JSON, wrong version, wrong KDF
  / cipher all raise ``KeystoreFormatError``.
- ``info()`` reads metadata without the password.
- ``init()`` rejects empty seed, oversized seed, short password,
  non-bytes seed.
- ``init(overwrite=False)`` refuses to clobber an existing file.
- File mode is 0o600 on POSIX.
- ``SignerHandle`` zeroes the buffer on close.
- ``SignerHandle.with_seed()`` exposes the seed exactly once.
- ``SignerHandle`` raises after close.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from tao_swarm.trading.keystore import (
    DEFAULT_KDF_PARAMS,
    KEYSTORE_VERSION,
    Keystore,
    KeystoreFormatError,
    SignerHandle,
    WrongPasswordError,
)

# We use very low Argon2id parameters in tests so the suite stays fast.
# Production keystores keep the OWASP defaults via DEFAULT_KDF_PARAMS.
_FAST_PARAMS = {"time_cost": 1, "memory_cost": 1024, "parallelism": 1}

_SEED = b"\xab" * 32
_PWD = "correct horse battery staple"


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_round_trip_init_unlock_returns_same_seed(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS, label="hot1")
    with Keystore.unlock(path, _PWD) as h:
        captured: list[bytes] = []
        h.with_seed(lambda b: captured.append(b))
        assert captured == [_SEED]
        assert h.label == "hot1"


def test_round_trip_with_default_kdf_params_works(tmp_path):
    """A keystore created with the OWASP-baseline parameters must
    still round-trip — slow, but correct."""
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED)
    with Keystore.unlock(path, _PWD) as h:
        assert h.with_seed(lambda b: b) == _SEED


# ---------------------------------------------------------------------------
# Failure modes — wrong password / tampered file
# ---------------------------------------------------------------------------

def test_wrong_password_raises_wrong_password_error(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    with pytest.raises(WrongPasswordError):
        Keystore.unlock(path, "not the password")


def test_tampered_ciphertext_raises_wrong_password_error(tmp_path):
    """Same exception as wrong password — by design, so attackers
    can't distinguish corrupted file from wrong password."""
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    envelope = json.loads(path.read_text())
    # Flip a byte in the ciphertext (keep base64 valid).
    ct = envelope["ciphertext"]
    envelope["ciphertext"] = ("A" if ct[0] != "A" else "B") + ct[1:]
    path.write_text(json.dumps(envelope))
    with pytest.raises(WrongPasswordError):
        Keystore.unlock(path, _PWD)


# ---------------------------------------------------------------------------
# Format errors
# ---------------------------------------------------------------------------

def test_unlock_missing_file_raises_format_error(tmp_path):
    with pytest.raises(KeystoreFormatError):
        Keystore.unlock(tmp_path / "nope.json", _PWD)


def test_unlock_invalid_json_raises_format_error(tmp_path):
    path = tmp_path / "ks.json"
    path.write_text("not json {")
    with pytest.raises(KeystoreFormatError):
        Keystore.unlock(path, _PWD)


def test_unlock_wrong_version_raises_format_error(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    envelope = json.loads(path.read_text())
    envelope["version"] = 999
    path.write_text(json.dumps(envelope))
    with pytest.raises(KeystoreFormatError):
        Keystore.unlock(path, _PWD)


def test_unlock_wrong_kdf_raises_format_error(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    envelope = json.loads(path.read_text())
    envelope["kdf"] = "scrypt"
    path.write_text(json.dumps(envelope))
    with pytest.raises(KeystoreFormatError):
        Keystore.unlock(path, _PWD)


def test_unlock_wrong_cipher_raises_format_error(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    envelope = json.loads(path.read_text())
    envelope["cipher"] = "chacha20-poly1305"
    path.write_text(json.dumps(envelope))
    with pytest.raises(KeystoreFormatError):
        Keystore.unlock(path, _PWD)


def test_unlock_missing_field_raises_format_error(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    envelope = json.loads(path.read_text())
    del envelope["nonce"]
    path.write_text(json.dumps(envelope))
    with pytest.raises(KeystoreFormatError):
        Keystore.unlock(path, _PWD)


# ---------------------------------------------------------------------------
# init() input validation
# ---------------------------------------------------------------------------

def test_init_rejects_empty_seed(tmp_path):
    with pytest.raises(Exception):  # KeystoreError specifically
        Keystore.init(tmp_path / "k.json", _PWD, b"", kdf_params=_FAST_PARAMS)


def test_init_rejects_oversized_seed(tmp_path):
    with pytest.raises(Exception):
        Keystore.init(
            tmp_path / "k.json", _PWD, b"\x00" * 1024,
            kdf_params=_FAST_PARAMS,
        )


def test_init_rejects_non_bytes_seed(tmp_path):
    with pytest.raises(Exception):
        Keystore.init(
            tmp_path / "k.json", _PWD, "string-seed",  # type: ignore[arg-type]
            kdf_params=_FAST_PARAMS,
        )


def test_init_rejects_short_password(tmp_path):
    with pytest.raises(Exception):
        Keystore.init(
            tmp_path / "k.json", "short", _SEED, kdf_params=_FAST_PARAMS,
        )


def test_init_refuses_to_overwrite_by_default(tmp_path):
    path = tmp_path / "k.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    with pytest.raises(Exception):
        Keystore.init(path, _PWD, b"\x11" * 32, kdf_params=_FAST_PARAMS)


def test_init_overwrite_true_replaces_existing(tmp_path):
    path = tmp_path / "k.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    new_seed = b"\x11" * 32
    Keystore.init(path, _PWD, new_seed, kdf_params=_FAST_PARAMS, overwrite=True)
    with Keystore.unlock(path, _PWD) as h:
        assert h.with_seed(lambda b: b) == new_seed


# ---------------------------------------------------------------------------
# File permissions / atomicity
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "posix", reason="POSIX-only file mode test")
def test_keystore_file_has_owner_only_permissions(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_init_does_not_leave_temp_file(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    assert path.exists()
    # Atomic rename should leave no .tmp behind.
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# info() reads metadata without unlocking
# ---------------------------------------------------------------------------

def test_info_reads_metadata_without_password(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS, label="canary")
    info = Keystore.info(path)
    assert info.version == KEYSTORE_VERSION
    assert info.label == "canary"
    assert info.kdf == "argon2id"
    assert info.kdf_params == _FAST_PARAMS
    assert info.created_at > 0


# ---------------------------------------------------------------------------
# SignerHandle lifecycle
# ---------------------------------------------------------------------------

def test_signer_handle_close_zeroes_buffer():
    h = SignerHandle(b"\xff" * 16, label="x")
    h.close()
    assert h.closed is True
    with pytest.raises(Exception):
        h.with_seed(lambda b: b)


def test_signer_handle_context_manager_closes(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    handle = Keystore.unlock(path, _PWD)
    with handle as h:
        assert h.with_seed(lambda b: b) == _SEED
    assert handle.closed is True


def test_signer_handle_with_seed_passes_correct_bytes(tmp_path):
    path = tmp_path / "ks.json"
    Keystore.init(path, _PWD, _SEED, kdf_params=_FAST_PARAMS)
    seen: list[bytes] = []
    with Keystore.unlock(path, _PWD) as h:
        result = h.with_seed(lambda b: (seen.append(b), len(b))[1])
        assert seen[0] == _SEED
        assert result == 32


def test_signer_handle_does_not_expose_seed_property():
    """Lock in: the handle has no public ``seed`` attribute. The
    only way to access bytes is through with_seed(callback)."""
    h = SignerHandle(b"\xab" * 16)
    assert not hasattr(h, "seed")
    h.close()


# ---------------------------------------------------------------------------
# Default KDF params hardness sanity
# ---------------------------------------------------------------------------

def test_default_kdf_params_meet_owasp_baseline():
    """OWASP 2024 baseline for Argon2id: m=64MiB, t=3, p=4."""
    assert DEFAULT_KDF_PARAMS["memory_cost"] >= 65536
    assert DEFAULT_KDF_PARAMS["time_cost"] >= 3
    assert DEFAULT_KDF_PARAMS["parallelism"] >= 4
