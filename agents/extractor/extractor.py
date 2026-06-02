"""Extractor — SLM-based sensitive information detection.

The Extractor is the entry point of the Privacy Router pipeline.
It takes raw text and returns structured extraction results including
a sensitivity assessment and validated records.

Examples
--------
>>> extractor = Extractor()
>>> result = extractor.extract("주민등록번호 901212-1234567")
>>> result.sensitivity.is_sensitive
True
>>> result.records[0].category
'RESIDENT_REGISTRATION_NUMBER'
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

_DEFAULT_EXTRACTOR: Extractor | None = None
"""Module-level singleton, populated on first call to :func:`extract`."""


# ── Validation helpers ───────────────────────────────────────────────────────


def _validate_record(
    item: _ExtractedItem, original_text: str
) -> ExtractionRecord | None:
    """Validate and sanitize a raw SLM output item.

    Parameters
    ----------
    item : _ExtractedItem
        Raw item produced by the SLM.
    original_text : str
        The original input text used for span verification.

    Returns
    -------
    ExtractionRecord or None
        A validated record, or ``None`` if the item is invalid.

    Examples
    --------
    >>> item = _ExtractedItem(category="RRN", span="901212-1234567", confidence=0.98, start=7, end=21)
    >>> _validate_record(item, "주민번호 901212-1234567")
    ExtractionRecord(...)
    """
    if not _SCREAMING_CASE_RE.match(item.category):
        return None
    if item.confidence < 0.5:
        return None

    start, end = item.start, item.end
    if original_text[start:end] != item.span:
        found = original_text.find(item.span)
        if found == -1:
            return None
        start, end = found, found + len(item.span)

    return ExtractionRecord(
        category=item.category,
        span=item.span,
        confidence=item.confidence,
        start=start,
        end=end,
    )


# ── Extractor ────────────────────────────────────────────────────────────────


class Extractor:
    """SLM-based sensitive information extractor.

    Uses a dotpromptz-managed prompt and instructor/LiteLLM for
    structured output.  The prompt file lives next to this module
    as ``extract.prompt``.

    Parameters
    ----------
    model : str or None
        Override the model identifier from the prompt.
        If ``None``, the model declared in the ``.prompt`` frontmatter
        is used.

    Examples
    --------
    >>> extractor = Extractor()
    >>> result = extractor.extract("주민등록번호 901212-1234567")
    >>> for rec in result.records:
    ...     print(rec.make_placeholder(1))
    [RESIDENT_REGISTRATION_NUMBER#1]
    """

    def __init__(self, model: str | None = None) -> None:
        self._prompt = load_prompt(str(_PROMPT_PATH))
        self._model = model or self._prompt["model"]

    # ── Public API ───────────────────────────────────────────────────────────

    def extract(self, text: str) -> ExtractionResult:
        """Extract sensitive information from text.

        Parameters
        ----------
        text : str
            The raw text to analyse.

        Returns
        -------
        ExtractionResult
            Sensitivity assessment and validated records. Records is
            empty when nothing is detected or the SLM call fails.
        """
        if not text or not text.strip():
            return ExtractionResult(
                sensitivity=Sensitivity(
                    is_sensitive=False, rationale="빈 텍스트입니다."
                ),
            )

        # Render the dotpromptz template with the input text
        rendered = render_prompt(self._prompt["template"], text=text)
        messages = [{"role": "user", "content": rendered}]

        # Call the SLM for structured extraction
        try:
            output = call_llm_structured(
                messages, _ExtractedOutput, model=self._model
            )
        except Exception:
            return ExtractionResult(
                sensitivity=Sensitivity(
                    is_sensitive=False, rationale="SLM 응답 파싱 실패."
                ),
            )

        # Validate each raw item against the original text
        records = [
            r
            for item in output.records
            for r in [_validate_record(item, text)]
            if r is not None
        ]
        return ExtractionResult(sensitivity=output.sensitivity, records=records)


# ── Module-level convenience ─────────────────────────────────────────────────


def extract(text: str) -> ExtractionResult:
    """One-shot extraction using a shared :class:`Extractor` instance.

    Parameters
    ----------
    text : str
        The raw text to analyse.

    Returns
    -------
    ExtractionResult
        Sensitivity assessment and validated records.

    Examples
    --------
    >>> from agents.extractor import extract
    >>> result = extract("주민등록번호 901212-1234567")
    >>> result.sensitivity.is_sensitive
    True
    """
    global _DEFAULT_EXTRACTOR
    if _DEFAULT_EXTRACTOR is None:
        _DEFAULT_EXTRACTOR = Extractor()
    return _DEFAULT_EXTRACTOR.extract(text)
