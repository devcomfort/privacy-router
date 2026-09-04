"""Fernet 암호화 유틸리티 테스트."""

import pytest

from masker import decrypt_text, encrypt_text, generate_key


def test_encrypt_decrypt_round_trip_for_utf8_text() -> None:
    original = "합성 개인정보와 English secret"
    key = generate_key()

    encrypted = encrypt_text(original, key)

    assert encrypted != original
    assert decrypt_text(encrypted, key) == original


def test_each_encryption_uses_a_fresh_ciphertext() -> None:
    key = generate_key()

    first = encrypt_text("same value", key)
    second = encrypt_text("same value", key)

    assert first != second
    assert decrypt_text(first, key) == decrypt_text(second, key) == "same value"


def test_decrypt_with_wrong_key_fails_closed() -> None:
    encrypted = encrypt_text("private value", generate_key())

    with pytest.raises(ValueError, match="복호화되지 않습니다"):
        decrypt_text(encrypted, generate_key())


def test_empty_text_round_trip() -> None:
    key = generate_key()

    assert decrypt_text(encrypt_text("", key), key) == ""
