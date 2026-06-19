"""ExtractorCore — Socratic sensitive information detection.

Pure extraction logic. No post-processing, no review.
This is the foundation that Extractor and Critic build on.

Examples
--------
>>> core = ExtractorCore()
>>> result = core.extract("주민등록번호 901212-1234567")
>>> result.sensitivity.is_sensitive
True
"""

from __future__ import annotations

import re
from pathlib import Path

from agents.llm import call_llm_structured, load_prompt, render_prompt

from .schemas import (
    ExtractionRecord,
    ExtractionResult,
    Sensitivity,
    _ExtractedItem,
    _ExtractedOutput,
)

# ── Constants ────────────────────────────────────────────────────────────────

_PROMPT_PATH = Path(__file__).parent / "extract.prompt"
"""Path to the dotpromptz prompt file used for extraction."""

_SCREAMING_CASE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
"""Pattern validating SCREAMING_SNAKE_CASE tag format."""


# ── Validation helpers ───────────────────────────────────────────────────────


def _validate_record(
    item: _ExtractedItem, original_text: str
) -> ExtractionRecord | None:
    """Validate and sanitize a raw SLM output item.

    Returns ``None`` when the item is invalid and should be discarded.
    """
    cat_raw = item.category.strip()
    if not _SCREAMING_CASE_RE.match(cat_raw):
        return None
    cat = cat_raw.upper()

    span = item.span.strip()
    if not span:
        return None

    if span not in original_text:
        return None

    if item.confidence < 0.5:
        return None

    start = original_text.find(span)
    return ExtractionRecord(
        category=cat,
        span=span,
        confidence=item.confidence,
        reasoning=item.reasoning or "",
        is_essential=item.is_essential,
        start=start,
        end=start + len(span),
    )


# ── ExtractorCore ────────────────────────────────────────────────────────────


class ExtractorCore:
    """Pure Socratic extraction — no review, no post-processing.

    Parameters
    ----------
    model : str or None
        Override the model identifier from the prompt.
    api_base : str or None
        Override the API base URL.
    prompt_path : str | Path | None
        Override the prompt file path.
    """

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        prompt_path: str | Path | None = None,
    ) -> None:
        path = str(prompt_path or _PROMPT_PATH)
        self._prompt = load_prompt(path)
        self._model = model or self._prompt["model"]
        self._api_base = api_base

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
        if not text or not text.strip():
            return ExtractionResult(
                sensitivity=Sensitivity(
                    is_sensitive=False, rationale="빈 텍스트입니다."
                ),
            )

        rendered = render_prompt(self._prompt["template"], text=text)
        messages = [{"role": "user", "content": rendered}]

        try:
            output = call_llm_structured(
                messages, _ExtractedOutput, model=self._model, api_base=self._api_base
            )
        except Exception:
            return ExtractionResult(
                sensitivity=Sensitivity(
                    is_sensitive=False, rationale="SLM 응답 파싱 실패."
                ),
            )

        records = [
            r
            for item in output.records
            for r in [_validate_record(item, text)]
            if r is not None
        ]
        return ExtractionResult(sensitivity=output.sensitivity, records=records)
