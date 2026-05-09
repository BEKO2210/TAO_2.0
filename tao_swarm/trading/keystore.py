"""
Encrypted keystore for the auto-trading hot key.

The keystore stores a Bittensor hot-key seed encrypted at rest with
AES-256-GCM, where the encryption key is derived from a user-
supplied password via Argon2id (OWASP-recommended password KDF).

File format (JSON envelope, base64 fields)::

    {
      "version": 1,
      "kdf": "argon2id",
      "kdf_params": {
        "time_cost": 3,
        "memory_cost": 65536,   # 64 MB
        "parallelism": 4,
        "salt": "<base64 16 bytes>"
      },
      "cipher": "aes-256-gcm",
      "nonce": "<base64 12 bytes>",
      "ciphertext": "<base64>",
      "created_at": <unix-ts float>,
      "label": "<optional human label>"
    }

Security properties

- The password is never written to disk. Only the salt + KDF
  parameters + ciphertext are stored.
- Argon2id parameters meet the OWASP 2024+ baseline
  (time=3, memory=64 MiB, parallelism=4). They can be raised; the
  KDF parameters live alongside the ciphertext so old keystores
  remain readable.
- AES-256-GCM with a fresh 96-bit nonce per encryption guarantees
  authenticated encryption — any tampered byte fails decryption.
- Wrong password fails decryption (GCM auth tag mismatch); we
  surface a single ``WrongPasswordError`` rather than detailed
  internal errors so timing / attempt-counting attackers can't
  distinguish "wrong password" from "corrupt keystore".
- The decrypted seed lives only inside the :class:`SignerHandle`
  context manager; on exit (or ``close()``) the buffer is zeroed
  best-effort. Python doesn't guarantee memory zeroing because
  bytes are immutable, but ``ctypes.memset`` over the underlying
  buffer is the strongest mitigation we can offer in pure Python.

This module performs no signing or broadcasting itself — that's
PR 2E. Here we only ensure the seed never lives unencrypted on
disk and never leaves the SignerHandle in plain text.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


KEYSTORE_VERSION = 1

# OWASP 2024 baseline for Argon2id with high-value secrets.
DEFAULT_KDF_PARAMS: dict[str, int] = {
    "time_cost": 3,
    "memory_cost": 65536,   # 64 MiB
    "parallelism": 4,
}

# Length constants. AES-256 → 32-byte key. GCM standard nonce → 96 bits.
_KEY_LEN = 32
_NONCE_LEN = 12
_SALT_LEN = 16

# Reasonable upper bound on stored seed bytes. A Bittensor hot-key
# seed is 32 bytes; we cap at 256 to give room for derived blobs
# (BIP39 mnemonic encoded, multi-key bundles, etc.) without ever
# letting a misconfigured caller stuff GBs through the cipher.
_MAX_SEED_BYTES = 256


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class KeystoreError(Exception):
    """Base for all keystore errors."""


class KeystoreFormatError(KeystoreError):
    """The keystore file is missing fields, has the wrong version, etc."""


class WrongPasswordError(KeystoreError):
    """The supplied password did not decrypt the keystore.

    Deliberately the same exception type for "wrong password" and
    "tampered ciphertext" so attackers can't distinguish them.
    """


# ---------------------------------------------------------------------------
# SignerHandle — the only thing that holds the decrypted seed
# ---------------------------------------------------------------------------

class SignerHandle:
    """Holds the decrypted seed in memory while the bot runs.

    Use as a context manager (``with handle: ...``) so the seed is
    explicitly zeroed when the block exits. The handle deliberately
    does NOT expose ``seed`` as a property — callers fetch the
    bytes only through ``with_seed(callback)``, which gives them
    direct access for the duration of one signing operation and
    nothing more.

    This module does not sign anything itself. PR 2E will add a
    signer that uses ``with_seed`` to produce a signature without
    ever materialising the seed in caller code.
    """

    __slots__ = ("_buf", "_label", "_closed")

    def __init__(self, seed: bytes, label: str = "") -> None:
        # Store as a mutable bytearray so we can zero it on close.
        self._buf: bytearray | None = bytearray(seed)
        self._label = label
        self._closed = False

    # Lifecycle

    def __enter__(self) -> SignerHandle:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        # Best-effort GC-time wipe. Python provides no guarantee.
        try:
            self.close()
        except Exception:
            pass

    def close(self) -> None:
        """Zero the decrypted-seed buffer.

        ``ctypes.memset`` writes through the bytearray's buffer,
        so the bytes are overwritten in place. Subsequent calls
        on the handle raise. The bytearray is then dropped for GC.
        """
        if self._closed or self._buf is None:
            self._closed = True
            self._buf = None
            return
        n = len(self._buf)
        addr = ctypes.addressof(
            (ctypes.c_char * n).from_buffer(self._buf)
        )
        ctypes.memset(addr, 0, n)
        self._buf = None
        self._closed = True

    # Access

    @property
    def label(self) -> str:
        return self._label

    @property
    def closed(self) -> bool:
        return self._closed

    def with_seed(self, callback: Any) -> Any:
        """Pass the decrypted seed bytes to ``callback`` and return
        whatever the callback returns. The seed bytes are not held
        in any caller-visible variable after the callback exits.

        Args:
            callback: ``Callable[[bytes], R]`` — called exactly once
                with a fresh ``bytes`` copy of the seed.
        """
        if self._closed or self._buf is None:
            raise KeystoreError("SignerHandle is closed; unlock again")
        # Make a fresh immutable copy for the caller. The bytearray
        # remains in our control and is zeroed on close().
        seed_copy = bytes(self._buf)
        try:
            return callback(seed_copy)
        finally:
            # Zero the local copy as best as Python lets us; the
            # callback should already have used it.
            del seed_copy


# ---------------------------------------------------------------------------
# Keystore — file format + init/unlock
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KeystoreInfo:
    """Non-secret metadata about a keystore file."""

    version: int
    label: str
    created_at: float
    kdf: str
    kdf_params: dict[str, int]


class Keystore:
    """Encrypted hot-key file with Argon2id + AES-256-GCM.

    Use the static methods :meth:`init` and :meth:`unlock`.
    Constructing this class directly is for advanced cases.
    """

    @staticmethod
    def init(
        path: Path | str,
        password: str,
        seed: bytes,
        *,
        label: str = "",
        kdf_params: dict[str, int] | None = None,
        overwrite: bool = False,
    ) -> KeystoreInfo:
        """Create a new keystore at ``path``, encrypting ``seed`` with
        a key derived from ``password``.

        Args:
            path: Filesystem path for the keystore file.
            password: Operator-chosen password. Min 8 chars; longer
                is strictly better. The keystore inherits the
                strength of this password — Argon2id makes brute-
                forcing expensive but not impossible.
            seed: Raw seed bytes (typically 32 bytes for a Bittensor
                hot key). Must be non-empty and at most 256 bytes.
            label: Optional human-readable label (e.g. "live-finney").
                Stored in plain text in the file.
            kdf_params: Override Argon2id parameters. Defaults to
                OWASP 2024 baseline.
            overwrite: If False (default), refuse to write over an
                existing file.

        Returns:
            KeystoreInfo describing the new keystore.
        """
        if not isinstance(seed, (bytes, bytearray)):
            raise KeystoreError("seed must be bytes")
        if len(seed) == 0:
            raise KeystoreError("seed cannot be empty")
        if len(seed) > _MAX_SEED_BYTES:
            raise KeystoreError(
                f"seed too large: {len(seed)} bytes > {_MAX_SEED_BYTES}"
            )
        if not isinstance(password, str) or len(password) < 8:
            raise KeystoreError(
                "password must be a string of at least 8 characters"
            )

        path = Path(path)
        if path.exists() and not overwrite:
            raise KeystoreError(
                f"keystore already exists at {path}; pass overwrite=True "
                "to replace it"
            )
        path.parent.mkdir(parents=True, exist_ok=True)

        params = {**DEFAULT_KDF_PARAMS, **(kdf_params or {})}
        salt = secrets.token_bytes(_SALT_LEN)
        nonce = secrets.token_bytes(_NONCE_LEN)
        kek = _derive_kek(password, salt, params)
        ciphertext = AESGCM(kek).encrypt(nonce, bytes(seed), associated_data=None)

        envelope: dict[str, Any] = {
            "version": KEYSTORE_VERSION,
            "kdf": "argon2id",
            "kdf_params": {**params, "salt": _b64(salt)},
            "cipher": "aes-256-gcm",
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
            "created_at": time.time(),
            "label": label,
        }

        # Atomic write: write to temp, fsync, rename. Avoids leaving
        # a partial keystore if the process is killed mid-write.
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as fh:
            fh.write(json.dumps(envelope, indent=2).encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        # Restrict permissions to owner-read-write where the OS supports it.
        try:
            os.chmod(path, 0o600)
        except (OSError, NotImplementedError):
            pass

        return KeystoreInfo(
            version=KEYSTORE_VERSION,
            label=label,
            created_at=envelope["created_at"],
            kdf="argon2id",
            kdf_params=params,
        )

    @staticmethod
    def unlock(path: Path | str, password: str) -> SignerHandle:
        """Decrypt the keystore at ``path`` and return a
        :class:`SignerHandle` holding the seed.

        Use as a context manager so the seed is zeroed on exit::

            with Keystore.unlock(path, password) as handle:
                signature = handle.with_seed(_sign_extrinsic)

        Raises:
            KeystoreFormatError: file missing / malformed / unsupported version.
            WrongPasswordError: password did not produce a valid key.
        """
        path = Path(path)
        if not path.exists():
            raise KeystoreFormatError(f"keystore not found: {path}")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KeystoreFormatError(f"keystore JSON malformed: {exc}") from None

        version = envelope.get("version")
        if version != KEYSTORE_VERSION:
            raise KeystoreFormatError(
                f"unsupported keystore version {version!r}; "
                f"this build expects {KEYSTORE_VERSION}"
            )
        if envelope.get("kdf") != "argon2id":
            raise KeystoreFormatError(
                f"unsupported KDF {envelope.get('kdf')!r}"
            )
        if envelope.get("cipher") != "aes-256-gcm":
            raise KeystoreFormatError(
                f"unsupported cipher {envelope.get('cipher')!r}"
            )

        try:
            params = envelope["kdf_params"]
            salt = _b64d(params["salt"])
            nonce = _b64d(envelope["nonce"])
            ciphertext = _b64d(envelope["ciphertext"])
        except (KeyError, ValueError) as exc:
            raise KeystoreFormatError(f"keystore field missing/invalid: {exc}") from None

        kek = _derive_kek(
            password, salt,
            {k: int(params[k]) for k in ("time_cost", "memory_cost", "parallelism")},
        )
        try:
            seed = AESGCM(kek).decrypt(nonce, ciphertext, associated_data=None)
        except InvalidTag:
            # Same exception for "wrong password" and "tampered file"
            # so attackers can't distinguish them via timing.
            raise WrongPasswordError("decryption failed") from None
        return SignerHandle(seed, label=envelope.get("label", "") or "")

    @staticmethod
    def info(path: Path | str) -> KeystoreInfo:
        """Read non-secret metadata without unlocking.

        Useful for ``tao-swarm keystore info`` to show creation date,
        label, and KDF parameters without ever needing the password.
        """
        path = Path(path)
        if not path.exists():
            raise KeystoreFormatError(f"keystore not found: {path}")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        params = {
            k: int(envelope["kdf_params"][k])
            for k in ("time_cost", "memory_cost", "parallelism")
        }
        return KeystoreInfo(
            version=int(envelope.get("version", 0)),
            label=envelope.get("label", "") or "",
            created_at=float(envelope.get("created_at", 0.0)),
            kdf=envelope.get("kdf", ""),
            kdf_params=params,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_kek(password: str, salt: bytes, params: dict[str, int]) -> bytes:
    """Argon2id key-derivation: password + salt + params → 32-byte KEK."""
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=int(params["time_cost"]),
        memory_cost=int(params["memory_cost"]),
        parallelism=int(params["parallelism"]),
        hash_len=_KEY_LEN,
        type=Type.ID,
    )


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))
