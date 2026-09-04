"""Tests for agents.masker — in-memory masking and hydration."""

from unittest.mock import patch

import pytest

from masker import (
    HydrationError,
    Masker,
    MaskingContract,
)

# ── crypto.py ────────────────────────────────────────────────────────────────


# ── MaskingContract ──────────────────────────────────────────────────────────


class TestMaskingContract:
    def test_validate_response_all_resolved(self):
        contract = MaskingContract(
            placeholder_map={"[RRN#1]": "901212-1234567", "[PHONE#1]": "010-1234-5678"},
            count=2,
        )
        unresolved = contract.validate_response("번호 [RRN#1]과 [PHONE#1]")
        assert unresolved == []

    def test_validate_response_has_unresolved(self):
        contract = MaskingContract(
            placeholder_map={"[RRN#1]": "901212-1234567"},
            count=1,
        )
        unresolved = contract.validate_response("번호 [RRN#1]과 [UNKNOWN_TAG#1]")
        assert "[UNKNOWN_TAG#1]" in unresolved

    def test_validate_response_no_placeholders(self):
        contract = MaskingContract(placeholder_map={"[RRN#1]": "val"}, count=1)
        unresolved = contract.validate_response("no placeholders here")
        assert unresolved == []

    def test_validate_response_empty_text(self):
        contract = MaskingContract(placeholder_map={"[RRN#1]": "val"}, count=1)
        unresolved = contract.validate_response("")
        assert unresolved == []


# ── Masker ───────────────────────────────────────────────────────────────────


class TestMasker:
    def test_mask_single_span(self):
        masker = Masker()
        text = "주민등록번호 901212-1234567 기재"
        records = [
            {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 7, "end": 21},
        ]
        result = masker.mask(text, records)
        assert "SENSITIVE_DATA#" in result.masked_text
        assert "901212-1234567" not in result.masked_text
        assert result.contract.count == 1

    def test_mask_multiple_spans(self):
        masker = Masker()
        text = "주민번호 901212-1234567 전화 010-9876-5432"
        records = [
            {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 5, "end": 19},
            {"category": "MOBILE_PHONE_NUMBER", "span": "010-9876-5432", "start": 23, "end": 36},
        ]
        result = masker.mask(text, records)
        assert result.masked_text.count("SENSITIVE_DATA#") == 2
        assert "901212-1234567" not in result.masked_text
        assert "010-9876-5432" not in result.masked_text

    @patch("masker.masker.secrets.token_hex", side_effect=["deadbeef", "cafebabe"])
    def test_placeholders_are_unlinkable_across_operations(self, _mock_token):
        masker = Masker()
        text = "Call 010-1234-5678"
        records = [
            {
                "category": "PERSONAL_IDENTIFIER_NUMBER",
                "span": "010-1234-5678",
                "start": 5,
                "end": 18,
            },
        ]

        first = masker.mask(text, records)
        second = masker.mask(text, records)

        assert "SENSITIVE_DATA#deadbeef" in first.masked_text
        assert "SENSITIVE_DATA#cafebabe" in second.masked_text

    @patch("masker.masker.secrets.token_hex", return_value="deadbeef")
    def test_prompt_derived_category_never_leaves_masker(self, _mock_token):
        result = Masker().mask(
            "Project Aurora must remain confidential.",
            [
                {
                    "category": "PROJECT_AURORA_SECRET",
                    "span": "Aurora",
                    "start": 8,
                    "end": 14,
                },
            ],
        )

        assert result.masked_text == "Project SENSITIVE_DATA#deadbeef must remain confidential."
        assert "AURORA" not in result.masked_text

    @patch("masker.masker.secrets.token_hex", return_value="01234567")
    def test_arbitrary_dynamic_category_is_opaque(self, _mock_token):
        result = Masker().mask(
            "Keep Apollo private.",
            [
                {
                    "category": "ACQUISITION_TARGET_APOLLO",
                    "span": "Apollo",
                    "start": 5,
                    "end": 11,
                },
            ],
        )

        assert result.masked_text == "Keep SENSITIVE_DATA#01234567 private."
        assert "ACQUISITION" not in result.masked_text

    def test_mask_span_not_found_skips(self):
        masker = Masker()
        result = masker.mask("hello world", [{"category": "TEST", "span": "nonexistent", "start": 0, "end": 11}])
        assert result.masked_text == "hello world"  # span not found → skipped
        assert result.contract.count == 0

    def test_hydrate_restores(self):
        masker = Masker()
        contract = MaskingContract(
            placeholder_map={"[RRN#1]": "901212-1234567", "[PHONE#1]": "010-1234-5678"},
            count=2,
        )
        result = masker.hydrate("번호 [RRN#1]과 [PHONE#1]입니다.", contract)
        assert result.hydrated_text == "번호 901212-1234567과 010-1234-5678입니다."
        assert result.placeholders_restored == 2

    def test_hydrate_unresolved_fails(self):
        masker = Masker()
        contract = MaskingContract(placeholder_map={"[RRN#1]": "901212-1234567"}, count=1)
        with pytest.raises(HydrationError):
            masker.hydrate("번호 [RRN#1]과 [UNKNOWN#1]입니다.", contract)

    def test_full_roundtrip(self):
        masker = Masker()
        original = "주민번호 901212-1234567 전화 010-9876-5432"
        records = [
            {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 5, "end": 19},
            {"category": "MOBILE_PHONE_NUMBER", "span": "010-9876-5432", "start": 23, "end": 36},
        ]
        result = masker.mask(original, records)
        llm_response = f"처리 완료: {result.masked_text}"
        hydrated = masker.hydrate(llm_response, result.contract)
        assert "901212-1234567" in hydrated.hydrated_text
        assert "SENSITIVE_DATA#" not in hydrated.hydrated_text

    def test_selective_mask(self):
        masker = Masker()
        text = "주민번호 901212-1234567 전화 010-9876-5432"
        records = [
            {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 5, "end": 19},
            {"category": "MOBILE_PHONE_NUMBER", "span": "010-9876-5432", "start": 23, "end": 36},
        ]
        # Only mask the first record (index 0)
        result = masker.selective_mask(text, records, [0])
        assert "SENSITIVE_DATA#" in result.masked_text
        assert "010-9876-5432" in result.masked_text  # second record NOT masked
        assert result.contract.count == 1

    def test_selective_mask_empty_indices(self):
        masker = Masker()
        text = "hello world"
        records = [{"category": "TEST", "span": "world", "start": 6, "end": 11}]
        result = masker.selective_mask(text, records, [])
        assert result.masked_text == "hello world"
        assert result.contract.count == 0

    def test_hydrate_no_placeholders(self):
        masker = Masker()
        contract = MaskingContract(placeholder_map={}, count=0)
        result = masker.hydrate("plain text", contract)
        assert result.hydrated_text == "plain text"
        assert result.placeholders_restored == 0

    def test_hydration_error_contains_unresolved(self):
        masker = Masker()
        contract = MaskingContract(placeholder_map={}, count=0)
        with pytest.raises(HydrationError) as exc_info:
            masker.hydrate("[UNKNOWN#1]", contract)
        assert "[UNKNOWN#1]" in exc_info.value.unresolved
