"""Fernet encryption for OAuth tokens and SMTP passwords at rest."""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
_fernet = None
if _KEY:
    try:
        _fernet = Fernet(_KEY.encode())
    except (ValueError, InvalidToken) as exc:
        logger.error("TOKEN_ENCRYPTION_KEY is invalid (not valid Fernet key): %s", exc)
        _fernet = None


def encrypt_token(plaintext: str) -> str:
    """Encrypt a plaintext string. Raises RuntimeError if key not configured."""
    if _fernet is None:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY not configured or invalid. Generate with: "
            "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Raises RuntimeError if key not configured.
    Raises InvalidToken if ciphertext is tampered or key mismatches."""
    if _fernet is None:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY not configured or invalid. Generate with: "
            "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return _fernet.decrypt(ciphertext.encode()).decode()
