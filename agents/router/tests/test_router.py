"""Tests for the Router — policy resolution, execution, and full pipeline.

Router.resolve() and Router.execute() tests are self-contained (no external deps).
PrivacyRouter.process() tests require valid OPENROUTER_API_KEY.
"""

from __future__ import annotations

import pytest
from agents.router import PrivacyRouter
from agents.router.schemas import ChatMessage, ChatRequest, PipelineResult, RouteResult
from agents.extractor.schemas import Sensitivity
from agents.judge.schemas import Judgment, MeaningfulnessAssessment
from agents.router.router import Router


# ── Router.resolve() ─────────────────────────────────────────────────────────


class TestRouterResolve:
    """Verify Router.resolve() maps each policy action correctly."""

    def test_route_to_external(self):
        router = Router()
        result = router.resolve("route_to_external")
        assert result.endpoint == "external_api"
        assert result.requires_masking is False

    def test_route_to_local(self):
        router = Router()
        result = router.resolve("route_to_local")
        assert result.endpoint == "local_api"
        assert result.requires_masking is False

    def test_mask_and_send(self):
        router = Router()
        result = router.resolve("mask_and_send")
        assert result.endpoint == "external_api"
        assert result.requires_masking is True

    def test_selective_mask(self):
        router = Router()
        result = router.resolve("selective_mask")
        assert result.endpoint == "external_api"
        assert result.requires_masking is True

    def test_prompt_user(self):
        router = Router()
        result = router.resolve("prompt_user")
        assert result.endpoint == "prompt"
        assert result.requires_masking is False

    def test_block(self):
        router = Router()
        result = router.resolve("block")
        assert result.endpoint == "blocked"
        assert result.requires_masking is False

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


# ── Router.execute() ─────────────────────────────────────────────────────────


class TestRouterExecute:
    """Verify Router.execute() with mock callables — no LLM calls."""

    def test_execute_allow_passes_text_to_external(self):
        router = Router()
        calls = []
        def mock_external(text):
            calls.append(text)
            return f"response: {text}"
        result = router.execute("hello world", "route_to_external", [], call_external=mock_external)
        assert result == "response: hello world"
        assert calls == ["hello world"]

    def test_execute_mask_and_send_masks_then_hydrates(self):
        router = Router()
        records = [
            {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "start": 5, "end": 19},
        ]
        def mock_external(masked_text):
            # The text should have placeholder, not original
            assert "901212-1234567" not in masked_text
            assert "RESIDENT_REGISTRATION_NUMBER#" in masked_text
            return f"processed: {masked_text}"
        result = router.execute(
            "주민번호 901212-1234567 확인", "mask_and_send", records, call_external=mock_external
        )
        # Result should be hydrated (original value restored)
        assert "901212-1234567" in result
        assert "RESIDENT_REGISTRATION_NUMBER#" not in result

    def test_execute_route_to_local(self):
        router = Router()
        def mock_local(text):
            return f"local: {text}"
        result = router.execute("hello", "route_to_local", [], call_local=mock_local)
        assert result == "local: hello"

    def test_execute_blocked_returns_blocked_message(self):
        router = Router()
        result = router.execute("sensitive", "block", [])
        assert "[BLOCKED]" in result

    def test_execute_external_missing_callable_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="call_external is required"):
            router.execute("hello", "route_to_external", [], call_external=None)

    def test_execute_local_missing_callable_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="call_local is required"):
            router.execute("hello", "route_to_local", [], call_local=None)

    def test_execute_unknown_action_raises(self):
        router = Router()
        with pytest.raises(ValueError, match="Unknown policy_action"):
            router.execute("hello", "nonexistent", [])

    def test_execute_mask_and_send_no_records_passthrough(self):
        """mask_and_send with no records: masking is a no-op, text passes through."""
        router = Router()
        def mock_external(text):
            return f"echo: {text}"
        result = router.execute("hello", "mask_and_send", [], call_external=mock_external)
        assert result == "echo: hello"

    def test_execute_prompt_user_raises_value_error(self):
        """prompt_user raises ValueError with confirmation instructions."""
        router = Router()
        with pytest.raises(ValueError, match="확인이 필요합니다"):
            router.execute("help me", "prompt_user", [])


