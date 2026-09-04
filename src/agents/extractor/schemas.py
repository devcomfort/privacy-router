"""Schemas for the Extractor package.

All Pydantic models used by the Extractor. Internal models are
prefixed with an underscore and excluded from the barrel.

Notes:
-----
Each model uses pydantic.Field with ``description`` and where
relevant, ``examples`` to fully document the contract.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from contracts.extraction import (  # noqa: F401
    ExtractionRecord,
    ExtractionResult,
    Requiredness,
    Sensitivity,
    redact_extraction_records,
)

# ── Public schemas ───────────────────────────────────────────────────────────




# ── Internal schemas (SLM output contracts) ──────────────────────────────────
# The following are the Pydantic shapes the SLM is asked to produce.
# They are NOT part of the public API.


class _ExtractedItem(BaseModel):
    """Shape the SLM produces for a single span.

    Offsets are computed in post-processing via ``text.find(span)``
    — the SLM is NOT asked to produce character offsets.

    Examples:
    --------
    >>> item = _ExtractedItem(category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567", confidence=0.98)
    """

    category: str = Field(
        ...,
        description="SCREAMING_SNAKE_CASE tag from the closed category list.",
        examples=["RESIDENT_REGISTRATION_NUMBER", "FABRICATION_PROCESS_DECISION"],
    )
    span: str = Field(
        ...,
        description="Exact substring from the input text.",
        examples=["901212-1234567"],
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Detection confidence.",
        examples=[0.98],
    )
    detection_type: str = Field(
        default="contextual",
        description="How this was detected: 'pattern' for fixed formats (RRN, phone), 'contextual' for context-dependent sensitivity.",
        examples=["pattern", "contextual"],
    )
    reasoning: str = Field(
        default="",
        description="One sentence explaining WHY this span is sensitive.",
        examples=["주민등록번호는 개인 식별 정보이므로", "미공개 연구 방법론이므로 경쟁사에게 이점이 됨"],
    )
    is_required: Requiredness = Field(
        default_factory=lambda: Requiredness(value=None, reason="not assessed"),
        description="Whether masking this record would preserve the query meaning.",
    )


class _ExtractedOutput(BaseModel):
    """Shape the SLM produces for the complete extraction call.

    Examples:
    --------
    >>> s = Sensitivity(is_sensitive=True, rationale="탐지됨")
    >>> o = _ExtractedOutput(sensitivity=s)
    >>> o.records
    []
    """

    sensitivity: Sensitivity = Field(
        ...,
        description="Sensitivity assessment from the SLM.",
        examples=[Sensitivity(is_sensitive=True, rationale="주민등록번호 탐지")],
    )
    records: list[_ExtractedItem] = Field(
        default_factory=list,
        description="Raw extracted items from the SLM.",
        examples=[[_ExtractedItem(category="RESIDENT_REGISTRATION_NUMBER", span="901212-1234567", confidence=0.98)]],
    )


class _CriticItem(BaseModel):
    """A single missed record from the critic pass."""

    category: str = Field(..., description="SCREAMING_SNAKE_CASE category.")
    span: str = Field(..., description="Exact substring the first pass missed.")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    detection_type: str = Field(default="contextual")
    reasoning: str = Field(default="", description="Why this was missed and why it's sensitive.")
    is_required: Requiredness = Field(
        default_factory=lambda: Requiredness(value=None, reason="not assessed"),
        description="Whether masking this record would preserve the query meaning.",
    )


class CriticOutput(BaseModel):
    """Second-pass critic output — finds what the Extractor missed."""

    found_missed: bool = Field(..., description="True if any sensitive spans were missed.")
    missed_records: list[_CriticItem] = Field(default_factory=list)


class PrivacyEntity(BaseModel):
    """Normalized privacy-relevant entity from one detector run.

    The raw ``span`` is retained for trusted local processing. ``identifier``
    is computed from ``tag`` and the occurrence-specific ``uid`` and is never
    persisted as a duplicate field.
    """

    id: UUID = Field(default_factory=uuid4, description="Internal identity of this entity record.")
    kind: Literal["contextual", "structural"] = Field(
        ...,
        description="Why the value is privacy-relevant.",
    )
    tag: str = Field(..., min_length=1, description="Canonical privacy tag, such as EMAIL or API_KEY.")
    uid: str = Field(
        default_factory=lambda: secrets.token_hex(16),
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-f]{32}$",
        description="Occurrence-specific opaque token.",
    )
    span: str = Field(..., min_length=1, description="Exact sensitive substring from the input.")
    offsets: tuple[int, int] = Field(
        ...,
        description="Zero-based, end-exclusive Unicode code-point offsets as (start, end).",
    )
    reason: str | None = Field(default=None, description="Why the detector classified the span as sensitive.")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    native_label: str | None = Field(default=None, description="Original backend label before normalization.")
    native_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Backend-specific metadata preserved for audit and comparison.",
    )
    detection_method: Literal["regex", "ner", "token_classifier", "llm", "hybrid"] = Field(
        ...,
        description="Mechanism that produced the detection.",
    )
    run_id: UUID = Field(..., description="Detector run that produced this entity.")
    is_required: Requiredness = Field(
        default_factory=lambda: Requiredness(value=None, reason="not assessed"),
        description="Whether this entity is required for the query's response or processing.",
    )

    @model_validator(mode="after")
    def validate_offsets(self) -> PrivacyEntity:
        """Validate the basic offset ordering invariant."""
        start, end = self.offsets
        if start < 0 or end <= start:
            raise ValueError("offsets must satisfy 0 <= start < end")
        return self

    @property
    def identifier(self) -> str:
        """Return the computed tag#uid marker without persisting it."""
        return f"{self.tag}#{self.uid}"


class DetectorRunBase(BaseModel):
    """Common fields shared by every detector execution provenance record."""

    run_id: UUID = Field(default_factory=uuid4)
    detector_type: str
    detector_id: str = Field(
        ...,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+(?:-[0-9]+)*$",
    )
    status: Literal["complete", "partial", "failed"] = "complete"
    external_opt_in: bool = False
    adapter_version: str = Field(
        ...,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+(?:-[0-9]+)*$",
    )
    error_code: str | None = None


class RecognizerDescriptor(BaseModel):
    """Identity metadata for one configured Presidio recognizer."""

    name: str
    identifier: str | None = None
    version: str | None = None


class LLMDetectorRun(DetectorRunBase):
    """Execution provenance for the LiteLLM-backed LLM detector."""

    detector_type: Literal["llm"] = "llm"
    model_id: str
    model_revision: str | None = None
    prompt_version: str | None = None


class PresidioDetectorRun(DetectorRunBase):
    """Execution provenance for one Presidio Analyzer run."""

    detector_type: Literal["presidio"] = "presidio"
    configured_recognizers: list[RecognizerDescriptor] = Field(default_factory=list)
    package_version: str | None = None


class OPFDetectorRun(DetectorRunBase):
    """Execution provenance for one OpenAI Privacy Filter run."""

    detector_type: Literal["opf"] = "opf"
    model_id: str
    model_revision: str | None = None
    output_mode: str = "typed"
    decode_mode: str | None = None


class LFMDetectorRun(DetectorRunBase):
    """Execution provenance for one LFM2.5 detector run."""

    detector_type: Literal["lfm"] = "lfm"
    model_id: str
    model_revision: str | None = None
    decoder_revision: str | None = None
    device: str | None = None


DetectorRunProvenance = Annotated[
    LLMDetectorRun | PresidioDetectorRun | OPFDetectorRun | LFMDetectorRun,
    Field(discriminator="detector_type"),
]


class DetectionResult(BaseModel):
    """Normalized detector output with auditable run provenance.

    A failed or partial result is distinct from an empty successful result.
    ``token_map`` derives identifier-to-span data from ``entities`` without
    creating a second value binding store.
    """

    status: Literal["complete", "partial", "failed"] = "complete"
    entities: list[PrivacyEntity] = Field(default_factory=list)
    detector_runs: list[DetectorRunProvenance] = Field(default_factory=list)
    diagnostics: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_entity_references(self) -> DetectionResult:
        """Validate entity identity and detector-run references."""
        ids = [entity.id for entity in self.entities]
        uids = [entity.uid for entity in self.entities]
        run_ids = {run.run_id for run in self.detector_runs}
        if len(ids) != len(set(ids)):
            raise ValueError("entity ids must be unique within a detection result")
        if len(uids) != len(set(uids)):
            raise ValueError("entity uids must be unique within a detection result")
        missing_run_ids = {entity.run_id for entity in self.entities} - run_ids
        if missing_run_ids:
            raise ValueError(f"entities reference unrecorded run_id values: {sorted(missing_run_ids)}")
        return self

    def token_map(self) -> dict[str, str]:
        """Derive identifier-to-value mapping without storing a duplicate binding list."""
        return {entity.identifier: entity.span for entity in self.entities}
