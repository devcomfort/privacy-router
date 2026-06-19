"""Router — Pure execution layer and main orchestrator.

The Router translates the Judge's ``policy_action`` into concrete
execution paths. The :class:`PrivacyRouter` class is the top-level
entry point that orchestrates the full Extractor → Judge → Router
pipeline.

Examples
--------
>>> from agents.router import PrivacyRouter
>>> pr = PrivacyRouter()
>>> result = pr.process("주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.")
>>> result.route.endpoint
'external_api'
"""

from __future__ import annotations

from typing import Any


from .schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    PipelineResult,
    RouteResult,
)


class Router:
    """Execution layer that resolves a policy action into a concrete path.

    No LLM calls — all decisions are already made by the Judge.

    Examples
    --------
    >>> router = Router()
    >>> router.resolve("mask_and_send")
    RouteResult(endpoint='external_api', requires_masking=True, ...)
    """

    # ── Decision table (tool-use style actions) ─────────────────────────

    _ACTIONS: dict[str, RouteResult] = {
        "route_to_external": RouteResult(
            endpoint="external_api",
            requires_masking=False,
            description="민감 정보 없음 — 외부 LLM으로 직접 전송",
        ),
        "route_to_local": RouteResult(
            endpoint="local_api",
            requires_masking=False,
            description="민감 정보가 핵심 — 로컬 LLM으로 처리",
        ),
        "mask_and_send": RouteResult(
            endpoint="external_api",
            requires_masking=True,
            description="모든 레코드 마스킹 후 외부 LLM으로 전송, 응답 재수화",
        ),
        "selective_mask": RouteResult(
            endpoint="external_api",
            requires_masking=True,
            description="비-essential 레코드만 마스킹 후 외부 LLM으로 전송",
        ),
        "prompt_user": RouteResult(
            endpoint="prompt",
            requires_masking=False,
            description="마스킹 시 질문 의미 상실 — 사용자 확인 필요 (409)",
        ),
        "block": RouteResult(
            endpoint="blocked",
            requires_masking=False,
            description="극단적 보안 위험 — 완전 차단",
        ),
    }

    # ── Public API ───────────────────────────────────────────────────────────

    def resolve(self, policy_action: str) -> RouteResult:
        """Resolve a policy action to a concrete execution path.

        Parameters
        ----------
        policy_action : str
            One of ``"route_to_external"``, ``"route_to_local"``,
            ``"mask_and_send"``, ``"selective_mask"``,
            ``"prompt_user"``, or ``"block"``.

        Returns
        -------
        RouteResult
            Concrete endpoint and masking requirements.

        Raises
        ------
        ValueError
            If *policy_action* is not recognised.

        Examples
        --------
        >>> router = Router()
        >>> router.resolve("mask_and_send")
        RouteResult(endpoint='external_api', requires_masking=True, ...)
        """
        if policy_action not in self._ACTIONS:
            raise ValueError(
                f"Unknown policy_action: {policy_action!r}. "
                f"Expected one of: {list(self._ACTIONS.keys())}"
            )
        return self._ACTIONS[policy_action]

    def execute(
        self,
        text: str,
        policy_action: str,
        records: list[dict[str, Any]],
        call_external: callable | None = None,
        call_local: callable | None = None,
    ) -> str:
        """Execute the full routing pipeline.

        Parameters
        ----------
        text : str
            Original input text.
        policy_action : str
            Policy decision from the Judge.
        records : list of dict
            Extraction records for masking.
        call_external : callable or None
            External API callable.
        call_local : callable or None
            Local API callable.

        Returns
        -------
        str
            The LLM response (hydrated if masking was applied).

        Raises
        ------
        ValueError
            If the required callable is missing.

        Examples
        --------
        >>> def fake_llm(text): return f"echo: {text}"
        >>> router = Router()
        >>> router.execute("hello", "allow", [], call_external=fake_llm)
        'echo: hello'
        """
        path = self.resolve(policy_action)

        if path.endpoint == "external_api":
            if call_external is None:
                raise ValueError("call_external is required for external_api")
            if path.requires_masking:
                from agents.masker import Masker

                masker = Masker()
                result = masker.mask(text, records)
                response = call_external(result.masked_text)
                hydrated = masker.hydrate(response, result.contract)
                return hydrated.hydrated_text
            return call_external(text)

        if path.endpoint == "prompt":
            raise ValueError(
                "⚠️ 확인이 필요합니다. X-Privacy-Router-Confirm: true 헤더로 재요청하세요."
            )

        # local_api — original text, no masking
        if path.endpoint == "blocked":
            return "[BLOCKED] 로컬 API가 구성되지 않아 민감 정보를 처리할 수 없습니다."

        # local_api — original text, no masking
        if call_local is None:
            raise ValueError("call_local is required for local_api")
        return call_local(text)


