"""AES-256-GCM helper for llm_configs.api_key.

Format on disk (BYTEA):
    [12-byte nonce] || [ciphertext] || [16-byte GCM tag]

The tag is appended automatically by AESGCM.encrypt(); we ship the
nonce alongside the ciphertext so the decryptor knows which IV was used.

ENCRYPTION_KEY is 64 hex chars = 32 raw bytes (256 bits). If the env
var is missing or malformed we fail fast at construction time — no
plaintext fallback is ever returned.
"""
from __future__ import annotations

import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


_NONCE_SIZE = 12     # AES-GCM standard
_KEY_BYTES = 32      # AES-256


class CryptoError(Exception):
    """Bad key / decrypt failure / corrupt blob."""


class ApiKeyCipher:
    """Symmetric AES-256-GCM cipher bound to ENCRYPTION_KEY."""

    def __init__(self, key_hex: str):
        try:
            key = bytes.fromhex(key_hex.strip())
        except ValueError as e:
            raise CryptoError(f"ENCRYPTION_KEY is not valid hex: {e}") from e
        if len(key) != _KEY_BYTES:
            raise CryptoError(
                f"ENCRYPTION_KEY must be {_KEY_BYTES} bytes ({_KEY_BYTES * 2} hex chars), "
                f"got {len(key)} bytes"
            )
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: str) -> bytes:
        if plaintext is None:
            raise CryptoError("encrypt: plaintext is None")
        nonce = os.urandom(_NONCE_SIZE)
        ct = self._aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ct

    def decrypt(self, blob: bytes) -> str:
        if blob is None or len(blob) <= _NONCE_SIZE:
            raise CryptoError("decrypt: blob too short")
        nonce, ct = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
        try:
            pt = self._aes.decrypt(nonce, ct, None)
        except Exception as e:
            # Authentication failure or wrong key — never expose details.
            raise CryptoError("decrypt failed (wrong key or corrupt blob)") from e
        return pt.decode("utf-8")

    @staticmethod
    def mask(api_key: str, keep_prefix: int = 4) -> str:
        """Return 'abcd****' for admin GET responses. Never log raw key."""
        if not api_key:
            return ""
        if len(api_key) <= keep_prefix:
            return "****"
        return api_key[:keep_prefix] + "****"


def cipher_from_env() -> ApiKeyCipher:
    raw = os.environ.get("ENCRYPTION_KEY", "")
    if not raw:
        raise CryptoError("ENCRYPTION_KEY env var is empty")
    return ApiKeyCipher(raw)
