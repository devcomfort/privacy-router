"""Immutable intent evidence bound to the exact source being analyzed."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _IntentContent(BaseModel):
    """Intent content shared by structured inference and source-bound evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    goal: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1024, pattern=r"\S")]
    action: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256, pattern=r"\S")]
    completion_condition: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1024, pattern=r"\S")]
    channel: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256, pattern=r"\S")] | None = None
    unresolved: tuple[
        Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"\S")], ...
    ] = Field(default=(), max_length=12)


class IntentAnnotation(_IntentContent):
    """Task evidence, never execution permission or disclosure authorization."""

    source_hash: Annotated[str, StringConstraints(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]

    @classmethod
    def for_text(
        cls,
        text: str,
        *,
        goal: str,
        action: str,
        completion_condition: str,
        channel: str | None = None,
        unresolved: tuple[str, ...] = (),
    ) -> IntentAnnotation:
        """Bind caller-provided intent to unchanged UTF-8 source text locally."""
        return cls(
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            goal=goal,
            action=action,
            completion_condition=completion_condition,
            channel=channel,
            unresolved=unresolved,
        )

    def matches_source(self, text: str) -> bool:
        """Check exact source identity without whitespace or Unicode normalization."""
        return self.source_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()

    def fingerprint(self) -> str:
        """Hash canonical evidence, including source binding, for cache isolation."""
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
