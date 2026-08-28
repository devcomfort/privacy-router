from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from .schemas import Requiredness


class ParsedEntity(BaseModel):
    """Backend-neutral candidate before identity and offset reconciliation."""

    tag: str = Field(..., min_length=1)
    kind: Literal["contextual", "structural"]
    native_label: str | None = None
    span: str = Field(..., min_length=1)
    offsets: tuple[int, int] | None = None
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    detection_method: Literal["regex", "ner", "token_classifier", "llm", "hybrid"]
    native_metadata: dict[str, Any] = Field(default_factory=dict)
    is_required: Requiredness = Field(default_factory=Requiredness)


class DetectorParser(Protocol):
    """Convert one detector's native payload into normalized candidates."""

    def parse(self, raw: object, text: str) -> list[ParsedEntity]:
        """Parse native detector output for the supplied source text."""
        ...
