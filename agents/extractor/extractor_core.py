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
from config import load_config, resolve_local_api_base

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

_SAFE_FALLBACK_CATEGORY = "SENSITIVE_DATA"
"""Category used when a model-generated label may contain a sensitive value."""

_CATEGORY_ALIASES = {
    "API_KEY": "API_CREDENTIAL",
    "COMPANY_NAME": "INSTITUTION_NAME",
    "CREDENTIAL": "API_CREDENTIAL",
    "INTERNAL_PROJECT_CODENAME": "INTERNAL_PROJECT_NAME",
    "INTERNAL_SYSTEM_URL": "INTERNAL_URL",
    "KOREAN_RRN": "RESIDENT_REGISTRATION_NUMBER",
    "MOBILE_PHONE_NUMBER": "PERSONAL_IDENTIFIER_NUMBER",
    "PASSPORT_NUMBER": "PERSONAL_IDENTIFIER_NUMBER",
    "PASSWORD": "API_CREDENTIAL",
    "PERSONAL_ID_NUMBER": "PERSONAL_IDENTIFIER_NUMBER",
    "PHONE_NUMBER": "PERSONAL_IDENTIFIER_NUMBER",
    "PROJECT_BUDGET": "PROJECT_BUDGET_AMOUNT",
    "PROJECT_LABOR_COST_AMOUNT": "PROJECT_LABOR_BUDGET_AMOUNT",
    "SALARY_AMOUNT": "SALARY_INFORMATION",
}
"""Semantically equivalent legacy labels mapped to the prompt's common names."""

_COMMON_CATEGORIES = frozenset(
    {
        *_CATEGORY_ALIASES.values(),
        "ACQUISITION_TARGET",
        "COMPETITIVE_LEAD_TIME",
        "COMPETITOR_NAME",
        "EMAIL_ADDRESS",
        "FABRICATION_PROCESS_DECISION",
        "INTERNAL_COST_DISCOUNT",
        "MEDICAL_DIAGNOSIS",
        "PATENT_FILING_TIMELINE",
        "PERSON_NAME",
        "RESIDENT_REGISTRATION_NUMBER",
        "SUPPLIER_SELECTION_DECISION",
        "UNPUBLISHED_BENCHMARK_RESULT",
        "UNPUBLISHED_RESEARCH_CONCEPT",
        "UNPUBLISHED_RESEARCH_METHODOLOGY",
    }
)
"""Value-independent category names shared by extractor prompts."""

_CATEGORY_WRAPPER_RULES = tuple(
    sorted(
        {
            **{category: category for category in _COMMON_CATEGORIES},
            **_CATEGORY_ALIASES,
        }.items(),
        key=lambda item: (-len(item[0]), item[0]),
    )
)
"""Known labels ordered deterministically for stripping value-bearing affixes."""


# ── Validation helpers ───────────────────────────────────────────────────────


def normalize_category(category: str, span: str) -> str | None:
    """Canonicalize a category and prevent sensitive-value label leakage."""
    normalized = category.strip().upper()
    if not _SCREAMING_CASE_RE.fullmatch(normalized):
        return None

    normalized = _CATEGORY_ALIASES.get(normalized, normalized)
    if normalized in _COMMON_CATEGORIES:
        return normalized

    for known_label, canonical_label in _CATEGORY_WRAPPER_RULES:
        if normalized.startswith(f"{known_label}_") or normalized.endswith(f"_{known_label}"):
            return canonical_label

    if any(character.isdigit() for character in normalized):
        return _SAFE_FALLBACK_CATEGORY

    category_tokens = {token for token in normalized.split("_") if token}
    span_tokens = {token.upper() for token in re.findall(r"[A-Za-z0-9]+", span)}
    if category_tokens & span_tokens:
        return _SAFE_FALLBACK_CATEGORY

    category_compact = normalized.replace("_", "")
    span_compact = "".join(re.findall(r"[A-Za-z0-9]+", span)).upper()
    if span_compact and span_compact in category_compact:
        return _SAFE_FALLBACK_CATEGORY

    return normalized


def _validate_record(item: _ExtractedItem, original_text: str) -> ExtractionRecord | None:
    """Validate and sanitize a raw SLM output item.

    Returns ``None`` when the item is invalid and should be discarded.
    """
    span = item.span.strip()
    if not span:
        return None

    cat = normalize_category(item.category, span)
    if cat is None:
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


class PrivacyAnalysisUnavailable(RuntimeError):
    """Raised when sensitive-information analysis cannot produce a valid result."""


class ExtractorCore:
    """Pure Socratic extraction — no review, no post-processing.

    Parameters
    ----------
    model : str or None
        Override the configured Decision Model identifier.
    api_base : str or None
        Override the API base URL.
    max_tokens : int or None
        Override the configured completion-token budget.
    prompt_path : str | Path | None
        Override the prompt file path.
    """

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        prompt_path: str | Path | None = None,
        max_tokens: int | None = None,
    ) -> None:
        path = str(prompt_path or _PROMPT_PATH)
        self._prompt = load_prompt(path)
        config = load_config()
        decision = config.decision
        self._model = model or decision.model
        configured_api_base = api_base
        if configured_api_base is None and model is None:
            configured_api_base = decision.api_base
        self._api_base = resolve_local_api_base(config, self._model, configured_api_base)
        self._max_tokens = max_tokens if max_tokens is not None else decision.config.max_tokens

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
                sensitivity=Sensitivity(is_sensitive=False, rationale="빈 텍스트입니다."),
            )

        rendered = render_prompt(self._prompt["template"], text=text)
        messages = [{"role": "user", "content": rendered}]

        try:
            output = call_llm_structured(
                messages,
                _ExtractedOutput,
                model=self._model,
                api_base=self._api_base,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            raise PrivacyAnalysisUnavailable("Sensitive-information analysis unavailable.") from exc

        records = [r for item in output.records for r in [_validate_record(item, text)] if r is not None]
        return ExtractionResult(sensitivity=output.sensitivity, records=records)
