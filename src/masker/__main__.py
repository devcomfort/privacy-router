"""Masker 암호화·복호화와 마스킹·복원 시연."""

from __future__ import annotations

from .crypto import decrypt_text, encrypt_text, generate_key
from .masker import Masker

_ENCRYPTION_SAMPLES = (
    ("사람 이름", "홍길동"),
    ("전화번호", "010-0000-0000"),
    ("주민등록번호", "000000-0000000"),
)


def main() -> None:
    """암호화/복호화 3건과 마스킹/복원 1건을 출력합니다."""
    key = generate_key()
    print("[Fernet 암호화·복호화]")
    for name, original in _ENCRYPTION_SAMPLES:
        encrypted = encrypt_text(original, key)
        decrypted = decrypt_text(encrypted, key)
        print(f"- {name}")
        print(f"  원문: {original}")
        print(f"  암호문: {encrypted}")
        print(f"  복호문: {decrypted}")
        print(f"  일치: {decrypted == original}")

    print("\n[Masker 마스킹·복원]")
    masker = Masker()
    original = "홍길동의 전화번호는 010-0000-0000이고 주민등록번호는 000000-0000000입니다."
    records = [
        {
            "category": "PERSON_NAME",
            "span": "홍길동",
            "start": 0,
            "end": 3,
        },
        {
            "category": "PHONE_NUMBER",
            "span": "010-0000-0000",
            "start": 11,
            "end": 24,
        },
        {
            "category": "RESIDENT_REGISTRATION_NUMBER",
            "span": "000000-0000000",
            "start": 35,
            "end": 49,
        },
    ]
    masked = masker.mask(original, records)
    restored = masker.hydrate(masked.masked_text, masked.contract)
    print(f"- 원문: {original}")
    print(f"- 마스킹: {masked.masked_text}")
    print(f"- 복원: {restored.hydrated_text}")
    print(f"- 일치: {restored.hydrated_text == original}")


if __name__ == "__main__":
    main()
