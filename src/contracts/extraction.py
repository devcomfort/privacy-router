"""Contracts shared by the extractor and masker packages."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class Sensitivity(BaseModel):
    """Assessment of whether input text contains sensitive information."""

    is_sensitive: bool = Field(..., description="Whether sensitive information was detected in the text.")
    rationale: str = Field(..., description="Human-readable explanation of the assessment.")


class ConfidentialityJudgment(BaseModel):
    """Disclosure sensitivity of one information item, independent of task necessity."""

    model_config = ConfigDict(frozen=True)

    value: Literal["public", "private"] | None = Field(
        default=None, description="None means unassessed, not a third confidentiality label."
    )
    reason: str | None = Field(
        default=None,
        min_length=1,
        pattern=r"\S",
        description="Assessment explanation; omitted only when not retained in metadata-only replay.",
    )

    @computed_field
    @property
    def status(self) -> Literal["assessed", "unassessed"]:
        """Expose missing evidence separately from the binary labels."""
        return "unassessed" if self.value is None else "assessed"


class NecessityJudgment(BaseModel):
    """Whether one original value is required or optional for the assessed task."""

    model_config = ConfigDict(frozen=True)

    value: Literal["required", "optional"] | None = Field(
        default=None,
        description="None means unassessed; individual optionality does not establish joint masking safety.",
    )
    reason: str | None = Field(
        default=None,
        min_length=1,
        pattern=r"\S",
        description="Assessment explanation; omitted only when not retained in metadata-only replay.",
    )

    @computed_field
    @property
    def status(self) -> Literal["assessed", "unassessed"]:
        """Expose missing evidence separately from the binary labels."""
        return "unassessed" if self.value is None else "assessed"


class ExtractionRecord(BaseModel):
    """One validated information span, whether public, private, or unassessed."""

    category: str = Field(..., description="Value-independent SCREAMING_SNAKE_CASE semantic type.")
    span: str = Field(..., description="Exact substring matched in the original text.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence score.")
    start: int = Field(..., ge=0, description="Start character index, 0-indexed.")
    end: int = Field(..., ge=0, description="End character index, exclusive.")
    detection_type: str = Field(default="contextual", description="Pattern or contextual detection.")
    confidentiality: ConfidentialityJudgment = Field(..., description="Per-item confidentiality and its reason.")
    necessity: NecessityJudgment = Field(..., description="Per-item task necessity and its independent reason.")


class ExtractionResult(BaseModel):
    """Validated sensitivity assessment and extracted records."""

    status: Literal["complete", "partial"] = Field(
        default="complete",
        description="Partial when any model item fails source validation; never sufficient for disclosure.",
    )
    sensitivity: Sensitivity = Field(..., description="Sensitivity assessment including rationale.")
    records: list[ExtractionRecord] = Field(default_factory=list, description="Validated extraction records.")
    masking_preserves_task: bool | None = Field(
        default=None,
        strict=True,
        description="Whether jointly masking all sensitive values in the assessed source preserves task completion. False means completion is prevented; None means not established.",
    )
    masking_reason: str | None = Field(default=None, description="Explanation of the whole-source masking assessment.")

    @model_validator(mode="after")
    def protected_records_imply_sensitivity(self) -> ExtractionResult:
        """Protect private and unassessed spans without treating public records as private."""
        if (
            any(record.confidentiality.value != "public" for record in self.records)
            and not self.sensitivity.is_sensitive
        ):
            self.sensitivity = self.sensitivity.model_copy(update={"is_sensitive": True})
        return self


def redact_extraction_records(records: Iterable[ExtractionRecord]) -> list[dict[str, Any]]:
    """Build metadata without exposing raw spans or model reasoning."""
    return [
        {
            "index": index,
            "category": record.category,
            "span": "<redacted>",
            "confidence": record.confidence,
            "confidentiality": {"value": record.confidentiality.value, "status": record.confidentiality.status},
            "necessity": {"value": record.necessity.value, "status": record.necessity.status},
        }
        for index, record in enumerate(records)
    ]
