"""Unit tests for agents.masker — masking and hydration.

Tests the Masker class with opaque request-scoped placeholders.
No external dependencies.
"""

from __future__ import annotations

import pytest

from agents.masker import HydrationError, Masker, MaskingContract


class TestMaskerMask:
    """Test Masker.mask() with opaque request-scoped placeholders."""

    def test_single_record(self):
        masker = Masker()
        result = masker.mask(
            "주민등록번호 901212-1234567을 확인해주세요",
            [{"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 6, "end": 20}],
        )
        assert "901212-1234567" not in result.masked_text
        assert "SENSITIVE_DATA#" in result.masked_text
        assert result.contract.count == 1

    def test_placeholder_is_unlinkable_across_operations(self, monkeypatch):
        masker = Masker()
        records = [{"category": "PHONE", "span": "010-1234-5678", "start": 0, "end": 13}]
        tokens = iter(["deadbeef", "cafebabe"])
        monkeypatch.setattr(
            "agents.masker.masker.secrets.token_hex",
            lambda _length: next(tokens),
        )

        r1 = masker.mask("010-1234-5678", records)
        r2 = masker.mask("010-1234-5678", records)

        assert list(r1.contract.placeholder_map) == ["SENSITIVE_DATA#deadbeef"]
        assert list(r2.contract.placeholder_map) == ["SENSITIVE_DATA#cafebabe"]

    def test_multiple_records(self):
        masker = Masker()
        result = masker.mask(
            "주민번호 901212-1234567 전화 010-9876-5432",
            [
                {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 4, "end": 18},
                {"category": "MOBILE_PHONE_NUMBER", "span": "010-9876-5432", "start": 22, "end": 35},
            ],
        )
        assert result.contract.count == 2
        assert "901212-1234567" not in result.masked_text
        assert "010-9876-5432" not in result.masked_text

    def test_no_records(self):
        masker = Masker()
        result = masker.mask("hello world", [])
        assert result.masked_text == "hello world"
        assert result.contract.count == 0


class TestMaskerHydrate:
    """Test Masker.hydrate() — restore original values."""

    def test_hydrate_single(self):
        masker = Masker()
        contract = MaskingContract(
            placeholder_map={"PHONE#abc12345": "010-1234-5678"},
            count=1,
        )
        result = masker.hydrate("전화번호는 PHONE#abc12345입니다", contract)
        assert result.placeholders_restored == 1

    def test_hydrate_multiple(self):
        masker = Masker()
        contract = MaskingContract(
            placeholder_map={
                "RRN#a1b2c3d4": "901212-1234567",
                "PHONE#e5f6a7b8": "010-9876-5432",
            },
            count=2,
        )
        result = masker.hydrate("RRN#a1b2c3d4와 PHONE#e5f6a7b8", contract)
        assert result.hydrated_text == "901212-1234567와 010-9876-5432"
        assert result.placeholders_restored == 2

    def test_hydrate_repeated_placeholder_counts_every_occurrence(self):
        masker = Masker()
        contract = MaskingContract(
            placeholder_map={"PHONE#abc12345": "010-1234-5678"},
            count=1,
        )

        result = masker.hydrate(
            "PHONE#abc12345 또는 [PHONE#abc12345]",
            contract,
        )

        assert result.hydrated_text == "010-1234-5678 또는 010-1234-5678"
        assert result.placeholders_restored == 2

    def test_hydrate_unknown_placeholder_fails_closed(self):
        masker = Masker()
        contract = MaskingContract(
            placeholder_map={"PHONE#abc12345": "010-1234-5678"},
            count=1,
        )

        with pytest.raises(HydrationError) as exc_info:
            masker.hydrate("전화번호는 PHONE#deadbeef입니다", contract)

        assert exc_info.value.unresolved == ["PHONE#deadbeef"]

    def test_hydrate_no_placeholders(self):
        masker = Masker()
        contract = MaskingContract(placeholder_map={"X#1": "y"}, count=1)
        result = masker.hydrate("hello world", contract)
        assert result.hydrated_text == "hello world"
        assert result.placeholders_restored == 0

    def test_hydrate_with_brackets_backward_compat(self):
        """Hydration works even if contract has brackets (old format)."""
        masker = Masker()
        contract = MaskingContract(
            placeholder_map={"[PHONE#abc12345]": "010-1234-5678"},
            count=1,
        )
        # LLM stripped brackets
        result = masker.hydrate("전화번호는 PHONE#abc12345입니다", contract)
        assert result.hydrated_text == "전화번호는 010-1234-5678입니다"
        assert result.placeholders_restored == 1


class TestMaskerRoundTrip:
    """Full mask → hydrate round-trip."""

    def test_full_round_trip(self):
        masker = Masker()
        original = "주민등록번호 901212-1234567을 확인해주세요"
        records = [{"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 6, "end": 20}]

        masked = masker.mask(original, records)
        hydrated = masker.hydrate(masked.masked_text, masked.contract)

        assert hydrated.hydrated_text == original
