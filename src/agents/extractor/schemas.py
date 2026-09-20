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
    ConfidentialityJudgment,
    ExtractionRecord,
    ExtractionResult,
    NecessityJudgment,
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

    Every item carries independent confidentiality and necessity judgments.
    Their reasons are required on fresh model output, including unassessed values.
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
    confidentiality: ConfidentialityJudgment = Field(
        ..., description="public/private or null, with an independent explanation."
    )
    necessity: NecessityJudgment = Field(..., description="required/optional or null, with an independent explanation.")

    @model_validator(mode="after")
    def require_judgment_reasons(self) -> _ExtractedItem:
        """Reject successful model output that omits either explanation."""
        if self.confidentiality.reason is None or self.necessity.reason is None:
            raise ValueError("Both confidentiality.reason and necessity.reason are required")
        return self


class _ExtractedOutput(BaseModel):
    """Single-call model output; overall sensitivity is derived from raw item judgments."""

    intent_consistent: bool | None = Field(
        default=None,
        strict=True,
        description="True only when supplied intent agrees with the original source; False for conflict; None if absent or unconfirmed. Never authorizes disclosure.",
    )
    masking_preserves_task: bool | None = Field(
        default=None,
        strict=True,
        description="Whether jointly masking all sensitive values preserves the supplied task. Independent of which alternative value is individually required; None if not established.",
    )
    masking_reason: str | None = Field(
        default=None,
        description="Why whole-source masking preserves or prevents completion, or what evidence is missing.",
    )
    records: list[_ExtractedItem] = Field(
        ...,
        description="Raw extracted items from the SLM.",
    )


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
    span: str = Field(..., min_length=1, description="Exact information substring from the input.")
    offsets: tuple[int, int] = Field(
        ...,
        description="Zero-based, end-exclusive Unicode code-point offsets as (start, end).",
    )
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
    confidentiality: ConfidentialityJudgment = Field(..., description="Per-item confidentiality and its reason.")
    necessity: NecessityJudgment = Field(
        default_factory=lambda: NecessityJudgment(value=None, reason="Task necessity was not assessed."),
        description="Per-item task necessity, independent of confidentiality.",
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
    masking_preserves_task: bool | None = Field(
        default=None,
        strict=True,
        description="Whole-source task preservation under joint masking; None when this detector does not assess it.",
    )
    masking_reason: str | None = Field(default=None, description="Explanation of the whole-source masking assessment.")

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