# ── PrivacyRouter (full pipeline — requires API key) ─────────────────────────


class TestRouterPolicyActions:
    """Verify each routing path with real SLM."""

    def test_allow_when_not_sensitive(self):
        pr = PrivacyRouter()
        result = pr.process("오늘 서울 날씨는 맑고 기온은 25도입니다")

        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is False
        assert result.judgment.policy_action == "route_to_external"
        assert result.mask_indices == []

    def test_mask_and_send_when_no_essential(self):
        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 포함한 이메일을 작성해줘")

        assert result.route.endpoint == "external_api"
        assert result.route.requires_masking is True
        assert result.judgment.policy_action == "mask_and_send"
        assert len(result.mask_indices) == len(result.records)
        assert result.judgment.meaningful_after_masking.is_meaningful_after_masking is True

    def test_essential_routes_to_local_or_prompt(self):
        """Load-bearing records route to local."""
        from unittest.mock import patch
        from agents.extractor.schemas import ExtractionResult, Sensitivity, ExtractionRecord

        mock_result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="주민등록번호"),
            records=[ExtractionRecord(
                category="RRN", span="901212-1234567",
                confidence=0.99, start=0, end=15, is_essential=True,
            )],
        )
        with patch('agents.extractor.Extractor') as MockExt:
            MockExt.return_value.extract.return_value = mock_result
            pr = PrivacyRouter()
            result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert result.judgment.policy_action == "route_to_local"
        assert result.route.endpoint == "local_api"
        assert result.mask_indices == []
        assert result.judgment.meaningful_after_masking.is_meaningful_after_masking is False

    def test_mixed_records_with_essential(self):
        from unittest.mock import patch
        from agents.extractor.schemas import ExtractionResult, Sensitivity, ExtractionRecord

        mock_result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="혼합"),
            records=[
                ExtractionRecord(
                    category="UNPUBLISHED_RESEARCH_CONCEPT", span="강화학습 알고리즘",
                    confidence=0.9, start=0, end=10, is_essential=True,
                ),
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567",
                    confidence=0.99, start=20, end=35, is_essential=False,
                ),
            ],
        )
        with patch('agents.extractor.Extractor') as MockExt:
            MockExt.return_value.extract.return_value = mock_result
            pr = PrivacyRouter()
            result = pr.process("새로운 강화학습 알고리즘 아이디어를 조언해주세요. 주민등록번호 901212-1234567.")

        assert result.judgment.policy_action == "route_to_local"
        assert result.route.endpoint == "local_api"

class TestRouterPipelineResult:
    """Verify PipelineResult structure."""

    def test_result_has_all_fields(self):
        pr = PrivacyRouter()
        result = pr.process("테스트")

        assert hasattr(result, "sensitivity")
        assert hasattr(result, "judgment")
        assert hasattr(result, "route")
        assert hasattr(result, "records")
        assert hasattr(result, "mask_indices")

    def test_rationale_contains_essential_info(self):
        from unittest.mock import patch
        from agents.extractor.schemas import ExtractionResult, Sensitivity, ExtractionRecord

        mock_result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="주민등록번호"),
            records=[ExtractionRecord(
                category="RRN", span="901212-1234567",
                confidence=0.99, start=0, end=15, is_essential=True,
            )],
        )
        with patch('agents.extractor.Extractor') as MockExt:
            MockExt.return_value.extract.return_value = mock_result
            pr = PrivacyRouter()
            result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert "essential" in result.judgment.rationale

    def test_records_have_schema_fields(self):
        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        for r in result.records:
            assert hasattr(r, "category")
            assert hasattr(r, "span")
            assert hasattr(r, "confidence")
            assert hasattr(r, "is_essential")
            assert hasattr(r, "reasoning")

# ── Mocked PrivacyRouter tests ───────────────────────────────────────────────


