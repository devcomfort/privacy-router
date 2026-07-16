"""Unit tests for POST /api/v1/guardrail — LiteLLM Generic Guardrail API.

Tests the guardrail endpoint with mocked PrivacyRouter pipeline to verify
decision logic (NONE / BLOCKED / GUARDRAIL_INTERVENED) without real LLM calls.

Test inputs sourced from docs/ground_truth.json where applicable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from server.api import app, require_auth

# ── Auth override ────────────────────────────────────────────────────────────


async def _mock_auth() -> str:
    return "test-provider"


app.dependency_overrides[require_auth] = _mock_auth
client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_pipeline(
    policy_action: str = "allow",
    requires_masking: bool = False,
    is_sensitive: bool = False,
    records: list | None = None,
):
    """Build a PipelineResult with correct schema fields."""
    from agents.extractor.schemas import Sensitivity
    from agents.judge.schemas import Judgment, MeaningfulnessAssessment
    from agents.router.schemas import PipelineResult, RouteResult

    endpoint = "local_api" if policy_action == "block" else "external_api"
    route = RouteResult(
        endpoint=endpoint,
        requires_masking=requires_masking,
        description="mock",
    )
    meaningful = MeaningfulnessAssessment(
        is_meaningful_after_masking=policy_action != "block",
        rationale="mock",
    )
    judgment = Judgment(
        meaningful_after_masking=meaningful,
        policy_action=policy_action,
        strategy="mock",
        rationale="mock",
    )
    sensitivity = Sensitivity(
        is_sensitive=is_sensitive,
        rationale="mock",
    )
    return PipelineResult(
        sensitivity=sensitivity,
        records=records or [],
        route=route,
        judgment=judgment,
    )


def _make_record(
    category: str = "PERSONAL_IDENTIFIER_NUMBER",
    span: str = "901212-1234567",
    is_essential: bool = False,
):
    """Build an ExtractionRecord with correct schema fields."""
    from agents.extractor.schemas import ExtractionRecord

    return ExtractionRecord(
        category=category,
        span=span,
        confidence=0.95,
        start=0,
        end=len(span),
        is_essential=is_essential,
        detection_type="pattern",
        reasoning="mock",
    )


# ── Error cases ──────────────────────────────────────────────────────────────


class TestGuardrailErrors:
    """Malformed or invalid requests."""

    def test_empty_body_returns_none(self):
        """Empty JSON body → texts defaults to [] → decision=NONE."""
        resp = client.post("/api/v1/guardrail", json={})
        assert resp.status_code == 200
        assert resp.json() == {"decision": "NONE"}

    def test_malformed_json_returns_400(self):
        """Invalid JSON body → 400 Bad Request."""
        resp = client.post(
            "/api/v1/guardrail",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_missing_texts_field_returns_none(self):
        """Request without 'texts' field → texts defaults to [] → decision=NONE."""
        resp = client.post(
            "/api/v1/guardrail",
            json={"input_type": "request"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"decision": "NONE"}

    def test_invalid_input_type_returns_none(self):
        """Unknown input_type is treated as 'request' (not 'response')."""
        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.return_value = _make_pipeline()
            MockRouter.return_value = mock_instance

            resp = client.post(
                "/api/v1/guardrail",
                json={"texts": ["hello"], "input_type": "unknown_type"},
            )
            assert resp.status_code == 200
            assert resp.json()["decision"] == "NONE"


# ── Early-exit paths ─────────────────────────────────────────────────────────


class TestGuardrailPassthrough:
    """Response-type requests and empty texts should pass through."""

    def test_response_input_type_returns_none(self):
        """input_type='response' → decision=NONE (responses are not checked)."""
        resp = client.post(
            "/api/v1/guardrail",
            json={"texts": ["some response text"], "input_type": "response"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"decision": "NONE"}

    def test_empty_texts_returns_none(self):
        """Empty texts array → decision=NONE."""
        resp = client.post(
            "/api/v1/guardrail",
            json={"texts": [], "input_type": "request"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"decision": "NONE"}

    def test_missing_input_type_defaults_to_request(self):
        """Missing input_type defaults to 'request' (triggers pipeline)."""
        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.return_value = _make_pipeline()
            MockRouter.return_value = mock_instance

            resp = client.post("/api/v1/guardrail", json={"texts": ["hello"]})
            assert resp.status_code == 200
            assert resp.json()["decision"] == "NONE"


# ── Non-sensitive (ground_truth: allow cases) ────────────────────────────────


class TestGuardrailNonSensitive:
    """Non-sensitive text → decision=NONE. Cases from ground_truth.json."""

    def test_general_knowledge(self):
        """ground_truth: '일반지식' — Python list sorting."""
        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.return_value = _make_pipeline(
                policy_action="allow",
                requires_masking=False,
                is_sensitive=False,
            )
            MockRouter.return_value = mock_instance

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["Python에서 리스트를 정렬하는 방법을 알려줘."],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"decision": "NONE"}
            mock_instance.process.assert_called_once()

    def test_weather_query(self):
        """ground_truth: '일반날씨' — no sensitive data."""
        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.return_value = _make_pipeline(
                policy_action="allow",
                is_sensitive=False,
            )
            MockRouter.return_value = mock_instance

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["오늘 서울 날씨는 맑고 기온은 25도입니다."],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"decision": "NONE"}


# ── Masking (ground_truth: selective_mask cases) ─────────────────────────────


class TestGuardrailMasking:
    """Sensitive-but-maskable → GUARDRAIL_INTERVENED."""

    def test_pii_maskable_email_task(self):
        """ground_truth: pii_rrn_mask — RRN is background, email task survives."""
        record = _make_record(
            category="PERSONAL_IDENTIFIER_NUMBER",
            span="901212-1234567",
            is_essential=False,
        )
        with (
            patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter,
            patch("server.api.routes.guardrail.Masker") as MockMasker,
        ):
            mock_router = MagicMock()
            mock_router.process.return_value = _make_pipeline(
                policy_action="selective_mask",
                requires_masking=True,
                is_sensitive=True,
                records=[record],
            )
            MockRouter.return_value = mock_router

            mock_masker = MagicMock()
            mock_mask_result = MagicMock()
            mock_mask_result.masked_text = "PERSONAL_IDENTIFIER_NUMBER#a1b2c3d4을 포함한 이메일을 작성해줘."
            mock_masker.mask.return_value = mock_mask_result
            MockMasker.return_value = mock_masker

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["decision"] == "GUARDRAIL_INTERVENED"
            assert len(data["modified_texts"]) == 1
            assert "PERSONAL_IDENTIFIER_NUMBER#a1b2c3d4" in data["modified_texts"][0]

    def test_phone_number_maskable(self):
        """Phone number in contact email task — maskable."""
        record = _make_record(category="PHONE_NUMBER", span="010-1234-5678")
        with (
            patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter,
            patch("server.api.routes.guardrail.Masker") as MockMasker,
        ):
            mock_router = MagicMock()
            mock_router.process.return_value = _make_pipeline(
                policy_action="selective_mask",
                requires_masking=True,
                is_sensitive=True,
                records=[record],
            )
            MockRouter.return_value = mock_router

            mock_masker = MagicMock()
            mock_mask_result = MagicMock()
            mock_mask_result.masked_text = "PHONE_NUMBER#x1y2z3w4로 연락해줘."
            mock_masker.mask.return_value = mock_mask_result
            MockMasker.return_value = mock_masker

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["010-1234-5678로 연락해줘."],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["decision"] == "GUARDRAIL_INTERVENED"

    def test_multiple_texts_partial_mask(self):
        """Mixed sensitive/non-sensitive — one masked, one passed through."""
        record = _make_record(category="PHONE_NUMBER", span="010-1234-5678")

        call_count = 0

        def side_effect(text):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_pipeline(
                    policy_action="selective_mask",
                    requires_masking=True,
                    is_sensitive=True,
                    records=[record],
                )
            return _make_pipeline(
                policy_action="allow",
                requires_masking=False,
                is_sensitive=False,
            )

        with (
            patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter,
            patch("server.api.routes.guardrail.Masker") as MockMasker,
        ):
            mock_router = MagicMock()
            mock_router.process.side_effect = side_effect
            MockRouter.return_value = mock_router

            mock_masker = MagicMock()
            mock_mask_result = MagicMock()
            mock_mask_result.masked_text = "PHONE_NUMBER#x1y2z3w4로 연락해줘."
            mock_masker.mask.return_value = mock_mask_result
            MockMasker.return_value = mock_masker

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": [
                        "010-1234-5678로 연락해줘.",
                        "오늘 날씨 알려줘.",
                    ],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["decision"] == "GUARDRAIL_INTERVENED"
            assert len(data["modified_texts"]) == 2
            assert "PHONE_NUMBER" in data["modified_texts"][0]
            assert data["modified_texts"][1] == "오늘 날씨 알려줘."


# ── Blocking (ground_truth: block cases) ─────────────────────────────────────


class TestGuardrailBlocking:
    """Essential-sensitive text → BLOCKED."""

    def test_rrn_direct_query(self):
        """ground_truth: pii_rrn_query — RRN is the subject, masking loses meaning."""
        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.return_value = _make_pipeline(
                policy_action="block",
                requires_masking=False,
                is_sensitive=True,
            )
            MockRouter.return_value = mock_instance

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["주민등록번호 901212-1234567을 기재해줘."],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"decision": "BLOCKED"}

    def test_block_on_first_text_stops_processing(self):
        """First text blocked → second text never processed."""
        call_count = 0

        def side_effect(text):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_pipeline(
                    policy_action="block",
                    is_sensitive=True,
                )
            raise AssertionError("Second text should not be processed")

        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.side_effect = side_effect
            MockRouter.return_value = mock_instance

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": [
                        "주민등록번호로 인증해줘.",
                        "이것은 처리되면 안 됨.",
                    ],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"decision": "BLOCKED"}
            assert call_count == 1

    def test_business_secret_essential(self):
        """ground_truth: 전략근거 — business decision is essential context."""
        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.return_value = _make_pipeline(
                policy_action="block",
                is_sensitive=True,
            )
            MockRouter.return_value = mock_instance

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["삼성 파운드리를 선택하기로 결정했어. 단가가 15% 저렴해서야."],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"decision": "BLOCKED"}


# ── Pipeline integration ─────────────────────────────────────────────────────


class TestGuardrailPipelineIntegration:
    """Verify the endpoint exercises the full pipeline correctly."""

    def test_privacy_router_called_per_text(self):
        """Each text in the array triggers a separate pipeline call."""
        call_args = []

        def side_effect(text):
            call_args.append(text)
            return _make_pipeline()

        with patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter:
            mock_instance = MagicMock()
            mock_instance.process.side_effect = side_effect
            MockRouter.return_value = mock_instance

            client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["첫 번째", "두 번째", "세 번째"],
                    "input_type": "request",
                },
            )
            assert call_args == ["첫 번째", "두 번째", "세 번째"]

    def test_masker_called_only_when_masking_required(self):
        """Masker.mask() is called only for texts that require masking."""
        call_count = 0

        def router_side_effect(text):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_pipeline(
                    policy_action="selective_mask",
                    requires_masking=True,
                    is_sensitive=True,
                    records=[_make_record()],
                )
            return _make_pipeline(
                policy_action="allow",
                requires_masking=False,
                is_sensitive=False,
            )

        with (
            patch("server.api.routes.guardrail.PrivacyRouter") as MockRouter,
            patch("server.api.routes.guardrail.Masker") as MockMasker,
        ):
            mock_router = MagicMock()
            mock_router.process.side_effect = router_side_effect
            MockRouter.return_value = mock_router

            mock_masker = MagicMock()
            mock_mask_result = MagicMock()
            mock_mask_result.masked_text = "masked"
            mock_masker.mask.return_value = mock_mask_result
            MockMasker.return_value = mock_masker

            resp = client.post(
                "/api/v1/guardrail",
                json={
                    "texts": ["민감한 텍스트", "일반 텍스트"],
                    "input_type": "request",
                },
            )
            assert resp.status_code == 200
            # Masker called once (only for the sensitive text)
            mock_masker.mask.assert_called_once()
