"""Unit tests for agents.masker.crypto — encryption/decryption utilities.

No external dependencies. Pure function tests.
"""

from __future__ import annotations

from agents.masker import decrypt_field, encrypt_field, generate_key


class TestEncryptDecrypt:
    """Fernet encrypt/decrypt round-trip."""

    def test_round_trip(self):
        original = "901212-1234567"
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original

    def test_different_inputs_different_ciphertext(self):
        a = encrypt_field("hello")
        b = encrypt_field("world")
        assert a != b

    def test_empty_string(self):
        assert encrypt_field("") == ""
        assert decrypt_field("") == ""

    def test_korean_text(self):
        original = "홍길동 주민등록번호 901212-1234567"
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original

    def test_long_text(self):
        original = "A" * 10000
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original


class TestGenerateKey:
    """Key generation utility."""

    def test_generates_key(self):
        key = generate_key()
        assert isinstance(key, str)
        assert len(key) > 0

    def test_key_is_base64(self):
        key = generate_key()
        # Fernet keys are base64-encoded 32 bytes
        assert key.endswith("=")
