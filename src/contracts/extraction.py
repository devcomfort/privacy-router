"""Contracts shared by the extractor and masker packages."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Sensitivity(BaseModel):
    """Assessment of whether input text contains sensitive information."""

    is_sensitive: bool = Field(..., description="Whether sensitive information was detected in the text.")
    rationale: str = Field(..., description="Human-readable explanation of the assessment.")


class Requiredness(BaseModel):
    """Tri-state assessment of whether a detected entity is required."""

    value: bool | None = Field(
        default=None,
        description="Whether this entity is required for the user's query response or processing.",
    )
    reason: str | None = Field(default=None, description="Why the entity is or is not required.")

    @model_validator(mode="after")
    def require_reason(self) -> Requiredness:
        """Require an explanation for every state."""
        if not self.reason or not self.reason.strip():
            raise ValueError("is_required.reason is required for every value state")
        return self


class ExtractionRecord(BaseModel):
    """One validated sensitive span returned by an extractor."""

    category: str = Field(..., description="Value-independent SCREAMING_SNAKE_CASE semantic type.")
    span: str = Field(..., description="Exact substring matched in the original text.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence score.")
    start: int = Field(..., ge=0, description="Start character index, 0-indexed.")
    end: int = Field(..., ge=0, description="End character index, exclusive.")
    detection_type: str = Field(default="contextual", description="Pattern or contextual detection.")
    reasoning: str = Field(default="", description="Why this span is sensitive.")
    is_required: Requiredness = Field(
        default_factory=lambda: Requiredness(value=None, reason="not assessed"),
        description="Whether masking this record preserves query meaning.",
    )


class ExtractionResult(BaseModel):
    """Validated sensitivity assessment and extracted records."""

    sensitivity: Sensitivity = Field(..., description="Sensitivity assessment including rationale.")
    records: list[ExtractionRecord] = Field(default_factory=list, description="Validated extraction records.")

    @model_validator(mode="after")
    def records_imply_sensitivity(self) -> ExtractionResult:
        """Treat validated sensitive spans as authoritative evidence."""
        if self.records and not self.sensitivity.is_sensitive:
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
            "is_required": {"value": record.is_required.value},
        }
        for index, record in enumerate(records)
    ]