class TestPrivacyRouterInitConfigException:
    """PrivacyRouter.__init__ config exception handler (lines 218-220)."""

    def test_config_exception_falls_back_to_defaults(self, monkeypatch):
        """When config.load_config raises, __init__ catches and continues with defaults."""
        import config as config_mod
        from unittest.mock import MagicMock

        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("bad config")))

        pr = PrivacyRouter()
        assert pr._extractor_model is None
        assert pr._judge_model is None

    def test_config_exception_preserves_explicit_models(self, monkeypatch):
        """Explicit model args survive config failure."""
        import config as config_mod
        from unittest.mock import MagicMock

        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("bad config")))

        pr = PrivacyRouter(extractor_model="my-model", api_base="http://localhost:8000")
        assert pr._extractor_model == "my-model"
        assert pr._api_base == "http://localhost:8000"

    def test_resolve_model_exception_also_caught(self, monkeypatch):
        """Exception from resolve_model is also caught."""
        import config as config_mod
        from unittest.mock import MagicMock

        mock_cfg = MagicMock()
        mock_cfg.extractor.model = "some-model"
        monkeypatch.setattr(config_mod, "load_config", MagicMock(return_value=mock_cfg))
        monkeypatch.setattr(config_mod, "resolve_model", MagicMock(side_effect=Exception("resolve failed")))

        pr = PrivacyRouter()
        assert pr._extractor_model == "some-model"


class TestPrivacyRouterPromptUserNoLocalModel:
    """prompt_user path when essential + no local model (lines 263-265)."""

    def _mock_extractor(self, monkeypatch, records):
        """Patch Extractor to return given records with is_sensitive=True."""
        from agents.extractor.schemas import ExtractionResult, Sensitivity
        from unittest.mock import MagicMock

        result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="sensitive data"),
            records=records,
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = result
        monkeypatch.setattr("agents.extractor.Extractor", mock_cls)

    def test_essential_returns_route_to_local(self, monkeypatch):
        """Load-bearing records → route_to_local (Judge rule-based)."""
        from agents.extractor.schemas import ExtractionRecord

        self._mock_extractor(monkeypatch, [
            ExtractionRecord(
                category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567",
                confidence=0.98, start=0, end=14, is_essential=True,
            ),
        ])

        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert result.judgment.policy_action == "route_to_local"
        assert result.route.endpoint == "local_api"
        assert result.mask_indices == []

    def test_prompt_user_only_via_explicit_action(self):
        """prompt_user is only reachable via explicit Router.resolve()."""
        router = Router()
        result = router.resolve("prompt_user")
        assert result.endpoint == "prompt"

    def test_route_to_local_when_local_model_available(self, monkeypatch):
        """Load-bearing + cfg.local.model is set → route_to_local."""
        import config as config_mod
        from agents.extractor.schemas import ExtractionRecord
        from unittest.mock import MagicMock

        self._mock_extractor(monkeypatch, [
            ExtractionRecord(
                category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567",
                confidence=0.98, start=0, end=14, is_essential=True,
            ),
        ])
        mock_cfg = MagicMock()
        mock_cfg.local.model = "local-llm"
        monkeypatch.setattr(config_mod, "load_config", MagicMock(return_value=mock_cfg))

        pr = PrivacyRouter()
        result = pr.process("주민등록번호 901212-1234567을 확인해주세요")

        assert result.judgment.policy_action == "route_to_local"
        assert result.route.endpoint == "local_api"

    def test_not_sensitive_routes_to_external(self, monkeypatch):
        """Non-sensitive → route_to_external."""
        from agents.extractor.schemas import ExtractionResult, Sensitivity
        from unittest.mock import MagicMock

        result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="clean text"),
            records=[],
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = result
        monkeypatch.setattr("agents.extractor.Extractor", mock_cls)

        pr = PrivacyRouter()
        pipeline = pr.process("오늘 서울 날씨는 맑음")

        assert pipeline.judgment.policy_action == "route_to_external"
        assert pipeline.route.endpoint == "external_api"
        assert pipeline.mask_indices == []

    def test_sensitive_no_essential_masks(self, monkeypatch):
        """Sensitive but not essential → mask_and_send."""
        from agents.extractor.schemas import ExtractionResult, ExtractionRecord, Sensitivity
        from unittest.mock import MagicMock

        result = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=True, rationale="PII found"),
            records=[
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567",
                    confidence=0.98, start=5, end=19, is_essential=False,
                ),
            ],
        )
        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = result
        monkeypatch.setattr("agents.extractor.Extractor", mock_cls)

        pr = PrivacyRouter()
        pipeline = pr.process("주민번호 901212-1234567을 포함한 이메일을 작성해줘")

        assert pipeline.judgment.policy_action == "mask_and_send"
        assert pipeline.route.requires_masking is True
        assert len(pipeline.mask_indices) == len(pipeline.records)


