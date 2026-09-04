"""인메모리 민감 데이터 계약을 위한 Fernet 암호화 유틸리티."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


def generate_key() -> str:
    """새 Fernet 키를 URL-safe 문자열로 생성합니다."""
    return Fernet.generate_key().decode("ascii")


def encrypt_text(value: str, key: str) -> str:
    """주어진 Fernet 키로 문자열을 암호화합니다."""
    return Fernet(key.encode("ascii")).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(token: str, key: str) -> str:
    """주어진 Fernet 키로 암호문을 복호화합니다."""
    try:
        value = Fernet(key.encode("ascii")).decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        raise ValueError("암호문이 현재 키로 복호화되지 않습니다.") from exc
    return value.decode("utf-8")
