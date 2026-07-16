"""Tests for the Router — policy resolution, execution, and full pipeline.

Router.resolve() and Router.execute() tests are self-contained (no external deps).
PrivacyRouter.process() tests require valid OPENROUTER_API_KEY.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents import ExtractionRecord, ExtractionResult, Sensitivity
from agents.judge import Judgment, MeaningfulnessAssessment
from agents.router import (
    ChatMessage,
    ChatRequest,
    MiddleManAgent,
    PipelineResult,
    PrivacyRouter,
    Router,
    RouteResult,
    RoutingStrategy,
    UserAction,
    UserDecision,
)

# ── Router.resolve() ─────────────────────────────────────────────────────────


class TestRouterResolve:
    """Verify Router.resolve() maps each policy action correctly."""

    def test_allow(self):
        router = Router()
        result = router.resolve("allow")
        assert result.endpoint == "external_api"
        assert result.requires_masking is False

    def test_block(self):
        router = Router()
        result = router.resolve("block")
        assert result.endpoint == "local_api"
        assert result.requires_masking is False

    def test_selective_mask(self):
        router = Router()
        result = router.resolve("selective_mask")
        assert result.endpoint == "external_api"
        assert result.requires_masking is True

    def test_unknown_action_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="Unknown policy_action"):
            router.resolve("nonexistent")

    def test_all_actions_return_route_result(self):
        router = Router()
        for action in Router._ACTIONS:
            result = router.resolve(action)
            assert isinstance(result, RouteResult)
            assert result.endpoint
            assert isinstance(result.requires_masking, bool)
            assert result.description


# ── MiddleManAgent policy invariants ─────────────────────────────────────────


class TestMiddleManPolicyInvariants:
    def test_records_override_not_sensitive_flag(self):
        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="inconsistent"),
            records=[
                ExtractionRecord(
                    category="PERSON_NAME",
                    span="Alice",
                    confidence=0.99,
                    start=0,
                    end=5,
                )
            ],
        )

        records, action = MiddleManAgent().apply_decision(
            extraction,
            UserDecision(
                action=UserAction.ACCEPT,
                strategy=RoutingStrategy.AUTO,
            ),
        )

        assert extraction.sensitivity.is_sensitive is True
        assert len(records) == 1
        assert action == "selective_mask"

    def test_sensitive_without_records_blocks(self):
        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="unextractable"),
            records=[],
        )

        middle_man = MiddleManAgent()
        summary = middle_man.summarize(extraction)
        result = middle_man.process_with_decision(extraction)

        assert summary.default_action.startswith("block")
        assert result.judgment.policy_action == "block"
        assert result.route.endpoint == "local_api"

    def test_mask_all_without_records_blocks(self):
        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="unextractable"),
            records=[],
        )

        _, action = MiddleManAgent().apply_decision(
            extraction,
            UserDecision(
                action=UserAction.STRATEGY,
                strategy=RoutingStrategy.MASK_ALL,
            ),
        )

        assert action == "block"


# ── Router.execute() ─────────────────────────────────────────────────────────


class TestRouterExecute:
    """Verify Router.execute() with mock callables — no LLM calls."""

    def test_execute_allow_passes_text_to_external(self):
        router = Router()
        calls = []

        def mock_external(text):
            calls.append(text)
            return f"response: {text}"

        result = router.execute("hello world", "allow", [], call_external=mock_external)
        assert result == "response: hello world"
        assert calls == ["hello world"]

    def test_execute_selective_mask_masks_then_hydrates(self):
        router = Router()
        records = [
            {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 5, "end": 19},
        ]

        def mock_external(masked_text):
            # The text should have placeholder, not original
            assert "901212-1234567" not in masked_text
            assert "SENSITIVE_DATA#" in masked_text
            return f"processed: {masked_text}"

        result = router.execute("주민번호 901212-1234567 확인", "selective_mask", records, call_external=mock_external)
        # Result should be hydrated (original value restored)
        assert "901212-1234567" in result
        assert "SENSITIVE_DATA#" not in result

    def test_execute_block(self):
        router = Router()

        def mock_local(text):
            return f"local: {text}"

        result = router.execute("hello", "block", [], call_local=mock_local)
        assert result == "local: hello"

    def test_execute_external_missing_callable_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="call_external is required"):
            router.execute("hello", "allow", [], call_external=None)

    def test_execute_local_missing_callable_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="call_local is required"):
            router.execute("hello", "block", [], call_local=None)

    def test_execute_unknown_action_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="Unknown policy_action"):
            router.execute("hello", "nonexistent", [])

    def test_execute_selective_mask_no_records_passthrough(self):
        """selective_mask with no records: masking is a no-op, text passes through."""
        router = Router()

        def mock_external(text):
            return f"echo: {text}"

        result = router.execute("hello", "selective_mask", [], call_external=mock_external)
        assert result == "echo: hello"


# ── PrivacyRouter (full pipeline — requires API key) ─────────────────────────


class TestRouterPolicyActions:
    """Verify each routing path with real SLM."""

    def test_allow_when_not_sensitive(self, monkeypatch):
        from unittest.mock import MagicMock

        from agents.extractor.schemas import ExtractionResult, Sensitivity

        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="clean text"),
            records=[],
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = extraction
        monkeypatch.setattr("agents.router.router.Extractor", mock_cls)

        result = PrivacyRouter().process("오늘 서울 날씨는 맑고 기온은 25도입니다")

        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is False
        assert result.judgment.policy_action == "allow"
        assert result.mask_indices == []

    def test_selective_mask_when_no_essential(self, monkeypatch):
        from unittest.mock import MagicMock

        from agents.extractor.schemas import ExtractionRecord, ExtractionResult, Sensitivity

        extraction = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="PII found"),
            records=[
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="901212-1234567",
                    confidence=0.99,
                    start=5,
                    end=19,
                    is_essential=False,
                )
            ],
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = extraction
        monkeypatch.setattr("agents.router.router.Extractor", mock_cls)

        result = PrivacyRouter().process("주민등록번호 901212-1234567을 포함한 이메일을 작성해줘")

        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is True
        assert result.judgment.policy_action == "selective_mask"
        assert len(result.mask_indices) == len(result.records)
        assert result.judgment.meaningful_after_masking.is_meaningful_after_masking is True

    def test_essential_routes_to_local_or_prompt(self):
        """Load-bearing records route to local."""
        from unittest.mock import patch

        from agents.extractor.schemas import ExtractionRecord, ExtractionResult, Sensitivity

        mock_result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="주민등록번호"),
            records=[
                ExtractionRecord(
                    category="RRN",
                    span="901212-1234567",
                    confidence=0.99,
                    start=0,
                    end=15,
                    is_essential=True,
                )
            ],
        )
        with patch("agents.router.router.Extractor") as MockExt:
            MockExt.return_value.extract.return_value = mock_result
            pr = PrivacyRouter()
            result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert result.judgment.policy_action == "block"
        assert result.route.endpoint == "local_api"
        assert result.mask_indices == []
        assert result.judgment.meaningful_after_masking.is_meaningful_after_masking is False

    def test_mixed_records_with_essential(self):
        from unittest.mock import patch

        from agents.extractor.schemas import ExtractionRecord, ExtractionResult, Sensitivity

        mock_result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="혼합"),
            records=[
                ExtractionRecord(
                    category="UNPUBLISHED_RESEARCH_CONCEPT",
                    span="강화학습 알고리즘",
                    confidence=0.9,
                    start=0,
                    end=10,
                    is_essential=True,
                ),
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="901212-1234567",
                    confidence=0.99,
                    start=20,
                    end=35,
                    is_essential=False,
                ),
            ],
        )
        with patch("agents.router.router.Extractor") as MockExt:
            MockExt.return_value.extract.return_value = mock_result
            pr = PrivacyRouter()
            result = pr.process("새로운 강화학습 알고리즘 아이디어를 조언해주세요. 주민등록번호 901212-1234567.")

        assert result.judgment.policy_action == "block"
        assert result.route.endpoint == "local_api"


class TestRouterPipelineResult:
    """Verify PipelineResult structure."""

    def test_result_has_all_fields(self, monkeypatch):
        extractor = MagicMock()
        extractor.return_value.extract.return_value = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="clean"),
            records=[],
        )
        monkeypatch.setattr("agents.router.router.Extractor", extractor)

        result = PrivacyRouter().process("테스트")

        assert hasattr(result, "sensitivity")
        assert hasattr(result, "judgment")
        assert hasattr(result, "route")
        assert hasattr(result, "records")
        assert hasattr(result, "mask_indices")

    def test_rationale_contains_essential_info(self):
        from unittest.mock import patch

        from agents.extractor.schemas import ExtractionRecord, ExtractionResult, Sensitivity

        mock_result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="주민등록번호"),
            records=[
                ExtractionRecord(
                    category="RRN",
                    span="901212-1234567",
                    confidence=0.99,
                    start=0,
                    end=15,
                    is_essential=True,
                )
            ],
        )
        with patch("agents.router.router.Extractor") as MockExt:
            MockExt.return_value.extract.return_value = mock_result
            pr = PrivacyRouter()
            result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert "essential" in result.judgment.rationale

    def test_records_have_schema_fields(self, monkeypatch):
        extractor = MagicMock()
        extractor.return_value.extract.return_value = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="PII found"),
            records=[
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="901212-1234567",
                    confidence=0.99,
                    start=7,
                    end=21,
                    is_essential=False,
                    reasoning="direct identifier",
                )
            ],
        )
        monkeypatch.setattr("agents.router.router.Extractor", extractor)

        result = PrivacyRouter().process("주민등록번호 901212-1234567을 확인해주세요")

        for r in result.records:
            assert hasattr(r, "category")
            assert hasattr(r, "span")
            assert hasattr(r, "confidence")
            assert hasattr(r, "is_essential")
            assert hasattr(r, "reasoning")


# ── Mocked PrivacyRouter tests ───────────────────────────────────────────────


class TestPrivacyRouterInitConfigFailure:
    """PrivacyRouter initialization fails closed on invalid model configuration."""

    def test_config_exception_is_not_swallowed(self, monkeypatch):
        load_failure = MagicMock(side_effect=ValueError("bad config"))
        monkeypatch.setattr("agents.router.router.load_config", load_failure)

        with pytest.raises(ValueError, match="bad config"):
            PrivacyRouter()

    def test_explicit_model_still_requires_valid_registry(self, monkeypatch):
        load_failure = MagicMock(side_effect=ValueError("bad config"))
        monkeypatch.setattr("agents.router.router.load_config", load_failure)

        with pytest.raises(ValueError, match="bad config"):
            PrivacyRouter(
                decision_model="openai/my-model",
                api_base="http://127.0.0.1:8000/v1",
            )

    def test_endpoint_resolution_exception_is_not_swallowed(self, monkeypatch):
        mock_cfg = MagicMock()
        mock_cfg.decision.model = "openai/some-model"
        mock_cfg.decision.api_base = None
        monkeypatch.setattr("agents.router.router.load_config", MagicMock(return_value=mock_cfg))
        resolve_failure = MagicMock(side_effect=ValueError("unsafe endpoint"))
        monkeypatch.setattr(
            "agents.router.router.resolve_local_api_base",
            resolve_failure,
        )

        with pytest.raises(ValueError, match="unsafe endpoint"):
            PrivacyRouter()

        resolve_failure.assert_called_once_with(mock_cfg, "openai/some-model", None)


class TestPrivacyRouterCanonicalActions:
    """Canonical action paths produced by the deterministic Judge."""

    def _mock_extractor(self, monkeypatch, records):
        """Patch Extractor to return given records with is_sensitive=True."""
        from unittest.mock import MagicMock

        from agents.extractor.schemas import ExtractionResult, Sensitivity

        result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="sensitive data"),
            records=records,
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = result
        monkeypatch.setattr("agents.router.router.Extractor", mock_cls)

    def test_essential_returns_block(self, monkeypatch):
        """Load-bearing records → block (Judge rule-based)."""
        from agents.extractor.schemas import ExtractionRecord

        self._mock_extractor(
            monkeypatch,
            [
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="901212-1234567",
                    confidence=0.98,
                    start=0,
                    end=14,
                    is_essential=True,
                ),
            ],
        )

        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert result.judgment.policy_action == "block"
        assert result.route.endpoint == "local_api"
        assert result.mask_indices == []

    def test_block_when_local_model_available(self, monkeypatch):
        """Load-bearing + cfg.local.model is set → block."""
        from unittest.mock import MagicMock

        import config as config_mod
        from agents.extractor.schemas import ExtractionRecord

        self._mock_extractor(
            monkeypatch,
            [
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="901212-1234567",
                    confidence=0.98,
                    start=0,
                    end=14,
                    is_essential=True,
                ),
            ],
        )
        mock_cfg = MagicMock()
        mock_cfg.local.model = "local-llm"
        monkeypatch.setattr(config_mod, "load_config", MagicMock(return_value=mock_cfg))

        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert result.judgment.policy_action == "block"
        assert result.route.endpoint == "local_api"

    def test_not_sensitive_routes_to_external(self, monkeypatch):
        """Non-sensitive → allow."""
        from unittest.mock import MagicMock

        from agents.extractor.schemas import ExtractionResult, Sensitivity

        result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="clean text"),
            records=[],
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = result
        monkeypatch.setattr("agents.router.router.Extractor", mock_cls)

        pr = PrivacyRouter()
        pipeline = pr.process("오늘 서울 날씨는 맑음")

        assert pipeline.judgment.policy_action == "allow"
        assert pipeline.route.endpoint == "external_api"
        assert pipeline.mask_indices == []

    def test_sensitive_no_essential_masks(self, monkeypatch):
        """Sensitive but not essential → selective_mask."""
        from unittest.mock import MagicMock

        from agents.extractor.schemas import ExtractionRecord, ExtractionResult, Sensitivity

        result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="PII found"),
            records=[
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER",
                    span="901212-1234567",
                    confidence=0.98,
                    start=5,
                    end=19,
                    is_essential=False,
                ),
            ],
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = result
        monkeypatch.setattr("agents.router.router.Extractor", mock_cls)

        pr = PrivacyRouter()
        pipeline = pr.process("주민번호 901212-1234567을 포함한 이메일을 작성해줘")

        assert pipeline.judgment.policy_action == "selective_mask"
        assert pipeline.route.requires_masking is True
        assert len(pipeline.mask_indices) == len(pipeline.records)


class TestPrivacyRouterChat:
    """chat() method tests (lines 326-345)."""

    def _make_chat_result(self, endpoint, requires_masking, description, policy_action):
        """Helper to build a minimal PipelineResult for chat testing."""
        from agents.extractor.schemas import Sensitivity
        from agents.judge import Judgment, MeaningfulnessAssessment

        return PipelineResult(
            sensitivity=Sensitivity(is_sensitive=(policy_action != "allow"), rationale="test"),
            judgment=Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=policy_action != "block",
                    rationale="test",
                ),
                policy_action=policy_action,
                strategy=description,
                rationale="test",
            ),
            route=RouteResult(endpoint=endpoint, requires_masking=requires_masking, description=description),
            records=[],
            mask_indices=[0] if requires_masking else [],
        )

    def test_chat_non_sensitive_returns_external(self, monkeypatch):
        """Non-sensitive input → [EXTERNAL] response."""
        from unittest.mock import MagicMock

        import config as config_mod

        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        pipeline_result = self._make_chat_result("external_api", False, "민감 정보 없음", "allow")
        monkeypatch.setattr(pr, "process", lambda text: pipeline_result)

        req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="hello")])
        resp = pr.chat(req)

        assert resp.model == "privacy-router"
        assert "[EXTERNAL]" in resp.choices[0].message.content
        assert resp.id.startswith("chatcmpl-")

    def test_chat_sensitive_returns_masked(self, monkeypatch):
        """Sensitive input → [MASKED] response."""
        from unittest.mock import MagicMock

        import config as config_mod

        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        pipeline_result = self._make_chat_result("external_api", True, "마스킹 후 전송", "selective_mask")
        monkeypatch.setattr(pr, "process", lambda text: pipeline_result)

        req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="주민등록번호 확인")])
        resp = pr.chat(req)

        assert "[MASKED]" in resp.choices[0].message.content
        assert resp.route_result is not None
        assert resp.route_result.requires_masking is True

    def test_chat_local_returns_local(self, monkeypatch):
        """Local route → [LOCAL] response."""
        from unittest.mock import MagicMock

        import config as config_mod

        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        pipeline_result = self._make_chat_result("local_api", False, "로컬 LLM으로 처리", "block")
        monkeypatch.setattr(pr, "process", lambda text: pipeline_result)

        req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="주민등록번호 확인")])
        resp = pr.chat(req)

        assert "[LOCAL]" in resp.choices[0].message.content

    def test_chat_multiple_messages(self, monkeypatch):
        """Multiple user messages are concatenated."""
        from unittest.mock import MagicMock

        import config as config_mod

        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        captured = []
        pipeline_result = self._make_chat_result("external_api", False, "외부 전송", "allow")

        def capture(text):
            captured.append(text)
            return pipeline_result

        monkeypatch.setattr(pr, "process", capture)

        req = ChatRequest(
            model="auto",
            messages=[
                ChatMessage(role="system", content="You are a helper"),
                ChatMessage(role="user", content="first message"),
                ChatMessage(role="assistant", content="ok"),
                ChatMessage(role="user", content="second message"),
            ],
        )
        resp = pr.chat(req)

        assert len(captured) == 1
        assert "first message" in captured[0]
        assert "second message" in captured[0]
        assert resp.model == "privacy-router"


class TestModuleLevelProcess:
    """Module-level process() function (lines 386-389)."""

    def test_process_creates_default_router(self, monkeypatch):
        """process() creates a PrivacyRouter on first call."""
        import config as config_mod
        from agents.router import router as router_module

        monkeypatch.setattr(router_module, "_DEFAULT_ROUTER", None)
        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="clean"),
            records=[],
        )
        monkeypatch.setattr(router_module, "Extractor", mock_cls)

        result = router_module.process("hello")

        assert isinstance(result, PipelineResult)
        assert result.route.endpoint == "external_api"
        assert router_module._DEFAULT_ROUTER is not None

    def test_process_reuses_existing_router(self, monkeypatch):
        """process() reuses the existing global router on subsequent calls."""
        from unittest.mock import MagicMock

        from agents.router import router as router_module

        mock_router = MagicMock()
        mock_router.process.return_value = PipelineResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="none"),
            judgment=Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=True,
                    rationale="none",
                ),
                policy_action="allow",
                strategy="외부 전송",
                rationale="none",
            ),
            route=RouteResult(endpoint="external_api", requires_masking=False, description="mocked"),
            records=[],
            mask_indices=[],
        )
        monkeypatch.setattr(router_module, "_DEFAULT_ROUTER", mock_router)

        result = router_module.process("test input")

        mock_router.process.assert_called_once_with("test input")
        assert result.route.description == "mocked"