class TestPrivacyRouterChat:
    """chat() method tests (lines 326-345)."""

    def _make_chat_result(self, endpoint, requires_masking, description, policy_action):
        """Helper to build a minimal PipelineResult for chat testing."""
        from agents.extractor.schemas import Sensitivity
        from agents.judge import Judgment, MeaningfulnessAssessment

        return PipelineResult(
            sensitivity=Sensitivity(is_sensitive=(policy_action != "route_to_external"), rationale="test"),
            judgment=Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=(policy_action not in ("route_to_local", "prompt_user")),
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
        import config as config_mod
        from unittest.mock import MagicMock
        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        pipeline_result = self._make_chat_result("external_api", False, "민감 정보 없음", "route_to_external")
        monkeypatch.setattr(pr, "process", lambda text: pipeline_result)

        req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="hello")])
        resp = pr.chat(req)

        assert resp.model == "privacy-router"
        assert "[EXTERNAL]" in resp.choices[0].message.content
        assert resp.id.startswith("chatcmpl-")

    def test_chat_sensitive_returns_masked(self, monkeypatch):
        """Sensitive input → [MASKED] response."""
        import config as config_mod
        from unittest.mock import MagicMock
        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        pipeline_result = self._make_chat_result("external_api", True, "마스킹 후 전송", "mask_and_send")
        monkeypatch.setattr(pr, "process", lambda text: pipeline_result)

        req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="주민등록번호 확인")])
        resp = pr.chat(req)

        assert "[MASKED]" in resp.choices[0].message.content
        assert resp.route_result is not None
        assert resp.route_result.requires_masking is True

    def test_chat_local_returns_local(self, monkeypatch):
        """Local route → [LOCAL] response."""
        import config as config_mod
        from unittest.mock import MagicMock
        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        pipeline_result = self._make_chat_result("local_api", False, "로컬 LLM으로 처리", "route_to_local")
        monkeypatch.setattr(pr, "process", lambda text: pipeline_result)

        req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="주민등록번호 확인")])
        resp = pr.chat(req)

        assert "[LOCAL]" in resp.choices[0].message.content

    def test_chat_multiple_messages(self, monkeypatch):
        """Multiple user messages are concatenated."""
        import config as config_mod
        from unittest.mock import MagicMock
        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        pr = PrivacyRouter()
        captured = []
        pipeline_result = self._make_chat_result("external_api", False, "외부 전송", "route_to_external")

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
        from agents.router import router as router_module
        from agents.extractor.schemas import ExtractionResult, Sensitivity
        from unittest.mock import MagicMock
        import config as config_mod

        monkeypatch.setattr(router_module, "_DEFAULT_ROUTER", None)
        monkeypatch.setattr(config_mod, "load_config", MagicMock(side_effect=Exception("no config")))

        mock_cls = MagicMock()
        mock_cls.return_value.extract.return_value = ExtractionResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="clean"),
            records=[],
        )
        monkeypatch.setattr("agents.extractor.Extractor", mock_cls)

        result = router_module.process("hello")

        assert isinstance(result, PipelineResult)
        assert result.route.endpoint == "external_api"
        assert router_module._DEFAULT_ROUTER is not None

    def test_process_reuses_existing_router(self, monkeypatch):
        """process() reuses the existing global router on subsequent calls."""
        from agents.router import router as router_module
        from unittest.mock import MagicMock

        mock_router = MagicMock()
        mock_router.process.return_value = PipelineResult(
            sensitivity=Sensitivity(is_sensitive=False, rationale="none"),
            judgment=Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=True, rationale="none",
                ),
                policy_action="route_to_external",
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