# ── PrivacyRouter (top-level orchestrator) ───────────────────────────────────


class PrivacyRouter:
    """Top-level orchestrator for the full Privacy Router pipeline.

    Chains Extractor → Judge → Router into a single call.

    Parameters
    ----------
    extractor_model : str or None
        Override the Extractor model.
    judge_model : str or None
        Override the Judge model.

    Examples
    --------
    >>> pr = PrivacyRouter()
    >>> result = pr.process("주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.")
    >>> result.sensitivity.is_sensitive
    True
    >>> result.judgment.policy_action
    'mask_and_send'
    """

    def __init__(
        self,
        extractor_model: str | None = None,
        judge_model: str | None = None,
        api_base: str | None = None,
    ) -> None:
        self._router = Router()
        # Resolve from config if not explicitly provided
        try:
            from config import load_config, resolve_model
            cfg = load_config()
            if extractor_model is None:
                extractor_model = cfg.extractor.model
            if api_base is None:
                spec = resolve_model(cfg, extractor_model)
                api_base = spec.api_base
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug("Config loading failed, using defaults: %s", exc)
        self._extractor_model = extractor_model
        self._judge_model = judge_model
        self._api_base = api_base

    # ── Core pipeline ────────────────────────────────────────────────────────

    def process(self, text: str) -> PipelineResult:
        """Run the full pipeline: Extractor → Judge → Router.

        Parameters
        ----------
        text : str
            Raw input text.

        Returns
        -------
        PipelineResult
            Sensitivity assessment, judgment, and routing decision.

        Examples
        --------
        >>> pr = PrivacyRouter()
        >>> result = pr.process("주민등록번호 901212-1234567")
        >>> result.sensitivity.is_sensitive
        True
        """
        from agents.extractor import Extractor
        from agents.judge import Judge

        extractor = Extractor(model=self._extractor_model, api_base=self._api_base)
        extraction = extractor.extract(text)
        records = extraction.records

        # Phase 2: Rule-based Judge
        judge = Judge()
        records_dict = [
            {"category": r.category, "span": r.span, "is_essential": r.is_essential}
            for r in records
        ]
        judgment = judge.classify(
            sensitivity={"is_sensitive": extraction.sensitivity.is_sensitive, "rationale": extraction.sensitivity.rationale},
            records=records_dict,
            text=text,
        )
        policy_action = judgment.policy_action

        mask_indices = (
            list(range(len(records)))
            if policy_action in ("mask_and_send", "selective_mask")
            else []
        )

        # Phase 3: Route
        route = self._router.resolve(policy_action)

        return PipelineResult(
            sensitivity=extraction.sensitivity,
            judgment=judgment,
            route=route,
            records=extraction.records,
            mask_indices=mask_indices,
        )

    # ── LiteLLM-compatible API ───────────────────────────────────────────────

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Process a chat completion request with privacy routing.

        Parameters
        ----------
        request : ChatRequest
            OpenAI-compatible chat request.

        Returns
        -------
        ChatResponse
            OpenAI-compatible response with routing metadata.

        Examples
        --------
        >>> pr = PrivacyRouter()
        >>> req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="hello")])
        >>> resp = pr.chat(req)
        >>> resp.model
        'privacy-router'
        """
        import time
        import uuid

        # Concatenate user messages as the input text
        user_text = " ".join(
            m.content for m in request.messages if m.role == "user"
        )

        # Run the pipeline
        pipeline = self.process(user_text)

        # Build response
        if pipeline.route.endpoint == "local_api":
            content = f"[LOCAL] {pipeline.route.description}"
        elif pipeline.route.requires_masking:
            content = f"[MASKED] {pipeline.route.description}"
        else:
            content = f"[EXTERNAL] {pipeline.route.description}"

        return ChatResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model="privacy-router",
            choices=[
                {
                    "index": 0,
                    "message": ChatMessage(role="assistant", content=content),
                    "finish_reason": "stop",
                }
            ],
            route_result=pipeline.route,
        )


# ── Module-level convenience ─────────────────────────────────────────────────


_DEFAULT_ROUTER: PrivacyRouter | None = None


def process(text: str) -> PipelineResult:
    """One-shot pipeline using a shared :class:`PrivacyRouter` instance.

    Parameters
    ----------
    text : str
        Raw input text.

    Returns
    -------
    PipelineResult
        Complete pipeline result.

    Examples
    --------
    >>> from agents.router import process
    >>> result = process("hello")
    >>> result.route.endpoint
    'external_api'
    """
    global _DEFAULT_ROUTER
    if _DEFAULT_ROUTER is None:
        _DEFAULT_ROUTER = PrivacyRouter()
    return _DEFAULT_ROUTER.process(text)
