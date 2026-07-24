"""Encryption utility for Privacy Router.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256).
Master key resolution: configured environment key, or an ephemeral key in ``dev`` mode only.

Usage:
    from agents.masker.crypto import encrypt_field, decrypt_field

    encrypted = encrypt_field("901212-1234567")
    original = decrypt_field(encrypted)
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.fernet import Fernet

from server import get_runtime_mode


def _get_master_key() -> bytes:
    """Resolve the shared master key as bytes."""
    key = os.environ.get("PRIVACY_ROUTER_MASTER_KEY") or os.environ.get("MASKING_ENCRYPTION_KEY") or ""
    if not key:
        if get_runtime_mode() != "dev":
            raise RuntimeError("PRIVACY_ROUTER_MASTER_KEY is required outside dev mode")
        key = Fernet.generate_key().decode()
        os.environ["PRIVACY_ROUTER_MASTER_KEY"] = key
    return key.strip().encode()


def _get_fernet() -> Fernet:
    """Return a Fernet instance backed by the shared master key."""
    return Fernet(_get_master_key())


def generate_key() -> str:
    """Generate a new Fernet key. Returns base64-encoded string."""
    return Fernet.generate_key().decode()


def encrypt_field(plaintext: str) -> str:
    """Encrypt a string field. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a string field. Returns original plaintext."""
    if not ciphertext:
        return ""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


def _fingerprint(value: str, domain: bytes) -> str:
    """Return a keyed SHA-256 fingerprint within one explicit domain."""
    if not value:
        return ""
    return hmac.new(_get_master_key(), domain + b"\0" + value.encode(), hashlib.sha256).hexdigest()


def fingerprint_field(value: str) -> str:
    """Return a masking-record HMAC-SHA256 fingerprint."""
    return _fingerprint(value, b"privacy-router:masking-record")


def cache_fingerprint(value: str) -> str:
    """Return a cache-key HMAC-SHA256 fingerprint."""
    return _fingerprint(value, b"privacy-router:cache-key")
