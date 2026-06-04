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

    # ── Decision table ───────────────────────────────────────────────────────

    _ACTIONS: dict[str, RouteResult] = {
        "allow": RouteResult(
            endpoint="external_api",
            requires_masking=False,
            description="민감 정보 없음 — 외부 API로 직접 전송",
        ),
        "mask_and_send": RouteResult(
            endpoint="external_api",
            requires_masking=True,
            description="민감 정보 마스킹 후 외부 API로 전송, 응답 재수화",
        ),
        "prompt_user": RouteResult(
            endpoint="prompt",
            requires_masking=False,
            description="마스킹 시 질문 의미 상실 — 사용자 확인 필요",
        ),
        "block": RouteResult(
            endpoint="blocked",
            requires_masking=False,
            description="민감 정보 직접 노출 위험 — 완전 차단",
        ),
        "process_locally": RouteResult(
            endpoint="local_api",
            requires_masking=False,
            description="민감 정보가 핵심 — 로컬 API에서 처리",
        ),
    }

    # ── Public API ───────────────────────────────────────────────────────────

    def resolve(self, policy_action: str) -> RouteResult:
        """Resolve a policy action to a concrete execution path.

        Parameters
        ----------
        policy_action : str
            One of ``"allow"``, ``"mask_and_send"``, or
            ``"process_locally"``.

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
    ) -> None:
        self._router = Router()
        self._extractor_model = extractor_model
        self._judge_model = judge_model

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

        # Phase 1: Extract
        extractor = Extractor(model=self._extractor_model)
        extraction = extractor.extract(text)

        # Phase 2: Judge
        judge = Judge(model=self._judge_model)
        records_dict = [r.model_dump() for r in extraction.records]
        judgment = judge.classify(
            sensitivity=extraction.sensitivity.model_dump(),
            records=records_dict,
            text=text,
        )

        # Phase 3: Route
        route = self._router.resolve(judgment.policy_action)

        return PipelineResult(
            sensitivity=extraction.sensitivity,
            judgment=judgment,
            route=route,
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
