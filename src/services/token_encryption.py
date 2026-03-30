"""Fernet encryption for OAuth tokens and SMTP passwords at rest.

The Fernet key is loaded lazily on first use so that importing this module
never fails -- CLI commands that don't need encryption are unaffected.
"""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_fernet = None
_initialized = False

_GENERATE_HINT = (
    "TOKEN_ENCRYPTION_KEY not configured or invalid. Generate with: "
    'python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def _get_fernet() -> Fernet:
    """Return the module-level Fernet instance, initializing on first call.

    Raises ``RuntimeError`` if TOKEN_ENCRYPTION_KEY is missing or invalid.
    """
    global _fernet, _initialized
    if _initialized:
        if _fernet is None:
            raise RuntimeError(_GENERATE_HINT)
        return _fernet

    _initialized = True
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(_GENERATE_HINT)
    try:
        _fernet = Fernet(key.encode())
    except (ValueError, InvalidToken) as exc:
        logger.error("TOKEN_ENCRYPTION_KEY is invalid (not valid Fernet key): %s", exc)
        raise RuntimeError(_GENERATE_HINT) from exc
    return _fernet


def encrypt_token(plaintext: str) -> str:
    """Encrypt a plaintext string. Raises RuntimeError if key not configured."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Raises RuntimeError if key not configured.
    Raises InvalidToken if ciphertext is tampered or key mismatches."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def try_decrypt(value: str) -> str:
    """Attempt to decrypt *value*; return it unchanged if decryption fails.

    This supports backwards compatibility: values stored before encryption
    was enabled are returned as-is, while encrypted values are decrypted.
    """
    if not value:
        return value
    try:
        return decrypt_token(value)
    except (RuntimeError, InvalidToken):
        # Not encrypted or key not configured — return raw value
        return value
