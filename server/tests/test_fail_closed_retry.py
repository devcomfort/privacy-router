"""Regression tests for fail-closed adapter retries at API boundaries."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from agents import (
    ExtractionRecord,
    ExtractionResult,
    MaskingContract,
    PrivacyAnalysisUnavailable,
    RouteResult,
    Sensitivity,
    decrypt_field,
)
from agents.router import SQLiteKVCache
from db import ExtractionCache, get_session, init_db
from db import Response as StoredResponse
from server.adapters import LiteLLMAdapter
from server.api import app, require_auth
from server.mcp.tools import (
    apply_decision as mcp_apply_decision,
)
from server.mcp.tools import (
    process as mcp_process,
)
from server.mcp.tools import (
    review as mcp_review,
)


async def _mock_auth() -> str:
    return "test-provider"


app.dependency_overrides[require_auth] = _mock_auth
client = TestClient(app)


def _pipeline(endpoint: str, requires_masking: bool = False, records: list | None = None):
    return SimpleNamespace(
        route=RouteResult(
            endpoint=endpoint,
            requires_masking=requires_masking,
            description="test route",
        ),
        sensitivity=SimpleNamespace(is_sensitive=requires_masking),
        judgment=SimpleNamespace(
            policy_action="block" if endpoint == "local_api" else "allow",
            strategy="auto",
            rationale="test rationale",
        ),
        records=records or [],
    )


def _extraction_record(span: str, category: str = "TEST_SECRET") -> ExtractionRecord:
    return ExtractionRecord(
        category=category,
        span=span,
        confidence=0.9,
        start=0,
        end=len(span),
        is_essential=False,
        reasoning="test",
    )


def _completion(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ]
    )


def _stream_part(
    content: str,
    *,
    tool_calls: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))])


def _tool_call(
    arguments: str,
    *,
    call_id: str = "call_1",
    name: str = "send_value",
    response_call_id: str | None = None,
    call_type: str = "function",
    index: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        call_id=response_call_id,
        id=call_id,
        type=call_type,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _tool_completion(
    arguments: str,
    *,
    content: str | None = None,
    call_id: str = "call_1",
    name: str = "send_value",
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=[
                        _tool_call(
                            arguments,
                            call_id=call_id,
                            name=name,
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ]
    )


class CountingAdapter:
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        failures: int = 0,
        stream_factory: Callable[[], object] | None = None,
    ) -> None:
        self.error = error
        self.failures = failures
        self.stream_factory = stream_factory
        self.calls: list[object] = []

    def resolve_backend_model(self, model: str) -> str:
        return model

    def format_response(self, response: object, content: str) -> dict[str, object]:
        return {
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
            "finish_reason": "stop",
        }

    def call(self, model: str, messages: object, *args: object, **kwargs: object) -> object:
        self.calls.append(messages)
        if len(self.calls) <= self.failures:
            assert self.error is not None
            raise self.error
        if kwargs.get("stream"):
            if self.stream_factory is not None:
                return self.stream_factory()
            return iter([_stream_part("ok")])
        return _completion()


class KeywordCapturingAdapter(CountingAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.keyword_calls: list[dict[str, object]] = []
        self.positional_calls: list[tuple[object, ...]] = []

    def call(
        self,
        model: str,
        messages: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        self.positional_calls.append(args)
        self.keyword_calls.append(kwargs)
        return super().call(model, messages, *args, **kwargs)


class MediaRejectingAdapter(CountingAdapter):
    """Simulate a configured local backend that accepts text only."""

    def call(
        self,
        model: str,
        messages: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        self.calls.append(messages)
        if "image_url" in json.dumps(messages):
            raise ValueError("At most 0 image(s) may be provided")
        if kwargs.get("stream"):
            return iter([_stream_part("The attachment could not be analyzed.")])
        return _completion("The attachment could not be analyzed.")


class ToolAdapter(CountingAdapter):
    def __init__(
        self,
        arguments: str,
        *,
        content: str | None = None,
        call_id: str = "call_1",
        name: str = "send_value",
    ) -> None:
        super().__init__()
        self.arguments = arguments
        self.content = content
        self.call_id = call_id
        self.name = name

    def call(
        self,
        model: str,
        messages: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        self.calls.append(messages)
        return _tool_completion(
            self.arguments,
            content=self.content,
            call_id=self.call_id,
            name=self.name,
        )


class MultiToolAdapter(CountingAdapter):
    def __init__(self, tool_calls: list[SimpleNamespace]) -> None:
        super().__init__()
        self.tool_calls = tool_calls

    def call(
        self,
        model: str,
        messages: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        self.calls.append(messages)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=self.tool_calls),
                    finish_reason="tool_calls",
                )
            ]
        )


class ResponsesToolAdapter(CountingAdapter):
    def __init__(self, output: list[SimpleNamespace]) -> None:
        super().__init__()
        self.output = output

    def call(
        self,
        model: str,
        messages: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        self.calls.append(messages)
        return SimpleNamespace(
            output=self.output,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=[]),
                    finish_reason="tool_calls",
                )
            ],
        )


class InMemoryContextCache:
    def __init__(self) -> None:
        self.contexts: dict[str, list[dict[str, str]]] = {}
        self.lock = Lock()

    def get_context(self, chat_id: str) -> list[dict[str, str]]:
        with self.lock:
            return list(self.contexts.get(chat_id, []))

    def put_context(
        self,
        chat_id: str,
        context: list[dict[str, str]],
    ) -> None:
        with self.lock:
            self.contexts[chat_id] = context

    def merge_context(
        self,
        chat_id: str,
        current: list[dict[str, str]],
        merge: Callable[
            [list[dict[str, str]], list[dict[str, str]]],
            list[object],
        ],
    ) -> None:
        with self.lock:
            merged = merge(self.contexts.get(chat_id, []), current)
            self.contexts[chat_id] = [
                (
                    segment
                    if isinstance(segment, dict)
                    else {
                        "label": segment.label,
                        "text": segment.text,
                    }
                )
                for segment in merged
            ]


def _config() -> SimpleNamespace:
    generation = SimpleNamespace(temperature=0.0, max_tokens=32)
    return SimpleNamespace(
        models=[
            SimpleNamespace(id="external-model", location="external"),
            SimpleNamespace(id="local-model", location="local"),
        ],
        external=SimpleNamespace(model="external-model", api_base=None, config=generation),
        local=SimpleNamespace(
            model="local-model",
            api_base="http://local.test/v1",
            config=generation,
        ),
    )


def _adapter_for(local: CountingAdapter, external: CountingAdapter):
    return lambda model: local if model == "local-model" else external


@contextmanager
def _chat_dependencies(
    *,
    route: str,
    local: CountingAdapter,
    external: CountingAdapter,
    requires_masking: bool = False,
    hydration_error: BaseException | None = None,
    records: list[ExtractionRecord] | None = None,
    cache: object | None = None,
):
    pipeline_records = list(records or [])
    if requires_masking and records is None:
        pipeline_records = [
            ExtractionRecord(
                category="TEST_SECRET",
                span="SOURCE_SENTINEL",
                confidence=0.9,
                start=0,
                end=len("SOURCE_SENTINEL"),
                is_essential=False,
                reasoning="test",
            )
        ]
    router = MagicMock()
    router.process.return_value = _pipeline(route, requires_masking, pipeline_records)
    contract = MaskingContract(
        placeholder_map={"TEST_SECRET#deadbeef": "SOURCE_SENTINEL"},
        count=1,
    )

    def mask_chat(
        _messages,
        _records,
        *,
        tools=None,
        tool_choice=None,
    ):
        return SimpleNamespace(
            value=[{"role": "user", "content": "MASKED_REQUEST"}],
            contract=contract,
            tools=tools,
            tool_choice=tool_choice,
        )

    mask_payload = MagicMock(side_effect=mask_chat)
    contract_store = MagicMock()
    contract_store.return_value.create_session.return_value = "session-1"
    hydrate_payload = AsyncMock(return_value="ok", side_effect=hydration_error)

    with (
        patch("server.api.routes.proxy.PrivacyRouter", return_value=router),
        patch("server.api.routes.proxy.mask_chat_messages", mask_payload),
        patch("server.api.routes.proxy.hydrate_masked_response", hydrate_payload),
        patch("server.api.routes.proxy.ContractStore", contract_store),
        patch("server.api.routes.proxy.get_config", return_value=_config()),
        patch(
            "server.api.routes.proxy.adapter_for",
            side_effect=_adapter_for(local, external),
        ),
        patch("server.api.routes.proxy.resolve_api_base", return_value=None),
        patch(
            "server.api.routes.proxy.resolve_local_api_base",
            return_value="http://local.test/v1",
        ),
        patch("server.api.routes.proxy._log_usage"),
        patch("server.api.routes.proxy.get_cache", return_value=cache),
    ):
        yield router, mask_payload


def _chat_request() -> dict[str, object]:
    return {
        "model": "privacy-router/external-model",
        "messages": [{"role": "user", "content": "SOURCE_SENTINEL"}],
        "max_tokens": 32,
    }


def test_classify_analysis_failure_returns_safe_503():
    router = MagicMock()
    router.process.side_effect = PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.")
    safe_client = TestClient(app, raise_server_exceptions=False)

    with patch("server.api.routes.classify.PrivacyRouter", return_value=router):
        response = safe_client.post(
            "/api/v1/classify",
            json={"text": "SOURCE_SENTINEL"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "privacy_analysis_failed"
    assert response.json()["error"]["reason"] == "extraction_failed"
    assert "SOURCE_SENTINEL" not in response.text


def test_classify_success_redacts_span_and_reasoning():
    secret = "SOURCE_SENTINEL"
    reasoning = "Internal analysis containing SOURCE_SENTINEL"
    record = ExtractionRecord(
        category="TEST_SECRET",
        span=secret,
        confidence=0.9,
        start=0,
        end=len(secret),
        is_essential=False,
        reasoning=reasoning,
    )
    router = MagicMock()
    router.process.return_value = _pipeline(
        "external_api",
        requires_masking=True,
        records=[record],
    )

    with (
        patch("server.api.routes.classify.PrivacyRouter", return_value=router),
        patch("server.api.routes.classify.get_config", return_value=_config()),
        patch("server.api.routes.classify._log_classify_usage"),
    ):
        response = client.post(
            "/api/v1/classify",
            json={"text": secret},
        )

    assert response.status_code == 200
    public_record = response.json()["records"][0]
    assert public_record["span"] == "<redacted>"
    assert "reasoning" not in public_record
    assert secret not in json.dumps(public_record)
    assert reasoning not in response.text


def test_generate_schema_failure_returns_safe_503_without_forwarding():
    router = MagicMock()
    router.process.side_effect = ValueError("SCHEMA_SECRET_SENTINEL")
    safe_client = TestClient(app, raise_server_exceptions=False)

    with (
        patch("server.api.routes.classify.PrivacyRouter", return_value=router),
        patch("server.api.routes.classify.call_llm") as llm,
    ):
        response = safe_client.post(
            "/api/v1/generate",
            json={"text": "SOURCE_SENTINEL"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "privacy_analysis_failed"
    assert response.json()["error"]["reason"] == "extraction_failed"
    assert "SOURCE_SENTINEL" not in response.text
    assert "SCHEMA_SECRET_SENTINEL" not in response.text
    llm.assert_not_called()


def test_generate_uses_registry_binding_for_requested_model():
    router = MagicMock()
    router.process.return_value = _pipeline("external_api")
    config = MagicMock()

    with (
        patch("server.api.routes.classify.PrivacyRouter", return_value=router),
        patch("server.api.routes.classify.get_config", return_value=config),
        patch(
            "server.api.routes.classify.resolve_generation_binding",
            return_value=(
                "openrouter/alternate",
                {"temperature": 0.2, "max_tokens": 321},
                "https://alternate.example/v1",
            ),
            create=True,
        ) as binding,
        patch(
            "server.api.routes.classify.call_llm",
            return_value="generated",
        ) as llm,
    ):
        response = client.post(
            "/api/v1/generate",
            json={
                "text": "SOURCE_SENTINEL",
                "model": "openrouter/alternate",
            },
        )

    assert response.status_code == 200
    binding.assert_called_once_with(
        config,
        "allow",
        "openrouter/alternate",
    )
    llm.assert_called_once_with(
        [{"role": "user", "content": "SOURCE_SENTINEL"}],
        model="openrouter/alternate",
        api_base="https://alternate.example/v1",
        temperature=0.2,
        max_tokens=321,
    )
    assert response.json()["model_used"] == "openrouter/alternate"


def test_generate_masks_with_owner_bound_contract_and_chat_messages():
    record = ExtractionRecord(
        category="TEST_SECRET",
        span="SOURCE_SENTINEL",
        confidence=0.9,
        start=0,
        end=len("SOURCE_SENTINEL"),
        is_essential=False,
        reasoning="test",
    )
    pipeline = _pipeline("external_api", True, [record])
    pipeline.judgment.policy_action = "selective_mask"
    router = MagicMock()
    router.process.return_value = pipeline
    masker = MagicMock()
    masker.mask.return_value = SimpleNamespace(
        masked_text="TEST_SECRET#deadbeef",
        contract=MaskingContract(
            placeholder_map={"TEST_SECRET#deadbeef": "SOURCE_SENTINEL"},
            count=1,
        ),
    )
    masker.hydrate.return_value = SimpleNamespace(hydrated_text="restored")
    store = MagicMock()
    store.create_session.return_value = "session-123"

    with (
        patch("server.api.routes.classify.PrivacyRouter", return_value=router),
        patch("server.api.routes.classify.get_config", return_value=MagicMock()),
        patch(
            "server.api.routes.classify.resolve_generation_binding",
            return_value=("external/model", {"temperature": 0.2}, "https://api.test/v1"),
        ),
        patch("server.api.routes.classify.Masker", return_value=masker),
        patch("server.api.routes.classify.ContractStore", return_value=store),
        patch(
            "server.api.routes.classify.call_llm",
            return_value="masked response",
        ) as llm,
    ):
        response = client.post(
            "/api/v1/generate",
            json={"text": "SOURCE_SENTINEL"},
        )

    assert response.status_code == 200
    assert response.json()["content"] == "restored"
    assert response.json()["masking_session_id"] == "session-123"
    llm.assert_called_once_with(
        [{"role": "user", "content": "TEST_SECRET#deadbeef"}],
        model="external/model",
        api_base="https://api.test/v1",
        temperature=0.2,
    )
    assert store.create_session.call_args.kwargs["owner_id"] == "test-provider"
    store.save_records.assert_called_once()


def test_generate_rejects_model_that_crosses_trust_boundary():
    router = MagicMock()
    router.process.return_value = _pipeline("external_api")

    with (
        patch("server.api.routes.classify.PrivacyRouter", return_value=router),
        patch(
            "server.api.routes.classify.resolve_generation_binding",
            side_effect=ValueError("External generation requires an external model"),
            create=True,
        ),
        patch("server.api.routes.classify.call_llm") as llm,
    ):
        response = client.post(
            "/api/v1/generate",
            json={"text": "SOURCE_SENTINEL", "model": "local/model"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid generator model"
    assert "SOURCE_SENTINEL" not in response.text
    llm.assert_not_called()


def test_mcp_allow_uses_registry_binding_and_chat_messages():
    config = MagicMock()
    with (
        patch("server.mcp.tools._load_config", return_value=config),
        patch(
            "server.mcp.tools.resolve_generation_binding",
            return_value=("external/model", {"temperature": 0.1}, "https://api.test/v1"),
        ) as binding,
        patch("server.mcp.tools.call_llm", return_value="generated") as llm,
    ):
        result = mcp_process(
            "SOURCE_SENTINEL",
            action="allow",
            model="external/model",
        )

    binding.assert_called_once_with(config, "allow", "external/model")
    llm.assert_called_once_with(
        [{"role": "user", "content": "SOURCE_SENTINEL"}],
        model="external/model",
        api_base="https://api.test/v1",
        temperature=0.1,
    )
    assert result["content"] == "generated"


def test_mcp_llm_failure_returns_explicit_source_free_error():
    config = MagicMock()
    with (
        patch("server.mcp.tools._load_config", return_value=config),
        patch(
            "server.mcp.tools.resolve_generation_binding",
            return_value=("external/model", {}, "https://api.test/v1"),
        ),
        patch(
            "server.mcp.tools.call_llm",
            side_effect=RuntimeError("PROVIDER_SECRET_SENTINEL"),
        ),
    ):
        result = mcp_process("SOURCE_SENTINEL", action="allow")

    assert result["action_taken"] == "error"
    assert result["content"] is None
    assert result["error_code"] == "llm_request_failed"
    assert "SOURCE_SENTINEL" not in str(result)
    assert "PROVIDER_SECRET_SENTINEL" not in str(result)


@pytest.mark.parametrize("action", ["allow", "generate"])
def test_mcp_binding_failure_returns_explicit_source_free_error(action: str):
    router = MagicMock()
    router.process.return_value = _pipeline("external_api")

    with (
        patch("server.mcp.tools._load_config", return_value=MagicMock()),
        patch("server.mcp.tools.ContractStore"),
        patch("server.mcp.tools.PrivacyRouter", return_value=router),
        patch(
            "server.mcp.tools.resolve_generation_binding",
            side_effect=ValueError("CONFIG_SECRET_SENTINEL"),
        ),
        patch("server.mcp.tools.call_llm") as llm,
    ):
        result = mcp_process("SOURCE_SENTINEL", action=action)

    assert result["action_taken"] == "error"
    assert result["content"] is None
    assert result["error_code"] == "generation_configuration_error"
    assert "SOURCE_SENTINEL" not in str(result)
    assert "CONFIG_SECRET_SENTINEL" not in str(result)
    llm.assert_not_called()


def test_mcp_analysis_failure_returns_unknown_sensitivity_without_forwarding():
    router = MagicMock()
    router.process.side_effect = PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.")

    with (
        patch("server.mcp.tools._load_config", return_value=MagicMock()),
        patch("server.mcp.tools.ContractStore"),
        patch("server.mcp.tools.PrivacyRouter", return_value=router),
        patch("server.mcp.tools.call_llm") as llm,
    ):
        result = mcp_process("SOURCE_SENTINEL", action="classify")

    assert result["action_taken"] == "error"
    assert result["analysis_status"] == "unavailable"
    assert result["is_sensitive"] is None
    assert result["error_code"] == "privacy_analysis_failed"
    assert "SOURCE_SENTINEL" not in str(result)
    llm.assert_not_called()


def test_mcp_schema_failure_returns_source_free_safe_state():
    router = MagicMock()
    router.process.side_effect = ValueError("SCHEMA_SECRET_SENTINEL")

    with (
        patch("server.mcp.tools._load_config", return_value=MagicMock()),
        patch("server.mcp.tools.PrivacyRouter", return_value=router),
        patch("server.mcp.tools.call_llm") as llm,
    ):
        result = mcp_process("SOURCE_SENTINEL", action="classify")

    assert result["action_taken"] == "error"
    assert result["analysis_status"] == "unavailable"
    assert result["is_sensitive"] is None
    assert "SOURCE_SENTINEL" not in str(result)
    assert "SCHEMA_SECRET_SENTINEL" not in str(result)
    llm.assert_not_called()


def test_mcp_review_analysis_failure_returns_explicit_safe_state():
    cache = MagicMock()
    cache.get_extraction.return_value = None
    extractor = MagicMock()
    extractor.extract.side_effect = PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.")
    config = MagicMock()
    config.decision.model = "test/model"
    config.decision.api_base = None

    with (
        patch("server.mcp.tools.get_cache", return_value=cache),
        patch("server.mcp.tools._load_config", return_value=config),
        patch("server.mcp.tools.Extractor", return_value=extractor),
        patch("server.mcp.tools.call_llm") as llm,
    ):
        result = mcp_review("SOURCE_SENTINEL", no_cache=True)

    assert result["analysis_status"] == "unavailable"
    assert result["summary"]["is_sensitive"] is None
    assert result["error_code"] == "privacy_analysis_failed"
    assert "SOURCE_SENTINEL" not in str(result)
    llm.assert_not_called()


def test_mcp_review_malformed_cache_returns_explicit_safe_state():
    cache = MagicMock()
    cache.get_extraction.return_value = {
        "sensitivity": None,
        "records": [],
    }

    with (
        patch("server.mcp.tools.get_cache", return_value=cache),
        patch("server.mcp.tools.call_llm") as llm,
    ):
        result = mcp_review("SOURCE_SENTINEL")

    assert result["analysis_status"] == "unavailable"
    assert result["summary"]["is_sensitive"] is None
    assert result["error_code"] == "privacy_analysis_failed"
    assert "SOURCE_SENTINEL" not in str(result)
    llm.assert_not_called()


def test_mcp_apply_decision_masks_with_complete_contract_call():
    record = ExtractionRecord(
        category="TEST_SECRET",
        span="SOURCE_SENTINEL",
        confidence=0.9,
        start=0,
        end=len("SOURCE_SENTINEL"),
        is_essential=False,
        reasoning="test",
    )
    pipeline = _pipeline("external_api", True, [record])
    pipeline.judgment.policy_action = "selective_mask"
    middle_man = MagicMock()
    middle_man.process_with_decision.return_value = pipeline
    masker = MagicMock()
    masker.mask.return_value = SimpleNamespace(
        masked_text="TEST_SECRET#deadbeef",
        contract=MaskingContract(
            placeholder_map={"TEST_SECRET#deadbeef": "SOURCE_SENTINEL"},
            count=1,
        ),
    )
    masker.hydrate.return_value = SimpleNamespace(hydrated_text="restored")
    store = MagicMock()
    store.create_session.return_value = "session-123"

    with (
        patch(
            "server.mcp.tools._load_extraction",
            return_value=(MagicMock(), False),
        ),
        patch("server.mcp.tools._load_config", return_value=MagicMock()),
        patch("server.mcp.tools.MiddleManAgent", return_value=middle_man),
        patch("server.mcp.tools.Masker", return_value=masker),
        patch("server.mcp.tools.ContractStore", return_value=store),
        patch(
            "server.mcp.tools.resolve_generation_binding",
            return_value=("external/model", {"temperature": 0.1}, None),
        ),
        patch("server.mcp.tools.call_llm", return_value="masked response") as llm,
    ):
        result = mcp_apply_decision("SOURCE_SENTINEL", action="accept")

    assert result["content"] == "restored"
    assert result["masking_session_id"] == "session-123"
    assert store.create_session.call_args.kwargs["chat_id"] is None
    llm.assert_called_once_with(
        [{"role": "user", "content": "TEST_SECRET#deadbeef"}],
        model="external/model",
        api_base=None,
        temperature=0.1,
    )


def test_mcp_apply_decision_llm_failure_returns_explicit_error():
    pipeline = _pipeline("external_api")
    middle_man = MagicMock()
    middle_man.process_with_decision.return_value = pipeline

    with (
        patch(
            "server.mcp.tools._load_extraction",
            return_value=(MagicMock(), False),
        ),
        patch("server.mcp.tools._load_config", return_value=MagicMock()),
        patch("server.mcp.tools.MiddleManAgent", return_value=middle_man),
        patch(
            "server.mcp.tools.resolve_generation_binding",
            return_value=("external/model", {}, None),
        ),
        patch(
            "server.mcp.tools.call_llm",
            side_effect=RuntimeError("PROVIDER_SECRET_SENTINEL"),
        ),
    ):
        result = mcp_apply_decision("SOURCE_SENTINEL", action="accept")

    assert result["action_taken"] == "error"
    assert result["content"] is None
    assert result["error_code"] == "llm_request_failed"
    assert result["user_action"] == "accept"
    assert "SOURCE_SENTINEL" not in str(result)
    assert "PROVIDER_SECRET_SENTINEL" not in str(result)


def test_mcp_apply_decision_binding_failure_returns_explicit_error():
    pipeline = _pipeline("external_api")
    middle_man = MagicMock()
    middle_man.process_with_decision.return_value = pipeline

    with (
        patch(
            "server.mcp.tools._load_extraction",
            return_value=(MagicMock(), False),
        ),
        patch("server.mcp.tools._load_config", return_value=MagicMock()),
        patch("server.mcp.tools.MiddleManAgent", return_value=middle_man),
        patch(
            "server.mcp.tools.resolve_generation_binding",
            side_effect=KeyError("CONFIG_SECRET_SENTINEL"),
        ),
        patch("server.mcp.tools.call_llm") as llm,
    ):
        result = mcp_apply_decision("SOURCE_SENTINEL", action="accept")

    assert result["action_taken"] == "error"
    assert result["content"] is None
    assert result["error_code"] == "generation_configuration_error"
    assert result["user_action"] == "accept"
    assert "SOURCE_SENTINEL" not in str(result)
    assert "CONFIG_SECRET_SENTINEL" not in str(result)
    llm.assert_not_called()


def test_mcp_review_to_apply_round_trips_real_encrypted_cache(
    tmp_path,
    monkeypatch,
):
    cache_engine = create_engine(f"sqlite:///{tmp_path / 'mcp-cache.db'}")
    SQLModel.metadata.create_all(cache_engine)
    monkeypatch.setattr("agents.router.cache.engine", cache_engine)
    cache = SQLiteKVCache()
    text = "Discuss private acquisition target Aurora."
    span = "Aurora"
    start = text.index(span)
    extraction = ExtractionResult(
        sensitivity=Sensitivity(
            is_sensitive=True,
            rationale="Contains a private acquisition target.",
        ),
        records=[
            ExtractionRecord(
                category="ACQUISITION_TARGET",
                span=span,
                confidence=0.98,
                start=start,
                end=start + len(span),
                detection_type="contextual",
                reasoning="The acquisition target is not public.",
                is_essential=True,
            )
        ],
    )
    extractor = MagicMock()
    extractor.extract.return_value = extraction
    config = MagicMock()
    config.decision.model = "test/model"
    config.decision.api_base = None

    with (
        patch("server.mcp.tools.get_cache", return_value=cache),
        patch("server.mcp.tools._load_config", return_value=config),
        patch("server.mcp.tools.Extractor", return_value=extractor),
        patch(
            "server.mcp.tools.resolve_generation_binding",
            return_value=(None, {}, None),
        ),
    ):
        reviewed = mcp_review(text)
        applied = mcp_apply_decision(text, action="accept")

    assert reviewed["summary"]["record_count"] == 1
    assert applied["action_taken"] != "error"
    assert applied["extraction_records"][0]["span"] == "<redacted>"
    extractor.extract.assert_called_once_with(text)
    with Session(cache_engine) as session:
        stored = session.exec(select(ExtractionCache)).one()
    assert text not in stored.extraction
    assert span not in stored.extraction


def test_mcp_apply_decision_analysis_failure_does_not_forward():
    cache = MagicMock()
    cache.get_extraction.return_value = None
    extractor = MagicMock()
    extractor.extract.side_effect = ValueError("SCHEMA_SECRET_SENTINEL")
    config = MagicMock()
    config.decision.model = "test/model"
    config.decision.api_base = None

    with (
        patch("server.mcp.tools.get_cache", return_value=cache),
        patch("server.mcp.tools._load_config", return_value=config),
        patch("server.mcp.tools.Extractor", return_value=extractor),
        patch("server.mcp.tools.call_llm") as llm,
    ):
        result = mcp_apply_decision(
            "SOURCE_SENTINEL",
            action="accept",
            no_cache=True,
        )

    assert result["action_taken"] == "error"
    assert result["analysis_status"] == "unavailable"
    assert result["is_sensitive"] is None
    assert result["error_code"] == "privacy_analysis_failed"
    assert "SOURCE_SENTINEL" not in str(result)
    assert "SCHEMA_SECRET_SENTINEL" not in str(result)
    llm.assert_not_called()


def test_chat_analysis_failure_returns_safe_503_without_forwarding():
    local = CountingAdapter()
    external = CountingAdapter()

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        router.process.side_effect = PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.")
        response = client.post("/v1/chat/completions", json=_chat_request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "privacy_analysis_failed"
    assert response.json()["error"]["reason"] == "extraction_failed"
    assert "SOURCE_SENTINEL" not in response.text
    assert local.calls == []
    assert external.calls == []


def test_chat_local_timeout_retries_only_local_and_returns_safe_503(caplog):
    local = CountingAdapter(error=TimeoutError("CHAT_SECRET_SENTINEL"), failures=3)
    external = CountingAdapter()

    with _chat_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=_chat_request())

    body = response.json()["error"]
    assert response.status_code == 503
    assert len(local.calls) == 3
    assert external.calls == []
    assert body["code"] == "privacy_route_unavailable"
    assert body["reason"] == "timeout"
    assert body["attempts"] == 3
    assert body["retryable"] is True
    assert body["request_id"]
    assert "전환되지 않았습니다" in body["message"]
    assert "CHAT_SECRET_SENTINEL" not in response.text
    assert "CHAT_SECRET_SENTINEL" not in caplog.text


def test_chat_external_timeout_retries_only_external_with_same_payload():
    local = CountingAdapter()
    external = CountingAdapter(error=ConnectionError("unused"), failures=2)

    with _chat_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=_chat_request())

    assert response.status_code == 200
    assert local.calls == []
    assert len(external.calls) == 3
    assert external.calls[0] is external.calls[1] is external.calls[2]


def test_chat_hydration_failure_returns_safe_error_without_success_body():
    local = CountingAdapter()
    external = CountingAdapter()

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
        hydration_error=ValueError("HYDRATION_SENTINEL"),
    ):
        response = client.post("/v1/chat/completions", json=_chat_request())

    assert response.status_code == 502
    assert response.json()["error"]["reason"] == "hydration_failed"
    assert "choices" not in response.json()
    assert "HYDRATION_SENTINEL" not in response.text


@pytest.mark.parametrize(
    ("privacy_options", "expected_value"),
    [
        (None, "TEST_SECRET#deadbeef"),
        ({"allow_sensitive_tool_arguments": True}, "SOURCE_SENTINEL"),
        ({"allow_sensitive_tool_arguments": "true"}, "TEST_SECRET#deadbeef"),
    ],
)
def test_chat_tool_arguments_require_explicit_release(privacy_options, expected_value):
    local = CountingAdapter()
    external = ToolAdapter('{"value":"TEST_SECRET#deadbeef"}')
    payload = _chat_request()
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]

    if privacy_options is not None:
        payload["privacy_router"] = privacy_options

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    arguments = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert response.status_code == 200
    assert json.loads(arguments) == {"value": expected_value}


def test_chat_hydrates_content_when_tool_calls_are_present():
    local = CountingAdapter()
    external = ToolAdapter(
        '{"value":"TEST_SECRET#deadbeef"}',
        content="Draft for TEST_SECRET#deadbeef",
    )
    payload = _chat_request()
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    message = response.json()["choices"][0]["message"]
    assert response.status_code == 200
    assert message["content"] == "ok"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"value": "TEST_SECRET#deadbeef"}


def test_chat_tool_arguments_fail_closed_for_unknown_placeholder(monkeypatch):
    monkeypatch.delenv("PRIVACY_ROUTER_BETA_PLACEHOLDER_REPAIR", raising=False)
    local = CountingAdapter()
    external = ToolAdapter('{"value":"TEST_SECRET#badc0ffe"}')
    payload = _chat_request()
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 502
    assert response.json()["error"]["reason"] == "hydration_failed"
    assert "TEST_SECRET#badc0ffe" not in response.text


def test_chat_tool_arguments_use_beta_repair_before_delivery(monkeypatch):
    monkeypatch.setenv("PRIVACY_ROUTER_BETA_PLACEHOLDER_REPAIR", "true")
    local = CountingAdapter()
    external = ToolAdapter('{"value":"TEST_SECRET#badc0ffe"}')

    payload = _chat_request()
    payload["tools"] = [_declared_send_value_tool()]
    payload["privacy_router"] = {"allow_sensitive_tool_arguments": True}

    with (
        _chat_dependencies(
            route="external_api",
            local=local,
            external=external,
            requires_masking=True,
        ),
        patch("server.api.routes.proxy.PlaceholderRepairer") as repairer_cls,
    ):
        repairer_cls.return_value.repair = AsyncMock(return_value="TEST_SECRET#deadbeef")
        response = client.post("/v1/chat/completions", json=payload)

    arguments = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert response.status_code == 200
    assert json.loads(arguments) == {"value": "SOURCE_SENTINEL"}
    assert repairer_cls.call_args.args == ("local-model",)
    assert repairer_cls.call_args.kwargs == {"api_base": "http://local.test/v1"}
    repair = repairer_cls.return_value.repair
    assert repair.await_count == 1
    assert repair.await_args.kwargs["observed"] == "TEST_SECRET#badc0ffe"
    assert "TEST_SECRET#badc0ffe" not in response.text


@pytest.mark.parametrize(
    ("allow_sensitive", "expected_value"),
    [(False, "TEST_SECRET#deadbeef"), (True, "SOURCE_SENTINEL")],
)
def test_chat_stream_requires_explicit_release_for_tool_arguments(
    allow_sensitive,
    expected_value,
):
    def tool_stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            _tool_call(
                                '{"value":"TEST_SECRET#',
                                name="send_",
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ]
        )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            _tool_call(
                                'deadbeef"}',
                                call_id=None,
                                name="value",
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ]
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream)
    payload = _chat_request()
    payload["stream"] = True
    if allow_sensitive:
        payload["privacy_router"] = {"allow_sensitive_tool_arguments": True}
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    chunks = [
        json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: {")
    ]
    tool_chunk = next(chunk for chunk in chunks if chunk["choices"][0]["delta"].get("tool_calls"))
    arguments = tool_chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(arguments) == {"value": expected_value}
    assert '"finish_reason": "tool_calls"' in response.text


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("allow_sensitive", [False, True])
def test_chat_local_tool_arguments_mask_model_output_by_default(
    stream,
    allow_sensitive,
):
    raw_secret = "MODEL_OUTPUT_SECRET"
    raw_arguments = '{"value":"\\u004dODEL_OUTPUT_SECRET"}'

    def tool_stream():
        yield _stream_part(
            "",
            tool_calls=[_tool_call(raw_arguments)],
        )

    local = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = stream
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]
    if allow_sensitive:
        payload["privacy_router"] = {"allow_sensitive_tool_arguments": True}

    with _chat_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        router.process.side_effect = [
            _pipeline("local_api"),
            _pipeline(
                "local_api",
                True,
                [_extraction_record(raw_secret)],
            ),
        ]
        response = client.post("/v1/chat/completions", json=payload)

    if stream:
        chunks = [
            json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: {")
        ]
        tool_chunk = next(chunk for chunk in chunks if chunk["choices"][0]["delta"].get("tool_calls"))
        arguments = tool_chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
    else:
        arguments = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]

    value = json.loads(arguments)["value"]
    assert response.status_code == 200
    if allow_sensitive:
        assert value == raw_secret
    else:
        assert value.startswith("SENSITIVE_DATA#")
        assert raw_secret not in response.text
    assert router.process.call_count == 2
    inspected_arguments = router.process.call_args_list[1].args[0]
    assert raw_secret in inspected_arguments
    assert "\\u004d" not in inspected_arguments
    assert 'PROTOCOL_FIELD path="/id"' in inspected_arguments
    assert 'PROTOCOL_FIELD path="/name"' in inspected_arguments
    assert "call_1" in inspected_arguments
    assert "send_value" in inspected_arguments


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("allow_sensitive", [False, True])
def test_chat_local_tool_argument_inspection_failure_is_fail_closed(
    stream,
    allow_sensitive,
    caplog,
):
    raw_secret = "MODEL_OUTPUT_SECRET"
    raw_arguments = json.dumps({"value": raw_secret})

    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = stream
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]
    if allow_sensitive:
        payload["privacy_router"] = {
            "allow_sensitive_tool_arguments": True,
        }

    with _chat_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        router.process.side_effect = [
            _pipeline("local_api"),
            PrivacyAnalysisUnavailable(raw_arguments),
        ]
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == (200 if stream else 502)
    assert raw_secret not in response.text
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert router.process.call_count == 2
    failure_records = [record for record in caplog.records if record.getMessage() == "privacy_route_failed"]
    assert len(failure_records) == 1
    failure_record = failure_records[0]
    assert failure_record.request_id.startswith("chatcmpl-")
    assert failure_record.route == "local_api"
    assert failure_record.attempts == 1
    assert failure_record.reason == "hydration_failed"
    assert failure_record.retryable is False
    assert raw_secret not in repr(failure_record.__dict__)
    assert failure_record.exc_info is None
    assert raw_secret not in caplog.text


def test_chat_local_stream_buffers_content_before_unrequested_tool_call_validation():
    def mixed_stream():
        yield _stream_part("FIRST_CONTENT")
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":NaN}')],
        )

    local = CountingAdapter(stream_factory=mixed_stream)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = True

    with _chat_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert "FIRST_CONTENT" not in response.text
    assert '"reason": "hydration_failed"' in response.text
    assert router.process.call_count == 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "raw_arguments",
    [
        '{"value":NaN}',
        '{"value":"UNKNOWN#badc0ffe","value":"safe"}',
        '{"value":"\\u0000MODEL_OUTPUT_SECRET"}',
    ],
)
def test_chat_local_tool_arguments_reject_unsafe_input(stream, raw_arguments):

    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = stream
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]

    with _chat_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == (200 if stream else 502)
    assert "NaN" not in response.text
    assert "UNKNOWN#badc0ffe" not in response.text
    assert "MODEL_OUTPUT_SECRET" not in response.text
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert router.process.call_count == 1


@pytest.mark.asyncio
async def test_chat_immediate_requests_are_not_starved_by_sync_stream():
    local = CountingAdapter()
    external = CountingAdapter()
    stream_started = Event()
    release_stream = Event()
    async_stream_started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def blocking_stream():
        stream_started.set()
        loop.call_soon_threadsafe(async_stream_started.set)
        release_stream.wait(timeout=10)
        yield _stream_part("ok")

    def stream_provider(*args, **kwargs):
        assert kwargs["stream"] is True
        return blocking_stream()

    def release_if_starved():
        assert stream_started.wait(timeout=10)
        release_stream.wait(timeout=3)
        release_stream.set()

    external.call = stream_provider
    payload = {**_chat_request(), "stream": True}
    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        transport = httpx.ASGITransport(app=app)
        with ThreadPoolExecutor(max_workers=1) as executor:
            release_future = executor.submit(release_if_starved)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as async_client:
                stream_task = asyncio.create_task(async_client.post("/v1/chat/completions", json=payload))
                try:
                    await asyncio.wait_for(async_stream_started.wait(), timeout=10)
                    assert not release_stream.is_set()
                    started = time.monotonic()
                    models = await asyncio.wait_for(
                        async_client.get("/v1/models"),
                        timeout=1.5,
                    )
                    elapsed = time.monotonic() - started
                finally:
                    release_stream.set()
                    await stream_task
            release_future.result(timeout=12)

    assert models.status_code == 200
    assert elapsed < 0.75


def test_chat_stream_buffers_content_until_tool_arguments_validate():
    def mixed_stream():
        yield _stream_part("FIRST_CONTENT")
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":"TEST_SECRET#badc0ffe"}')],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=mixed_stream)
    payload = _chat_request()
    payload["stream"] = True
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert "FIRST_CONTENT" not in response.text
    assert "TEST_SECRET#badc0ffe" not in response.text
    assert '"reason": "hydration_failed"' in response.text
    assert '"finish_reason": "stop"' not in response.text


def test_chat_stream_releases_buffered_content_after_tool_arguments_validate():
    def mixed_stream():
        yield _stream_part("FIRST_CONTENT")
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":"TEST_SECRET#deadbeef"}')],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=mixed_stream)
    payload = _chat_request()
    payload["stream"] = True
    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "send_value",
                "parameters": {"type": "object"},
            },
        }
    ]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert "FIRST_CONTENT" in response.text
    chunks = [
        json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: {")
    ]
    tool_chunk = next(chunk for chunk in chunks if chunk["choices"][0]["delta"].get("tool_calls"))
    arguments = tool_chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(arguments) == {"value": "TEST_SECRET#deadbeef"}
    assert '"finish_reason": "tool_calls"' in response.text


@contextmanager
def _responses_dependencies(
    *,
    route: str,
    local: CountingAdapter,
    external: CountingAdapter,
    requires_masking: bool = False,
    hydration_error: BaseException | None = None,
):
    records = []
    if requires_masking:
        records = [
            ExtractionRecord(
                category="TEST_SECRET",
                span="SOURCE_SENTINEL",
                confidence=0.9,
                start=0,
                end=len("SOURCE_SENTINEL"),
                is_essential=False,
                reasoning="test",
            )
        ]
    router = MagicMock()
    router.process.return_value = _pipeline(route, requires_masking, records)
    contract = MaskingContract(
        placeholder_map={"TEST_SECRET#deadbeef": "SOURCE_SENTINEL"},
        count=1,
    )

    def mask_responses(
        _input,
        _records,
        *,
        instructions=None,
        tools=None,
        tool_choice=None,
    ):
        return SimpleNamespace(
            value="MASKED_REQUEST",
            contract=contract,
            instructions=instructions,
            tools=tools,
            tool_choice=tool_choice,
        )

    mask_payload = MagicMock(side_effect=mask_responses)
    hydrate_payload = AsyncMock(return_value="ok", side_effect=hydration_error)

    with (
        patch("server.api.routes.responses.PrivacyRouter", return_value=router),
        patch("server.api.routes.responses.mask_responses_input", mask_payload),
        patch("server.api.routes.responses.hydrate_masked_response", hydrate_payload),
        patch("server.api.routes.responses.get_config", return_value=_config()),
        patch(
            "server.api.routes.responses.adapter_for",
            side_effect=_adapter_for(local, external),
        ),
        patch("server.api.routes.responses.resolve_api_base", return_value=None),
        patch(
            "server.api.routes.responses.resolve_local_api_base",
            return_value="http://local.test/v1",
        ),
    ):
        yield router, mask_payload


def _responses_request() -> dict[str, object]:
    return {
        "model": "privacy-router/external-model",
        "input": "SOURCE_SENTINEL",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("blocking_stage", ["analysis", "provider"])
async def test_responses_immediate_errors_are_not_starved_by_slow_work(
    blocking_stage: str,
):
    local = CountingAdapter()
    external = CountingAdapter()
    stage_started = Event()
    release_stage = Event()
    async_stage_started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def slow_process(_: str):
        stage_started.set()
        loop.call_soon_threadsafe(async_stage_started.set)
        release_stage.wait(timeout=10)
        return _pipeline("external_api")

    def slow_provider(*args, **kwargs):
        stage_started.set()
        loop.call_soon_threadsafe(async_stage_started.set)
        release_stage.wait(timeout=10)
        return _completion()

    def release_if_starved():
        assert stage_started.wait(timeout=10)
        release_stage.wait(timeout=3)
        release_stage.set()

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ) as (router, _):
        if blocking_stage == "analysis":
            router.process.side_effect = slow_process
        else:
            external.call = slow_provider
        transport = httpx.ASGITransport(app=app)
        with ThreadPoolExecutor(max_workers=1) as executor:
            release_future = executor.submit(release_if_starved)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as async_client:
                slow_task = asyncio.create_task(async_client.post("/v1/responses", json=_responses_request()))
                try:
                    await asyncio.wait_for(async_stage_started.wait(), timeout=10)
                    assert not release_stage.is_set()
                    started = time.monotonic()
                    missing = await asyncio.wait_for(
                        async_client.post(
                            "/v1/responses",
                            json={
                                **_responses_request(),
                                "previous_response_id": "resp_missing",
                            },
                        ),
                        timeout=1.5,
                    )
                    elapsed = time.monotonic() - started
                finally:
                    release_stage.set()
                    await slow_task
            release_future.result(timeout=12)

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "previous_response_not_found"
    assert elapsed < 0.75


@pytest.mark.asyncio
async def test_responses_immediate_errors_are_not_starved_by_sync_stream():
    local = CountingAdapter()
    external = CountingAdapter()
    stream_started = Event()
    release_stream = Event()
    async_stream_started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def blocking_stream():
        stream_started.set()
        loop.call_soon_threadsafe(async_stream_started.set)
        release_stream.wait(timeout=10)
        yield _stream_part("ok")

    def stream_provider(*args, **kwargs):
        assert kwargs["stream"] is True
        return blocking_stream()

    def release_if_starved():
        assert stream_started.wait(timeout=10)
        release_stream.wait(timeout=3)
        release_stream.set()

    external.call = stream_provider
    payload = {**_responses_request(), "stream": True}
    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        transport = httpx.ASGITransport(app=app)
        with ThreadPoolExecutor(max_workers=1) as executor:
            release_future = executor.submit(release_if_starved)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as async_client:
                stream_task = asyncio.create_task(async_client.post("/v1/responses", json=payload))
                try:
                    await asyncio.wait_for(async_stream_started.wait(), timeout=10)
                    assert not release_stream.is_set()
                    started = time.monotonic()
                    missing = await asyncio.wait_for(
                        async_client.post(
                            "/v1/responses",
                            json={
                                **_responses_request(),
                                "previous_response_id": "resp_missing",
                            },
                        ),
                        timeout=1.5,
                    )
                    elapsed = time.monotonic() - started
                finally:
                    release_stream.set()
                    await stream_task
            release_future.result(timeout=12)

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "previous_response_not_found"
    assert elapsed < 0.75


def test_responses_rejects_non_function_tools_before_provider_call():
    local = CountingAdapter()
    external = CountingAdapter()
    payload = _responses_request()
    payload["tools"] = [
        {
            "type": "file_search",
            "vector_store_ids": ["vs_123"],
        }
    ]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 400
    assert "Only function tools are supported" in response.json()["error"]["message"]
    assert external.calls == []


def test_responses_normalizes_forced_function_tool_choice_for_chat_provider():
    local = CountingAdapter()
    external = KeywordCapturingAdapter()
    payload = _responses_request()
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]
    payload["tool_choice"] = {"type": "function", "name": "send_value"}

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert external.keyword_calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "send_value"},
    }


def test_responses_stream_emits_matching_items_with_stable_output_indexes():
    def mixed_stream():
        yield _stream_part("hello")
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":"safe"}')],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=mixed_stream)
    payload = _responses_request()
    payload["stream"] = True
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    events = []
    for block in response.text.split("\n\n"):
        lines = block.splitlines()
        if len(lines) != 2 or not lines[0].startswith("event: "):
            continue
        events.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    added = [data for event, data in events if event == "response.output_item.added"]
    done = [data for event, data in events if event == "response.output_item.done"]

    assert response.status_code == 200
    assert [(event.get("output_index"), event.get("item", {}).get("type")) for event in added] == [
        (0, "message"),
        (1, "function_call"),
    ]
    assert [(event.get("output_index"), event.get("item", {}).get("type")) for event in done] == [
        (0, "message"),
        (1, "function_call"),
    ]
    arguments_done = next(data for event, data in events if event == "response.function_call_arguments.done")
    assert arguments_done["output_index"] == 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("allow_sensitive", [False, True])
def test_responses_local_tool_arguments_mask_model_output_by_default(
    stream,
    allow_sensitive,
):
    raw_secret = "MODEL_OUTPUT_SECRET"
    raw_arguments = '{"value":"\\u004dODEL_OUTPUT_SECRET"}'

    def tool_stream():
        yield _stream_part(
            "",
            tool_calls=[_tool_call(raw_arguments)],
        )

    local = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = stream
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]
    if allow_sensitive:
        payload["privacy_router"] = {"allow_sensitive_tool_arguments": True}

    with _responses_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        router.process.side_effect = [
            _pipeline("local_api"),
            _pipeline(
                "local_api",
                True,
                [_extraction_record(raw_secret)],
            ),
        ]
        response = client.post("/v1/responses", json=payload)

    if stream:
        events = _decode_sse_events(response)
        arguments = next(
            data["arguments"] for event, data in events if event == "response.function_call_arguments.done"
        )
    else:
        function_call = next(item for item in response.json()["output"] if item["type"] == "function_call")
        arguments = function_call["arguments"]

    value = json.loads(arguments)["value"]
    assert response.status_code == 200
    if allow_sensitive:
        assert value == raw_secret
    else:
        assert value.startswith("SENSITIVE_DATA#")
        assert raw_secret not in response.text
    assert router.process.call_count == 2
    inspected_arguments = router.process.call_args_list[1].args[0]
    assert raw_secret in inspected_arguments
    assert "\\u004d" not in inspected_arguments
    assert 'PROTOCOL_FIELD path="/id"' in inspected_arguments
    assert 'PROTOCOL_FIELD path="/call_id"' in inspected_arguments
    assert 'PROTOCOL_FIELD path="/name"' in inspected_arguments
    assert "call_1" in inspected_arguments
    assert "send_value" in inspected_arguments


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("allow_sensitive", [False, True])
def test_responses_local_tool_argument_inspection_failure_is_fail_closed(
    stream,
    allow_sensitive,
):
    raw_secret = "MODEL_OUTPUT_SECRET"
    raw_arguments = json.dumps({"value": raw_secret})

    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = stream
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]
    if allow_sensitive:
        payload["privacy_router"] = {
            "allow_sensitive_tool_arguments": True,
        }

    with _responses_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        router.process.side_effect = [
            _pipeline("local_api"),
            PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable."),
        ]
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == (200 if stream else 502)
    assert raw_secret not in response.text
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert router.process.call_count == 2


def test_responses_local_stream_buffers_content_before_unrequested_tool_call_validation():
    def mixed_stream():
        yield _stream_part("FIRST_CONTENT")
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":NaN}')],
        )

    local = CountingAdapter(stream_factory=mixed_stream)
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = True

    with _responses_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert "FIRST_CONTENT" not in response.text
    assert '"reason": "hydration_failed"' in response.text
    assert router.process.call_count == 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "raw_arguments",
    [
        '{"value":NaN}',
        '{"value":"UNKNOWN#badc0ffe","value":"safe"}',
        '{"value":"\\u0000MODEL_OUTPUT_SECRET"}',
    ],
)
def test_responses_local_tool_arguments_reject_unsafe_input(
    stream,
    raw_arguments,
):
    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = stream
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]

    with _responses_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == (200 if stream else 502)
    assert "NaN" not in response.text
    assert "UNKNOWN#badc0ffe" not in response.text
    assert "MODEL_OUTPUT_SECRET" not in response.text
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert router.process.call_count == 1


def test_responses_analysis_failure_returns_safe_503_without_forwarding():
    local = CountingAdapter()
    external = CountingAdapter()

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ) as (router, _mask_payload):
        router.process.side_effect = PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.")
        response = client.post("/v1/responses", json=_responses_request())

    body = response.json()
    assert response.status_code == 503
    assert body["error"]["code"] == "privacy_analysis_failed"
    assert body["error"]["reason"] == "extraction_failed"
    assert body["output"] == []
    assert "SOURCE_SENTINEL" not in response.text
    assert local.calls == []
    assert external.calls == []


def test_responses_local_timeout_retries_only_local_and_returns_safe_error(caplog):
    local = CountingAdapter(error=TimeoutError("RESPONSES_SECRET_SENTINEL"), failures=3)
    external = CountingAdapter()

    with _responses_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/responses", json=_responses_request())

    body = response.json()["error"]
    assert response.status_code == 503
    assert len(local.calls) == 3
    assert external.calls == []
    assert body["reason"] == "timeout"
    assert body["attempts"] == 3
    assert body["retryable"] is True
    assert body["request_id"] == response.json()["id"]
    assert "RESPONSES_SECRET_SENTINEL" not in response.text
    assert "RESPONSES_SECRET_SENTINEL" not in caplog.text


def test_responses_external_non_retryable_error_stops_after_one_attempt(caplog):
    local = CountingAdapter()
    external = CountingAdapter(error=ValueError("provider detail"), failures=1)

    with _responses_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/responses", json=_responses_request())

    assert response.status_code == 502
    assert local.calls == []
    assert len(external.calls) == 1
    assert response.json()["error"]["reason"] == "adapter_error"
    assert response.json()["error"]["retryable"] is False
    assert "provider detail" not in response.text
    assert "provider detail" not in caplog.text


def test_responses_hydration_failure_returns_safe_error_without_output():
    local = CountingAdapter()
    external = CountingAdapter()

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
        hydration_error=ValueError("HYDRATION_SENTINEL"),
    ):
        response = client.post("/v1/responses", json=_responses_request())

    assert response.status_code == 502
    assert response.json()["error"]["reason"] == "hydration_failed"
    assert response.json()["output"] == []
    assert "HYDRATION_SENTINEL" not in response.text


@pytest.mark.parametrize(
    ("privacy_options", "expected_value"),
    [
        (None, "TEST_SECRET#deadbeef"),
        ({"allow_sensitive_tool_arguments": True}, "SOURCE_SENTINEL"),
        ({"allow_sensitive_tool_arguments": 1}, "TEST_SECRET#deadbeef"),
    ],
)
def test_responses_tool_arguments_require_explicit_release(
    privacy_options,
    expected_value,
):
    local = CountingAdapter()
    external = ToolAdapter('{"value":"TEST_SECRET#deadbeef"}')
    payload = _responses_request()
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]

    if privacy_options is not None:
        payload["privacy_router"] = privacy_options

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/responses", json=payload)

    function_call = next(item for item in response.json()["output"] if item["type"] == "function_call")
    assert response.status_code == 200
    assert json.loads(function_call["arguments"]) == {"value": expected_value}


def test_responses_tool_arguments_use_beta_repair_before_delivery(monkeypatch):
    monkeypatch.setenv("PRIVACY_ROUTER_BETA_PLACEHOLDER_REPAIR", "true")
    local = CountingAdapter()
    external = ToolAdapter('{"value":"TEST_SECRET#badc0ffe"}')

    payload = _responses_request()
    payload["tools"] = [_declared_responses_send_value_tool()]
    payload["privacy_router"] = {"allow_sensitive_tool_arguments": True}

    with (
        _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
            requires_masking=True,
        ),
        patch("server.api.routes.responses.PlaceholderRepairer") as repairer_cls,
    ):
        repairer_cls.return_value.repair = AsyncMock(return_value="TEST_SECRET#deadbeef")
        response = client.post("/v1/responses", json=payload)

    function_call = next(item for item in response.json()["output"] if item["type"] == "function_call")
    assert response.status_code == 200
    assert json.loads(function_call["arguments"]) == {"value": "SOURCE_SENTINEL"}
    assert repairer_cls.call_args.args == ("local-model",)
    assert repairer_cls.call_args.kwargs == {"api_base": "http://local.test/v1"}
    repair = repairer_cls.return_value.repair
    assert repair.await_count == 1
    assert repair.await_args.kwargs["observed"] == "TEST_SECRET#badc0ffe"
    assert "TEST_SECRET#badc0ffe" not in response.text


@pytest.mark.parametrize(
    ("allow_sensitive", "expected_value"),
    [(False, "TEST_SECRET#deadbeef"), (True, "SOURCE_SENTINEL")],
)
def test_responses_stream_requires_explicit_release_for_tool_arguments(
    allow_sensitive,
    expected_value,
):
    def tool_stream():
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":"TEST_SECRET#', name="send_")],
        )
        yield _stream_part(
            "",
            tool_calls=[_tool_call('deadbeef"}', call_id=None, name="value")],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream)
    payload = _responses_request()
    payload["stream"] = True
    if allow_sensitive:
        payload["privacy_router"] = {"allow_sensitive_tool_arguments": True}
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    events = _decode_sse_events(response)
    arguments_done = next(payload for event, payload in events if event == "response.function_call_arguments.done")
    assert json.loads(arguments_done["arguments"]) == {"value": expected_value}
    assert "response.function_call_arguments.done" in response.text


def test_responses_stream_buffers_content_until_tool_arguments_validate():
    def mixed_stream():
        yield _stream_part("FIRST_CONTENT")
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":"TEST_SECRET#badc0ffe"}')],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=mixed_stream)
    payload = _responses_request()
    payload["stream"] = True
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert "FIRST_CONTENT" not in response.text
    assert "TEST_SECRET#badc0ffe" not in response.text
    assert "response.failed" in response.text
    assert '"reason": "hydration_failed"' in response.text
    assert "response.completed" not in response.text


def test_responses_stream_releases_buffered_content_after_tool_arguments_validate():
    def mixed_stream():
        yield _stream_part("FIRST_CONTENT")
        yield _stream_part(
            "",
            tool_calls=[_tool_call('{"value":"TEST_SECRET#deadbeef"}')],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=mixed_stream)
    payload = _responses_request()
    payload["stream"] = True
    payload["tools"] = [
        {
            "type": "function",
            "name": "send_value",
            "parameters": {"type": "object"},
        }
    ]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert "FIRST_CONTENT" in response.text
    events = _decode_sse_events(response)
    arguments_done = next(payload for event, payload in events if event == "response.function_call_arguments.done")
    assert json.loads(arguments_done["arguments"]) == {"value": "TEST_SECRET#deadbeef"}
    assert "response.completed" in response.text
    assert "response.failed" not in response.text


def _late_stream_error():
    yield _stream_part("FIRST_SAFE_CHUNK")
    raise TimeoutError("STREAM_SECRET_SENTINEL")


def test_chat_stream_local_timeout_retries_only_local_and_emits_safe_failure():
    local = CountingAdapter(error=TimeoutError("CHAT_STREAM_SECRET_SENTINEL"), failures=3)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = True

    with _chat_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert len(local.calls) == 3
    assert external.calls == []
    assert '"reason": "timeout"' in response.text
    assert "CHAT_STREAM_SECRET_SENTINEL" not in response.text
    assert '"finish_reason": "stop"' not in response.text
    assert response.text.endswith("data: [DONE]\n\n")


def test_chat_stream_late_external_timeout_does_not_retry_or_finish():
    local = CountingAdapter()
    external = CountingAdapter(stream_factory=_late_stream_error)
    payload = _chat_request()
    payload["stream"] = True

    with _chat_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert local.calls == []
    assert len(external.calls) == 1
    assert "FIRST_SAFE_CHUNK" in response.text
    assert '"reason": "timeout"' in response.text
    assert "STREAM_SECRET_SENTINEL" not in response.text
    assert '"finish_reason": "stop"' not in response.text


def test_responses_stream_local_timeout_retries_only_local_and_emits_safe_failure():
    local = CountingAdapter(error=TimeoutError("RESPONSES_STREAM_SECRET_SENTINEL"), failures=3)
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = True

    with _responses_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert len(local.calls) == 3
    assert external.calls == []
    assert "response.failed" in response.text
    assert '"reason": "timeout"' in response.text
    assert "RESPONSES_STREAM_SECRET_SENTINEL" not in response.text
    assert "response.completed" not in response.text
    assert response.text.endswith("data: [DONE]\n\n")


def test_responses_stream_late_external_timeout_does_not_retry_or_complete():
    local = CountingAdapter()
    external = CountingAdapter(stream_factory=_late_stream_error)
    payload = _responses_request()
    payload["stream"] = True

    with _responses_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert local.calls == []
    assert len(external.calls) == 1
    assert "FIRST_SAFE_CHUNK" in response.text
    assert "response.failed" in response.text
    assert '"reason": "timeout"' in response.text
    assert "STREAM_SECRET_SENTINEL" not in response.text
    assert "response.completed" not in response.text


def test_chat_local_success_never_calls_external():
    local = CountingAdapter()
    external = CountingAdapter()

    with _chat_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=_chat_request())

    assert response.status_code == 200
    assert len(local.calls) == 1
    assert external.calls == []


def test_responses_local_retry_keeps_selected_payload_and_succeeds():
    local = CountingAdapter(error=ConnectionError("temporary"), failures=2)
    external = CountingAdapter()

    with _responses_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/responses", json=_responses_request())

    assert response.status_code == 200
    assert len(local.calls) == 3
    assert local.calls[0] is local.calls[1] is local.calls[2]
    assert external.calls == []


def test_responses_masks_pipeline_records_without_reextracting():
    local = CountingAdapter()
    external = CountingAdapter()

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
        requires_masking=True,
    ) as (router, mask_payload):
        response = client.post("/v1/responses", json=_responses_request())

    sent_records = mask_payload.call_args.args[1]
    assert response.status_code == 200
    assert router.process.call_count == 1
    assert mask_payload.call_count == 1
    assert len(sent_records) == 1
    assert sent_records[0].span == "SOURCE_SENTINEL"
    public_record = response.json()["metadata"]["privacy_router"]["extraction_records"][0]
    assert public_record["span"] == "<redacted>"
    assert "reasoning" not in public_record


def test_chat_metadata_never_echoes_extractor_reasoning_from_session_context():
    local = CountingAdapter()
    external = CountingAdapter()
    cache = InMemoryContextCache()
    cache.contexts["test-provider\x00shared-chat"] = [
        {"label": "message[0].content", "text": "Project Aurora is confidential"},
    ]
    record = ExtractionRecord(
        category="PHONE_NUMBER",
        span="CURRENT_PHONE",
        confidence=0.99,
        reasoning="The prior turn says Project Aurora is confidential",
        start=5,
        end=18,
        is_essential=False,
    )

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
        records=[record],
        requires_masking=True,
        cache=cache,
    ):
        payload = _chat_request()
        payload["messages"] = [{"role": "user", "content": "Call CURRENT_PHONE"}]
        response = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"x-chat-id": "shared-chat"},
        )

    assert response.status_code == 200
    metadata = response.json()["privacy_router"]["extraction_records"][0]
    assert metadata["span"] == "<redacted>"
    assert "reasoning" not in metadata
    assert "Project Aurora" not in response.text
    assert "CURRENT_PHONE" not in response.text
    assert "original_text" not in response.json()["privacy_router"]


def test_concurrent_chat_deltas_preserve_both_session_turns():
    local = CountingAdapter()
    external = CountingAdapter()
    cache = InMemoryContextCache()
    first_started = Event()
    second_started = Event()
    release_first = Event()

    class ControlledRouter:
        def process(self, text: str):
            if "SECOND_TURN" in text:
                second_started.set()
            elif "FIRST_TURN" in text:
                first_started.set()
                assert release_first.wait(timeout=2)
            return _pipeline("external_api")

    first_payload = {
        **_chat_request(),
        "messages": [{"role": "user", "content": "FIRST_TURN"}],
    }
    second_payload = {
        **_chat_request(),
        "messages": [{"role": "user", "content": "SECOND_TURN"}],
    }
    headers = {"x-chat-id": "concurrent-context-test"}

    with (
        _chat_dependencies(
            route="external_api",
            local=local,
            external=external,
        ),
        patch(
            "server.api.routes.proxy.PrivacyRouter",
            return_value=ControlledRouter(),
        ),
        patch("server.api.routes.proxy.get_cache", return_value=cache),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first = executor.submit(
            client.post,
            "/v1/chat/completions",
            json=first_payload,
            headers=headers,
        )
        assert first_started.wait(timeout=2)
        second = executor.submit(
            client.post,
            "/v1/chat/completions",
            json=second_payload,
            headers=headers,
        )
        second_started.wait(timeout=0.25)
        release_first.set()
        responses = [first.result(timeout=2), second.result(timeout=2)]

    assert [response.status_code for response in responses] == [200, 200]
    persisted = next(iter(cache.contexts.values()))
    assert {segment["text"] for segment in persisted} == {
        "FIRST_TURN",
        "SECOND_TURN",
    }


def test_chat_session_context_includes_prior_messages_and_tool_results():
    local = CountingAdapter()
    external = CountingAdapter()
    cache = InMemoryContextCache()
    headers = {"x-chat-id": "chat-context-test"}
    first_payload = _chat_request()
    first_payload["messages"] = [
        {"role": "user", "content": "Project Aurora is confidential"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"project":"Aurora"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "Aurora costs 15 million",
        },
    ]
    second_payload = _chat_request()
    second_payload["messages"] = [{"role": "user", "content": "Can I send it to a vendor?"}]

    with (
        _chat_dependencies(
            route="external_api",
            local=local,
            external=external,
        ) as (router, _),
        patch("server.api.routes.proxy.get_cache", return_value=cache),
    ):
        first = client.post(
            "/v1/chat/completions",
            json=first_payload,
            headers=headers,
        )
        second = client.post(
            "/v1/chat/completions",
            json=second_payload,
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    analyzed = router.process.call_args_list[1].args[0]
    assert analyzed.count("Project Aurora is confidential") == 1
    assert analyzed.count('{"project":"Aurora"}') == 1
    assert analyzed.count("Aurora costs 15 million") == 1
    assert analyzed.count("Can I send it to a vendor?") == 1


def test_responses_session_context_includes_prior_input_and_instructions():
    local = CountingAdapter()
    external = CountingAdapter()
    cache = InMemoryContextCache()
    headers = {"x-chat-id": "responses-context-test"}
    first_payload = _responses_request()
    first_payload.update(
        {
            "instructions": "Never disclose Project Aurora",
            "input": "Aurora costs 15 million",
        }
    )
    second_payload = _responses_request()
    second_payload["input"] = "Summarize it for a vendor"

    with (
        _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ) as (router, _),
        patch("server.api.routes.responses.get_cache", return_value=cache),
    ):
        first = client.post(
            "/v1/responses",
            json=first_payload,
            headers=headers,
        )
        second = client.post(
            "/v1/responses",
            json=second_payload,
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    analyzed = router.process.call_args_list[1].args[0]
    assert analyzed.count("Never disclose Project Aurora") == 1
    assert analyzed.count("Aurora costs 15 million") == 1
    assert analyzed.count("Summarize it for a vendor") == 1


def test_chat_session_context_is_isolated_by_api_key():
    local = CountingAdapter()
    external = CountingAdapter()
    cache = InMemoryContextCache()
    headers = {"x-chat-id": "shared-client-chat-id"}

    async def auth_for_first_key() -> str:
        return "api-key-1"

    async def auth_for_second_key() -> str:
        return "api-key-2"

    with (
        _chat_dependencies(
            route="external_api",
            local=local,
            external=external,
        ) as (router, _),
        patch("server.api.routes.proxy.get_cache", return_value=cache),
    ):
        try:
            app.dependency_overrides[require_auth] = auth_for_first_key
            first = client.post(
                "/v1/chat/completions",
                json={
                    **_chat_request(),
                    "messages": [{"role": "user", "content": "Tenant one confidential"}],
                },
                headers=headers,
            )
            app.dependency_overrides[require_auth] = auth_for_second_key
            second = client.post(
                "/v1/chat/completions",
                json={
                    **_chat_request(),
                    "messages": [{"role": "user", "content": "Tenant two request"}],
                },
                headers=headers,
            )
        finally:
            app.dependency_overrides[require_auth] = _mock_auth

    assert first.status_code == 200
    assert second.status_code == 200
    second_analysis = router.process.call_args_list[1].args[0]
    assert "Tenant one confidential" not in second_analysis
    assert "Tenant two request" in second_analysis
    assert len(cache.contexts) == 2


def test_chat_response_does_not_echo_prior_only_sensitive_context():
    local = CountingAdapter()
    external = CountingAdapter()
    cache = InMemoryContextCache()
    headers = {"x-chat-id": "chat-metadata-test"}

    with (
        _chat_dependencies(
            route="external_api",
            local=local,
            external=external,
            requires_masking=True,
        ),
        patch("server.api.routes.proxy.get_cache", return_value=cache),
    ):
        first = client.post(
            "/v1/chat/completions",
            json=_chat_request(),
            headers=headers,
        )
        second = client.post(
            "/v1/chat/completions",
            json={
                **_chat_request(),
                "messages": [{"role": "user", "content": "Follow up"}],
            },
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "SOURCE_SENTINEL" not in second.text


def test_responses_response_does_not_echo_prior_only_sensitive_context():
    local = CountingAdapter()
    external = CountingAdapter()
    cache = InMemoryContextCache()
    headers = {"x-chat-id": "responses-metadata-test"}

    with (
        _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
            requires_masking=True,
        ),
        patch("server.api.routes.responses.get_cache", return_value=cache),
    ):
        first = client.post(
            "/v1/responses",
            json=_responses_request(),
            headers=headers,
        )
        second = client.post(
            "/v1/responses",
            json={
                **_responses_request(),
                "input": "Follow up",
            },
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "SOURCE_SENTINEL" not in second.text


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        ("/v1/chat/completions", _chat_request()),
        ("/v1/responses", _responses_request()),
    ],
)
def test_conversation_id_length_is_bounded(route: str, payload: dict[str, object]):
    response = client.post(
        route,
        json=payload,
        headers={"x-chat-id": "x" * 513},
    )

    assert response.status_code == 400
    assert "between 1 and 512 UTF-8 bytes" in response.text


def _decode_sse_events(response) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in response.text.split("\n\n"):
        lines = block.splitlines()
        if len(lines) != 2 or not lines[0].startswith("event: "):
            continue
        events.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return events


def test_responses_success_matches_openresponses_resource_contract():
    local = CountingAdapter()
    external = CountingAdapter()
    payload = _responses_request()

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    body = response.json()
    required = {
        "id",
        "object",
        "created_at",
        "completed_at",
        "status",
        "incomplete_details",
        "model",
        "previous_response_id",
        "instructions",
        "output",
        "error",
        "tools",
        "tool_choice",
        "truncation",
        "parallel_tool_calls",
        "text",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "top_logprobs",
        "temperature",
        "reasoning",
        "usage",
        "max_output_tokens",
        "max_tool_calls",
        "store",
        "background",
        "service_tier",
        "metadata",
        "safety_identifier",
        "prompt_cache_key",
    }
    assert required <= body.keys()
    assert body["error"] is None
    assert body["output"][0]["status"] == "completed"
    assert body["output"][0]["content"][0]["annotations"] == []
    assert body["output"][0]["content"][0]["logprobs"] == []
    assert body["usage"]["input_tokens_details"]["cached_tokens"] == 0
    assert body["usage"]["output_tokens_details"]["reasoning_tokens"] == 0


def test_responses_are_encrypted_at_rest_and_expire():
    local = CountingAdapter()
    external = CountingAdapter()
    init_db()
    payload = _responses_request()

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        created = client.post("/v1/responses", json=payload)

    assert created.status_code == 200
    body = created.json()
    session = get_session()
    stored = None
    try:
        stored = session.get(StoredResponse, body["id"])
        assert stored is not None
        assert stored.storage_encrypted is True
        assert json.dumps(body, ensure_ascii=False) != stored.output_json
        assert json.loads(decrypt_field(stored.output_json)) == body
        assert stored.expires_at is not None
        assert stored.created_at < stored.expires_at
        assert (stored.expires_at - stored.created_at).total_seconds() <= 24 * 60 * 60

        fetched = client.get(f"/v1/responses/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == body

        continuation_payload = _responses_request()
        continuation_payload.update(
            {
                "previous_response_id": body["id"],
                "input": "Continue from the encrypted response",
                "store": False,
            }
        )
        with _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ):
            continuation = client.post("/v1/responses", json=continuation_payload)
        assert continuation.status_code == 200

        stored.expires_at = stored.created_at
        session.add(stored)
        session.commit()
        assert client.get(f"/v1/responses/{body['id']}").status_code == 404
        with _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ):
            expired_continuation = client.post(
                "/v1/responses",
                json=continuation_payload,
            )
        assert expired_continuation.status_code == 400
        assert expired_continuation.json()["error"]["code"] == "previous_response_not_found"
    finally:
        if stored is not None:
            session.delete(stored)
            session.commit()
        session.close()


def test_responses_stream_emits_schema_complete_event_envelopes():
    local = CountingAdapter()
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = True

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    events = _decode_sse_events(response)
    assert response.status_code == 200
    assert events
    assert [data["sequence_number"] for _, data in events] == list(range(len(events)))
    assert all(data["type"] == event for event, data in events)
    assert [event for event, _ in events[:2]] == [
        "response.created",
        "response.in_progress",
    ]
    created = next(data for event, data in events if event == "response.created")
    completed = next(data for event, data in events if event == "response.completed")
    assert created["response"]["status"] == "in_progress"
    assert completed["response"]["status"] == "completed"
    assert completed["response"]["store"] is True


def test_responses_compaction_is_opaque_replayable_and_owner_bound():
    source = "Remember the code word cobalt."

    async def owner_a() -> str:
        return "owner-a"

    async def owner_b() -> str:
        return "owner-b"

    try:
        app.dependency_overrides[require_auth] = owner_a
        compact = client.post(
            "/v1/responses/compact",
            json={
                "model": "privacy-router/external-model",
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": source}],
                    }
                ],
            },
        )
        assert compact.status_code == 200
        compact_body = compact.json()
        compact_item = compact_body["output"][0]
        assert compact_item["type"] == "compaction"
        assert source not in compact_item["encrypted_content"]
        assert source not in compact.text

        local = CountingAdapter()
        external = CountingAdapter()
        continuation = {
            "model": "privacy-router/external-model",
            "input": [
                compact_item,
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "What was it?"}],
                },
            ],
        }
        with _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ):
            replay = client.post("/v1/responses", json=continuation)
        assert replay.status_code == 200
        assert source in json.dumps(external.calls)

        app.dependency_overrides[require_auth] = owner_b
        rejected = client.post("/v1/responses", json=continuation)
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "invalid_compaction"
    finally:
        app.dependency_overrides[require_auth] = _mock_auth


def test_responses_websocket_supports_sequential_response_create_turns():
    local = CountingAdapter()
    external = CountingAdapter()

    def receive_turn(websocket) -> dict[str, object]:
        while True:
            event = websocket.receive_json()
            if event["type"] in {"response.completed", "response.failed"}:
                return event

    with (
        _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ),
        client.websocket_connect(
            "/v1/responses",
            headers={"Authorization": "Bearer test"},
        ) as websocket,
    ):
        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "input": "First turn",
                "store": True,
            }
        )
        first = receive_turn(websocket)
        first_id = first["response"]["id"]

        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "previous_response_id": first_id,
                "input": "Second turn",
                "store": True,
            }
        )
        second = receive_turn(websocket)

    assert first["type"] == "response.completed"
    assert second["type"] == "response.completed"
    assert second["response"]["previous_response_id"] == first_id


def test_responses_adds_default_strict_flag_to_function_tools():
    local = CountingAdapter()
    external = CountingAdapter()
    payload = _responses_request()
    payload["tools"] = [
        {
            "type": "function",
            "name": "get_weather",
            "parameters": {"type": "object"},
        }
    ]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert response.json()["tools"] == [
        {
            "type": "function",
            "name": "get_weather",
            "description": None,
            "parameters": {"type": "object"},
            "strict": False,
        }
    ]


def test_responses_websocket_uses_schema_complete_error_event():
    local = CountingAdapter()
    external = CountingAdapter()

    with (
        _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ),
        client.websocket_connect(
            "/v1/responses",
            headers={"Authorization": "Bearer test"},
        ) as websocket,
    ):
        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "previous_response_id": "resp_missing",
                "input": "Continue",
                "store": False,
            }
        )
        event = websocket.receive_json()

    assert event == {
        "type": "error",
        "status": 400,
        "error": {
            "type": "invalid_request_error",
            "code": "previous_response_not_found",
            "message": "The previous response was not found",
            "param": "previous_response_id",
        },
    }


def test_responses_websocket_evicts_volatile_parent_after_failed_continuation():
    local = CountingAdapter()
    external = CountingAdapter()

    def receive_terminal(websocket) -> dict[str, object]:
        while True:
            event = websocket.receive_json()
            if event["type"] in {"response.completed", "response.failed", "error"}:
                return event

    with (
        _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ),
        client.websocket_connect(
            "/v1/responses",
            headers={"Authorization": "Bearer test"},
        ) as websocket,
    ):
        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "input": "First turn",
                "store": False,
            }
        )
        first = receive_terminal(websocket)
        first_id = first["response"]["id"]

        external.error = TimeoutError("provider timed out")
        external.failures = 100
        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "previous_response_id": first_id,
                "input": "Fail this continuation",
                "store": False,
            }
        )
        failed = receive_terminal(websocket)

        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "previous_response_id": first_id,
                "input": "Retry stale parent",
                "store": False,
            }
        )
        retry = receive_terminal(websocket)

    assert failed["type"] == "response.failed"
    assert retry["type"] == "error"
    assert retry["error"]["code"] == "previous_response_not_found"


def test_responses_websocket_rejects_unmatched_function_output_and_evicts_parent():
    local = CountingAdapter()
    external = CountingAdapter()

    def receive_terminal(websocket) -> dict[str, object]:
        while True:
            event = websocket.receive_json()
            if event["type"] in {"response.completed", "response.failed", "error"}:
                return event

    with (
        _responses_dependencies(
            route="external_api",
            local=local,
            external=external,
        ),
        client.websocket_connect(
            "/v1/responses",
            headers={"Authorization": "Bearer test"},
        ) as websocket,
    ):
        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "input": "First turn",
                "store": False,
            }
        )
        first = receive_terminal(websocket)
        first_id = first["response"]["id"]

        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "previous_response_id": first_id,
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": "call_missing",
                        "output": "No matching function call exists.",
                    }
                ],
                "store": False,
            }
        )
        failed = receive_terminal(websocket)

        websocket.send_json(
            {
                "type": "response.create",
                "model": "privacy-router/external-model",
                "previous_response_id": first_id,
                "input": "Retry stale parent",
                "store": False,
            }
        )
        retry = receive_terminal(websocket)

    assert failed["type"] == "error"
    assert failed["error"]["code"] == "invalid_function_call_output"
    assert retry["type"] == "error"
    assert retry["error"]["code"] == "previous_response_not_found"
    assert len(external.calls) == 1


def test_litellm_adapter_does_not_print_tool_payloads(capsys):
    adapter = LiteLLMAdapter()
    secret = "SCHEMA_SECRET_SENTINEL"

    with patch(
        "server.adapters.base.litellm.completion",
        return_value=_completion(),
    ):
        adapter.call(
            "test/model",
            [{"role": "user", "content": "hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": secret,
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_litellm_adapter_supplies_key_for_unauthenticated_local_endpoint():
    adapter = LiteLLMAdapter()

    with (
        patch.object(adapter, "get_api_key", return_value=""),
        patch(
            "server.adapters.base.litellm.completion",
            return_value=_completion(),
        ) as completion,
    ):
        adapter.call(
            "openai/local-model",
            [{"role": "user", "content": "hello"}],
            api_base="http://127.0.0.1:8011/v1",
        )

    assert completion.call_args.kwargs["api_key"] == "not-needed"


def test_litellm_adapter_does_not_supply_dummy_key_to_remote_endpoint():
    adapter = LiteLLMAdapter()

    with (
        patch.object(adapter, "get_api_key", return_value=""),
        patch(
            "server.adapters.base.litellm.completion",
            return_value=_completion(),
        ) as completion,
    ):
        adapter.call(
            "openai/remote-model",
            [{"role": "user", "content": "hello"}],
            api_base="https://models.example.com/v1",
        )

    assert completion.call_args.kwargs["api_key"] is None


def test_responses_accepts_null_optional_sampling_fields():
    local = CountingAdapter()
    external = KeywordCapturingAdapter()
    payload = _responses_request()
    payload.update(
        {
            "temperature": None,
            "top_p": None,
            "presence_penalty": None,
            "frequency_penalty": None,
            "top_logprobs": None,
            "parallel_tool_calls": None,
            "truncation": None,
        }
    )

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["temperature"] == 1.0
    assert body["top_p"] == 1.0
    assert body["presence_penalty"] == 0.0
    assert body["frequency_penalty"] == 0.0
    assert body["top_logprobs"] == 0
    assert body["parallel_tool_calls"] is True
    assert body["truncation"] == "disabled"


@pytest.mark.parametrize(
    "override",
    [
        {"temperature": "hot"},
        {"temperature": 10**400},
        {"top_p": 1.1},
        {"presence_penalty": -2.1},
        {"frequency_penalty": 2.1},
        {"top_logprobs": 1.5},
        {"max_output_tokens": 0},
        {"parallel_tool_calls": "false"},
        {"truncation": "middle"},
    ],
)
def test_responses_rejects_invalid_generation_options(override):
    local = CountingAdapter()
    external = CountingAdapter()
    payload = _responses_request()
    payload.update(override)

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert local.calls == []
    assert external.calls == []


def test_responses_forwards_supported_generation_options():
    local = CountingAdapter()
    external = KeywordCapturingAdapter()
    payload = _responses_request()
    payload.update(
        {
            "temperature": 0.2,
            "max_output_tokens": 123,
            "top_p": 0.8,
            "presence_penalty": -0.5,
            "frequency_penalty": 0.5,
            "parallel_tool_calls": False,
            "top_logprobs": 4,
        }
    )

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    call = external.keyword_calls[0]
    assert call["top_p"] == 0.8
    assert call["presence_penalty"] == -0.5
    assert call["frequency_penalty"] == 0.5
    assert call["parallel_tool_calls"] is False
    assert call["top_logprobs"] == 4
    assert call["logprobs"] is True
    assert external.positional_calls[0] == (0.2, 123)
    assert response.json()["temperature"] == 0.2


@pytest.mark.parametrize("stream", [False, True])
def test_responses_retries_text_only_when_local_model_rejects_media(stream):
    local = MediaRejectingAdapter()
    external = CountingAdapter()
    payload = {
        "model": "privacy-router/external-model",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe this image."},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,iVBORw0KGgo=",
                    },
                ],
            }
        ],
        "stream": stream,
    }

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert len(local.calls) == 2
    assert external.calls == []
    assert "data:image/png" in json.dumps(local.calls[0])
    fallback = json.dumps(local.calls[1])
    assert "data:image/png" not in fallback
    assert "could not inspect" in fallback
    if stream:
        events = _decode_sse_events(response)
        completed = next(data for name, data in events if name == "response.completed")
        body = completed["response"]
    else:
        body = response.json()
    assert body["metadata"]["privacy_router"]["route"] == "local_api"
    assert body["metadata"]["privacy_router"]["policy_action"] == "block"


def test_responses_rejects_input_image_without_url_before_privacy_analysis():
    local = CountingAdapter()
    external = CountingAdapter()
    payload = {
        "model": "privacy-router/external-model",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_image", "image_url": None}],
            }
        ],
    }

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "input_image.image_url must be a non-empty string"
    assert local.calls == []
    assert external.calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_chat_retries_text_only_when_local_model_rejects_media(stream):
    local = MediaRejectingAdapter()
    external = CountingAdapter()
    payload = _chat_request()
    payload["messages"] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image."},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                },
            ],
        }
    ]
    payload["stream"] = stream

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert len(local.calls) == 2
    assert external.calls == []
    assert "data:image/png" in json.dumps(local.calls[0])
    fallback = json.dumps(local.calls[1])
    assert "data:image/png" not in fallback
    assert "could not inspect" in fallback
    if not stream:
        meta = response.json()["privacy_router"]
        assert meta["route"] == "local_api"
        assert meta["policy_action"] == "block"


def test_responses_ignores_media_shape_nested_in_text_part_metadata():
    local = CountingAdapter()
    external = CountingAdapter()
    payload = {
        "model": "privacy-router/external-model",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Describe the serialized example.",
                        "metadata": {
                            "type": "input_image",
                            "image_url": "not-an-attachment",
                        },
                    }
                ],
            }
        ],
    }

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert local.calls == []
    assert len(external.calls) == 1


def _declared_send_value_tool() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "send_value",
            "description": "Send one value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
        },
    }


def _declared_responses_send_value_tool() -> dict[str, object]:
    return {
        "type": "function",
        "name": "send_value",
        "description": "Send one value.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        },
    }


@pytest.mark.parametrize("stream", [False, True])
def test_chat_local_output_rejects_undeclared_tool_name_before_release(stream):
    generated_name = "undeclared_sensitive_sink"

    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[_tool_call("{}", name=generated_name)],
        )

    local = (
        CountingAdapter(stream_factory=tool_stream)
        if stream
        else ToolAdapter("{}", content="FIRST_CONTENT", name=generated_name)
    )
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="local_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == (200 if stream else 502)
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert generated_name not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert len(local.calls) == 1
    assert external.calls == []


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("allow_sensitive", [False, True])
def test_responses_local_output_rejects_sensitive_tool_id_before_release(
    stream,
    allow_sensitive,
):
    generated_id = "MODEL_OUTPUT_PRIVATE_CALL_ID"

    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[_tool_call("{}", call_id=generated_id)],
        )

    local = (
        CountingAdapter(stream_factory=tool_stream)
        if stream
        else ToolAdapter("{}", content="FIRST_CONTENT", call_id=generated_id)
    )
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_responses_send_value_tool()]
    if allow_sensitive:
        payload["privacy_router"] = {"allow_sensitive_tool_arguments": True}

    with _responses_dependencies(
        route="local_api",
        local=local,
        external=external,
    ) as (router, _):

        def analyze(text: str):
            if generated_id in text:
                return _pipeline(
                    "local_api",
                    True,
                    [_extraction_record(generated_id, "PRIVATE_CALL_ID")],
                )
            return _pipeline("local_api")

        router.process.side_effect = analyze
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == (200 if stream else 502)
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert generated_id not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert len(local.calls) == 1
    assert external.calls == []


def test_chat_local_stream_rejects_non_function_tool_type_before_release():
    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[_tool_call("{}", call_type="custom")],
        )

    local = CountingAdapter(stream_factory=tool_stream)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = True
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="local_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert '"reason": "hydration_failed"' in response.text
    assert "custom" not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert len(local.calls) == 1
    assert external.calls == []


@pytest.mark.parametrize("index", ["MODEL_OUTPUT_INDEX", -1, True, 7])
def test_chat_local_stream_rejects_malformed_tool_index_before_release(index):
    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[_tool_call("{}", index=index)],
        )

    local = CountingAdapter(stream_factory=tool_stream)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = True
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="local_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert '"reason": "hydration_failed"' in response.text
    assert "MODEL_OUTPUT_INDEX" not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert len(local.calls) == 1
    assert external.calls == []


@pytest.mark.parametrize("index", ["MODEL_OUTPUT_INDEX", 7])
def test_responses_local_stream_rejects_malformed_tool_index_before_release(index):
    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[_tool_call("{}", index=index)],
        )

    local = CountingAdapter(stream_factory=tool_stream)
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = True
    payload["tools"] = [_declared_responses_send_value_tool()]

    with _responses_dependencies(
        route="local_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert '"reason": "hydration_failed"' in response.text
    assert "MODEL_OUTPUT_INDEX" not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert len(local.calls) == 1
    assert external.calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_chat_external_tool_arguments_remain_raw_without_masking_contract(stream):
    raw_arguments = '{ "value" : "\\u0041" }'

    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    payload = _chat_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    if stream:
        chunks = [
            json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: {")
        ]
        tool_chunk = next(chunk for chunk in chunks if chunk["choices"][0]["delta"].get("tool_calls"))
        arguments = tool_chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
    else:
        arguments = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert arguments == raw_arguments


@pytest.mark.parametrize("stream", [False, True])
def test_responses_external_tool_arguments_remain_raw_without_masking_contract(stream):
    raw_arguments = '{ "value" : "\\u0041" }'

    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    payload = _responses_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_responses_send_value_tool()]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    if stream:
        events = _decode_sse_events(response)
        arguments = next(
            data["arguments"] for event, data in events if event == "response.function_call_arguments.done"
        )
    else:
        arguments = response.json()["output"][0]["arguments"]
    assert arguments == raw_arguments


@pytest.mark.parametrize("stream", [False, True])
def test_chat_external_tool_arguments_reject_invalid_json_without_masking_contract(stream):
    raw_arguments = '{"value":NaN}'

    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    payload = _chat_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == (200 if stream else 502)
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert "NaN" not in response.text


@pytest.mark.parametrize("stream", [False, True])
def test_responses_external_tool_arguments_reject_invalid_json_without_masking_contract(stream):
    raw_arguments = '{"value":NaN}'

    def tool_stream():
        yield _stream_part("", tool_calls=[_tool_call(raw_arguments)])

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream) if stream else ToolAdapter(raw_arguments)
    payload = _responses_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_responses_send_value_tool()]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == (200 if stream else 502)
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert "NaN" not in response.text


def test_chat_local_output_rejects_duplicate_parallel_tool_call_ids():
    local = MultiToolAdapter(
        [
            _tool_call('{"value":"one"}', call_id="duplicate"),
            _tool_call('{"value":"two"}', call_id="duplicate", index=1),
        ]
    )
    external = CountingAdapter()
    payload = _chat_request()
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 502
    assert response.json()["error"]["reason"] == "hydration_failed"
    assert "duplicate" not in response.text
    assert len(local.calls) == 1
    assert external.calls == []


def test_responses_local_output_rejects_duplicate_parallel_call_ids():
    local = ResponsesToolAdapter(
        [
            SimpleNamespace(
                type="function_call",
                id="item_1",
                call_id="duplicate",
                name="send_value",
                arguments='{"value":"one"}',
            ),
            SimpleNamespace(
                type="function_call",
                id="item_2",
                call_id="duplicate",
                name="send_value",
                arguments='{"value":"two"}',
            ),
        ]
    )
    external = CountingAdapter()
    payload = _responses_request()
    payload["tools"] = [_declared_responses_send_value_tool()]

    with _responses_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 502
    assert response.json()["error"]["reason"] == "hydration_failed"
    assert "duplicate" not in response.text
    assert len(local.calls) == 1
    assert external.calls == []


def test_chat_external_stream_rejects_duplicate_parallel_tool_call_ids():
    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[
                _tool_call('{"value":"one"}', call_id="duplicate", index=0),
                _tool_call('{"value":"two"}', call_id="duplicate", index=1),
            ],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream)
    payload = _chat_request()
    payload["stream"] = True
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert '"reason": "hydration_failed"' in response.text
    assert "FIRST_CONTENT" not in response.text
    assert "duplicate" not in response.text
    assert local.calls == []
    assert len(external.calls) == 1


def test_responses_external_stream_rejects_duplicate_parallel_call_ids():
    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[
                _tool_call(
                    '{"value":"one"}',
                    call_id="item_1",
                    response_call_id="duplicate",
                    index=0,
                ),
                _tool_call(
                    '{"value":"two"}',
                    call_id="item_2",
                    response_call_id="duplicate",
                    index=1,
                ),
            ],
        )

    local = CountingAdapter()
    external = CountingAdapter(stream_factory=tool_stream)
    payload = _responses_request()
    payload["stream"] = True
    payload["tools"] = [_declared_responses_send_value_tool()]

    with _responses_dependencies(route="external_api", local=local, external=external):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    assert '"reason": "hydration_failed"' in response.text
    assert "response.completed" not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert "duplicate" not in response.text
    assert local.calls == []
    assert len(external.calls) == 1


def test_chat_stream_assembles_split_function_type_before_release():
    def tool_stream():
        yield _stream_part(
            "",
            tool_calls=[
                _tool_call(
                    '{"value":',
                    call_id="call_",
                    name="send_",
                    call_type="fun",
                )
            ],
        )
        yield _stream_part(
            "",
            tool_calls=[
                _tool_call(
                    '"ok"}',
                    call_id="1",
                    name="value",
                    call_type="ction",
                )
            ],
        )

    local = CountingAdapter(stream_factory=tool_stream)
    external = CountingAdapter()
    payload = _chat_request()
    payload["stream"] = True
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    chunks = [
        json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: {")
    ]
    tool_chunk = next(chunk for chunk in chunks if chunk["choices"][0]["delta"].get("tool_calls"))
    tool_call = tool_chunk["choices"][0]["delta"]["tool_calls"][0]
    assert tool_call["id"] == "call_1"
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == "send_value"
    assert json.loads(tool_call["function"]["arguments"]) == {"value": "ok"}
    assert len(local.calls) == 1
    assert external.calls == []


def test_responses_stream_explicit_call_id_replaces_earlier_id_fallback():
    def tool_stream():
        yield _stream_part(
            "",
            tool_calls=[
                _tool_call(
                    '{"value":',
                    call_id="item_",
                    name="send_",
                    call_type="fun",
                )
            ],
        )
        yield _stream_part(
            "",
            tool_calls=[
                _tool_call(
                    '"ok"}',
                    call_id="1",
                    response_call_id="call_",
                    name="value",
                    call_type="ction",
                )
            ],
        )
        yield _stream_part(
            "",
            tool_calls=[
                _tool_call(
                    "",
                    call_id=None,
                    response_call_id="1",
                    name="",
                    call_type="function",
                )
            ],
        )

    local = CountingAdapter(stream_factory=tool_stream)
    external = CountingAdapter()
    payload = _responses_request()
    payload["stream"] = True
    payload["tools"] = [_declared_responses_send_value_tool()]

    with _responses_dependencies(route="local_api", local=local, external=external):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == 200
    events = _decode_sse_events(response)
    item_added = next(
        payload
        for event, payload in events
        if event == "response.output_item.added" and payload["item"]["type"] == "function_call"
    )
    arguments_done = next(payload for event, payload in events if event == "response.function_call_arguments.done")
    assert item_added["item"]["id"] == "item_1"
    assert item_added["item"]["call_id"] == "call_1"
    assert item_added["item"]["name"] == "send_value"
    assert json.loads(arguments_done["arguments"]) == {"value": "ok"}
    assert len(local.calls) == 1
    assert external.calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_chat_external_output_rejects_undeclared_tool_name_before_release(stream):
    generated_name = "undeclared_external_sink"

    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[_tool_call("{}", name=generated_name)],
        )

    local = CountingAdapter()
    external = (
        CountingAdapter(stream_factory=tool_stream)
        if stream
        else ToolAdapter("{}", content="FIRST_CONTENT", name=generated_name)
    )
    payload = _chat_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_send_value_tool()]

    with _chat_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == (200 if stream else 502)
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert generated_name not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert len(external.calls) == 1
    assert local.calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_responses_external_output_rejects_undeclared_tool_name_before_release(stream):
    generated_name = "undeclared_external_sink"

    def tool_stream():
        yield _stream_part(
            "FIRST_CONTENT",
            tool_calls=[_tool_call("{}", name=generated_name)],
        )

    local = CountingAdapter()
    external = (
        CountingAdapter(stream_factory=tool_stream)
        if stream
        else ToolAdapter("{}", content="FIRST_CONTENT", name=generated_name)
    )
    payload = _responses_request()
    payload["stream"] = stream
    payload["tools"] = [_declared_responses_send_value_tool()]

    with _responses_dependencies(
        route="external_api",
        local=local,
        external=external,
    ):
        response = client.post("/v1/responses", json=payload)

    assert response.status_code == (200 if stream else 502)
    if stream:
        assert '"reason": "hydration_failed"' in response.text
    else:
        assert response.json()["error"]["reason"] == "hydration_failed"
    assert generated_name not in response.text
    assert "FIRST_CONTENT" not in response.text
    assert len(external.calls) == 1
    assert local.calls == []
