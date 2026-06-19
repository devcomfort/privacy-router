"""Extractor — Facade for the extraction pipeline.

Composes ExtractorCore (Socratic extraction) + optional Critic (review)
into a single interface. Judge is injected externally by the Router.

Design
------
```
Extractor (facade)
  ├── ExtractorCore  — Socratic extraction (always)
  └── Critic         — post-review (precision="high" only)
```

Both components are independently injectable for testing.

Examples
--------
>>> extractor = Extractor()                        # default
>>> extractor = Extractor(precision="high")        # with Critic review
>>> extractor = Extractor(critic=my_critic)        # inject custom Critic
>>> result = extractor.extract("주민등록번호 901212-1234567")
"""

from __future__ import annotations

import re
from typing import Literal

from .critic import Critic
from .extractor_core import ExtractorCore
from .schemas import (
    ExtractionRecord,
    ExtractionResult,
    Sensitivity,
    _CriticItem,
)

# ── Constants ────────────────────────────────────────────────────────────────

_SCREAMING_CASE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
"""Pattern validating SCREAMING_SNAKE_CASE tag format."""

_DEFAULT_EXTRACTOR: Extractor | None = None
"""Module-level singleton, populated on first call to :func:`extract`."""


# ── Extractor ────────────────────────────────────────────────────────────────


class Extractor:
    """Facade for the extraction pipeline.

    Parameters
    ----------
    precision : "default" | "high"
        Extraction precision. "high" enables Critic post-review.
    model : str or None
        Override the model for extraction.
    api_base : str or None
        Override the API base URL.
    core : ExtractorCore or None
        Inject a custom ExtractorCore (for testing).
    critic : Critic or None
        Inject a custom Critic (for testing). Auto-created if precision="high".
    """

    def __init__(
        self,
        precision: Literal["default", "high"] = "default",
        model: str | None = None,
        api_base: str | None = None,
        core: ExtractorCore | None = None,
        critic: Critic | None = None,
    ) -> None:
        self._precision = precision
        self._core = core or ExtractorCore(model=model, api_base=api_base)
        self._critic = critic if critic is not None else (
            Critic(model=model, api_base=api_base) if precision == "high" else None
        )

    @property
    def precision(self) -> str:
        return self._precision

    def extract(self, text: str) -> ExtractionResult:
        """Extract sensitive information from text.

        Parameters
        ----------
        text : str
            The raw text to analyse.

        Returns
        -------
        ExtractionResult
            Sensitivity assessment and validated records.
        """
        # Phase 1: Socratic extraction
        result = self._core.extract(text)

        # Phase 2: Critic review (high precision only)
        # Runs even when Phase 1 found nothing — Critic's job is to catch
        # Phase 2: Critic review (high precision only)
        # Runs on any non-empty text, regardless of Phase 1 results.
        # Critic's job: catch what Phase 1 missed, including when it missed EVERYTHING.
        if self._critic and text and text.strip():
            review = self._critic.review(text, result.records)
            if review.found_missed:
                validated = _validate_critic_records(
                    review.missed_records, text, result.records
                )
                if validated:
                    result = ExtractionResult(
                        sensitivity=Sensitivity(
                            is_sensitive=True,
                            rationale=result.sensitivity.rationale
                            or "Critic에서 민감 정보 발견.",
                        ),
                        records=result.records + validated,
                    )

        return result


# ── Validation ────────────────────────────────────────────────────────────────


def _validate_critic_records(
    missed: list[_CriticItem],
    original_text: str,
    existing: list[ExtractionRecord],
) -> list[ExtractionRecord]:
    """Convert and validate critic-found records.

    Applies the same bar as ExtractorCore:
    - SCREAMING_SNAKE_CASE category check
    - Span exists in original text
    - Confidence >= 0.5
    - Deduplication against existing records
    - Computes start/end positions
    """
    seen_spans = {r.span for r in existing}
    validated = []

    for item in missed:
        # Dedup
        if item.span in seen_spans:
            continue

        # Same validation as ExtractorCore._validate_record
        cat = item.category.strip().upper()
        if not _SCREAMING_CASE_RE.match(cat):
            continue

        span = item.span.strip()
        if not span:
            continue
        if span not in original_text:
            continue
        if item.confidence < 0.5:
            continue

        start = original_text.find(span)
        validated.append(ExtractionRecord(
            category=cat,
            span=span,
            confidence=item.confidence,
            reasoning=item.reasoning or "",
            is_essential=item.is_essential,
            start=start,
            end=start + len(span),
        ))
        seen_spans.add(span)

    return validated


# ── Module-level convenience ─────────────────────────────────────────────────


def extract(
    text: str, precision: Literal["default", "high"] = "default"
) -> ExtractionResult:
    """One-shot extraction using a shared :class:`Extractor` instance.

    Parameters
    ----------
    text : str
        The raw text to analyse.
    precision : "default" | "high"
        Extraction precision.

    Returns
    -------
    ExtractionResult
        Sensitivity assessment and validated records.
    """
    global _DEFAULT_EXTRACTOR
    if _DEFAULT_EXTRACTOR is None or _DEFAULT_EXTRACTOR.precision != precision:
        _DEFAULT_EXTRACTOR = Extractor(precision=precision)
    return _DEFAULT_EXTRACTOR.extract(text)
