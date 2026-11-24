"""Application-level cryptographic helpers for OAuth credentials and CSRF/PKCE state."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class EncryptionConfigError(RuntimeError):
    """Raised when OAUTH_ENCRYPTION_KEY is missing or invalid."""


class EncryptionOperationError(RuntimeError):
    """Raised when encrypting or decrypting sensitive credentials fails."""


def _get_fernet() -> Fernet:
    from clipyyy.config import get_oauth_encryption_key

    key = get_oauth_encryption_key()
    if not key:
        raise EncryptionConfigError(
            "OAUTH_ENCRYPTION_KEY is not configured. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise EncryptionConfigError(
            "OAUTH_ENCRYPTION_KEY is invalid. It must be a valid 32-byte url-safe base64 Fernet key."
        ) from exc


def validate_encryption_key() -> tuple[bool, str]:
    """Return whether OAUTH_ENCRYPTION_KEY is configured and valid (without revealing it)."""
    try:
        _get_fernet()
        return True, "OAUTH_ENCRYPTION_KEY configured"
    except EncryptionConfigError as exc:
        return False, str(exc)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a sensitive string using authenticated encryption (Fernet)."""
    if not plaintext:
        raise ValueError("Cannot encrypt an empty secret")
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a sensitive string encrypted with ``encrypt_secret``."""
    if not ciphertext:
        raise ValueError("Cannot decrypt an empty ciphertext")
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionOperationError(
            "Stored OAuth credential could not be decrypted. Check OAUTH_ENCRYPTION_KEY."
        ) from exc


def encrypt_json(payload: dict[str, Any]) -> str:
    """Serialize and encrypt a JSON-compatible dict."""
    return encrypt_secret(json.dumps(payload, separators=(",", ":")))


def decrypt_json(ciphertext: str) -> dict[str, Any]:
    """Decrypt and parse a JSON dict encrypted with ``encrypt_json``."""
    raw = decrypt_secret(ciphertext)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise EncryptionOperationError("Decrypted payload is not a JSON object")
    return data


def hash_token(raw_token: str) -> str:
    """Return a SHA-256 hex digest for storing opaque tokens/states safely."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def generate_random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` using PKCE S256."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge

