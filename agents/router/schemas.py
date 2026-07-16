"""Schemas for the Router package.

Includes routing results and LiteLLM/OpenAI-compatible chat schemas
so the router can serve as a drop-in proxy.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agents.extractor.schemas import ExtractionRecord, Sensitivity
from agents.judge.schemas import Judgment


class RouteResult(BaseModel):
    """Concrete routing result produced by the Router.

    Attributes
    ----------
    endpoint : str
        Target endpoint: ``"external_api"`` or ``"local_api"``.
    requires_masking : bool
        Whether the text must be masked before transmission.
    description : str
        Human-readable description of the chosen path (Korean).

    Examples
    --------
    >>> r = RouteResult(endpoint="external_api", requires_masking=True, description="마스킹 후 전송")
    >>> r.endpoint
    'external_api'
    """

    endpoint: str = Field(
        ...,
        description="Target endpoint: 'external_api' or 'local_api'.",
        examples=["external_api", "local_api"],
    )
    requires_masking: bool = Field(
        ...,
        description="Whether masking is required before sending.",
        examples=[True, False],
    )
    description: str = Field(
        ...,
        description="Human-readable description of the routing decision (Korean).",
        examples=["민감 정보 마스킹 후 외부 API로 전송, 응답 재수화"],
    )


class PlaceholderRepairDecision(BaseModel):
    """One candidate replacement for a malformed placeholder token."""

    placeholder: str | None = Field(
        default=None,
        description=(
            "Exact registered placeholder that the observed token represents, or null when the mapping is ambiguous."
        ),
    )


# ── LiteLLM / OpenAI-compatible schemas ──────────────────────────────────────


class ChatMessage(BaseModel):
    """OpenAI-compatible chat message.

    Attributes
    ----------
    role : str
        One of ``"system"``, ``"user"``, or ``"assistant"``.
    content : str
        The message content.

    Examples
    --------
    >>> m = ChatMessage(role="user", content="hello")
    >>> m.role
    'user'
    """

    role: str = Field(
        ...,
        description="Message role.",
        examples=["user"],
    )
    content: str = Field(
        ...,
        description="Message content.",
        examples=["주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."],
    )


class ChatRequest(BaseModel):
    """OpenAI-compatible chat completions request.

    Attributes
    ----------
    model : str, optional
        Model to use. Defaults to ``"auto"`` (routed by Privacy Router).
    messages : list of ChatMessage
        Conversation messages.
    temperature : float or None, optional
        Sampling temperature (0.0 ~ 2.0).
    max_tokens : int or None, optional
        Maximum completion tokens.
    stream : bool, optional
        Whether to stream the response.

    Examples
    --------
    >>> req = ChatRequest(model="auto", messages=[ChatMessage(role="user", content="hello")])
    >>> req.model
    'auto'
    """

    model: str = Field(
        default="auto",
        description="Model identifier, or 'auto' for Privacy Router routing.",
        examples=["auto", "openrouter/google/gemini-3.1-flash-lite"],
    )
    messages: list[ChatMessage] = Field(
        ...,
        description="Conversation messages.",
        examples=[[ChatMessage(role="user", content="hello")]],
    )
    temperature: float | None = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature.",
        examples=[0.7],
    )
    max_tokens: int | None = Field(
        default=256,
        ge=1,
        description="Maximum tokens to generate.",
        examples=[256],
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream the response.",
        examples=[False],
    )


class ChatChoice(BaseModel):
    """A single completion choice.

    Attributes
    ----------
    index : int
        Choice index.
    message : ChatMessage
        The response message.
    finish_reason : str
        Reason the generation stopped.

    Examples
    --------
    >>> c = ChatChoice(index=0, message=ChatMessage(role="assistant", content="ok"), finish_reason="stop")
    >>> c.index
    0
    """

    index: int = Field(default=0, description="Choice index.", examples=[0])
    message: ChatMessage = Field(
        ..., description="Response message.", examples=[ChatMessage(role="assistant", content="처리 완료")]
    )
    finish_reason: str = Field(default="stop", description="Completion stop reason.", examples=["stop"])


class ChatUsage(BaseModel):
    """Token usage statistics.

    Attributes
    ----------
    prompt_tokens : int
        Tokens in the prompt.
    completion_tokens : int
        Tokens in the completion.
    total_tokens : int
        Total tokens.

    Examples
    --------
    >>> u = ChatUsage(prompt_tokens=150, completion_tokens=80, total_tokens=230)
    >>> u.total_tokens
    230
    """

    prompt_tokens: int = Field(default=0, ge=0, description="Prompt token count.", examples=[150])
    completion_tokens: int = Field(default=0, ge=0, description="Completion token count.", examples=[80])
    total_tokens: int = Field(default=0, ge=0, description="Total token count.", examples=[230])


class ChatResponse(BaseModel):
    """OpenAI-compatible chat completions response.

    Attributes
    ----------
    id : str
        Response identifier.
    object : str
        Always ``"chat.completion"``.
    created : int
        Unix timestamp.
    model : str
        Model used.
    choices : list of ChatChoice
        Completion choices.
    usage : ChatUsage
        Token usage statistics.
    route_result : RouteResult or None, optional
        Privacy Router's routing decision metadata.

    Examples
    --------
    >>> resp = ChatResponse(id="chat-123", created=1717200000, model="privacy-router", choices=[])
    >>> resp.model
    'privacy-router'
    """

    id: str = Field(..., description="Response identifier.", examples=["chatcmpl-abc123"])
    object: str = Field(default="chat.completion", description="Object type.", examples=["chat.completion"])
    created: int = Field(..., description="Unix timestamp of creation.", examples=[1717200000])
    model: str = Field(..., description="Model identifier.", examples=["privacy-router"])
    choices: list[ChatChoice] = Field(..., description="Completion choices.")
    usage: ChatUsage = Field(default_factory=ChatUsage, description="Token usage.")
    route_result: RouteResult | None = Field(
        default=None,
        description="Privacy Router routing metadata.",
        examples=[
            RouteResult(
                endpoint="external_api", requires_masking=True, description="민감 정보 마스킹 후 외부 API로 전송"
            )
        ],
    )


# ── Pipeline result ─────────────────────────────────────────────────────────


class PipelineResult(BaseModel):
    """Full result from the Privacy Router pipeline.

    Attributes
    ----------
    sensitivity : Sensitivity
        Sensitivity assessment from the Extractor.
    judgment : Judgment
        Policy judgment from the Judge.
    route : RouteResult
        Concrete routing result.
    response : str or None
        Final LLM response text (if execution was performed).

    Examples
    --------
    >>> rr = RouteResult(endpoint="external_api", requires_masking=False, description="안전")
    >>> pr = PipelineResult(sensitivity={"is_sensitive": False, "rationale": "none"}, judgment={"policy_action": "allow"}, route=rr)
    >>> pr.route.endpoint
    'external_api'
    """

    sensitivity: Sensitivity = Field(
        ...,
        description="Sensitivity assessment.",
        examples=[Sensitivity(is_sensitive=True, rationale="주민등록번호 탐지")],
    )
    judgment: Judgment = Field(
        ...,
        description="Policy judgment.",
        examples=[
            Judgment(
                meaningful_after_masking={"is_meaningful_after_masking": True, "rationale": "test"},
                policy_action="selective_mask",
                strategy="마스킹 후 전송",
                rationale="test",
            )
        ],
    )
    route: RouteResult = Field(
        ...,
        description="Routing result.",
        examples=[RouteResult(endpoint="external_api", requires_masking=True, description="마스킹 후 전송")],
    )
    response: str | None = Field(default=None, description="Final LLM response text.", examples=["이메일 초안: ..."])
    records: list[ExtractionRecord] = Field(
        default_factory=list,
        description="Extraction records with detection_type and reasoning.",
        examples=[
            [
                ExtractionRecord(
                    category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567", confidence=0.98, start=7, end=21
                )
            ]
        ],
    )
    per_record_eval: dict | None = Field(
        default=None,
        description="PerRecordEvaluation result (if evaluator ran).",
    )
    mask_indices: list[int] = Field(
        default_factory=list,
        description="Indices of records to mask for the selective_mask action.",
    )
