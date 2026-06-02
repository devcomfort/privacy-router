"""Judge — Privacy policy decision engine.

The Judge receives sensitivity assessments and extraction records
from the Extractor and produces a :class:`Judgment` that tells the
Router what action to take.

The LLM is only asked one question: "does the query survive masking?"
Sensitivity is already determined by the Extractor.

Examples
--------
>>> judge = Judge()
>>> j = judge.classify(
...     sensitivity={"is_sensitive": True, "rationale": "..."},
...     records=[{"category": "RESIDENT_REGISTRATION_NUMBER", ...}],
...     text="주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
... )
>>> j.policy_action
'mask_and_send'
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.llm import call_llm_structured, load_prompt, render_prompt

from .schemas import Judgment, MeaningfulnessAssessment

# ── Constants ────────────────────────────────────────────────────────────────

_PROMPT_PATH = Path(__file__).parent / "classify.prompt"
"""Path to the dotpromptz prompt file used for classification."""

_DEFAULT_JUDGE: Judge | None = None
"""Module-level singleton, populated on first call to :func:`judge`."""


# ── Judge ────────────────────────────────────────────────────────────────────


class Judge:
    """Privacy policy judge that decides what action to take.

    The Judge evaluates whether a query remains meaningful after
    masking its sensitive spans. It does NOT re-evaluate whether
    information is sensitive — that is the Extractor's responsibility.

    Parameters
    ----------
    model : str or None
        Override the model identifier from the prompt file.
        If ``None``, the model in ``classify.prompt`` is used.

    Examples
    --------
    >>> judge = Judge()
    >>> judgment = judge.classify(
    ...     sensitivity={"is_sensitive": False, "rationale": "no PII"},
    ...     records=[],
    ...     text="hello",
    ... )
    >>> judgment.policy_action
    'allow'
    """

    def __init__(self, model: str | None = None) -> None:
        self._prompt = load_prompt(str(_PROMPT_PATH))
        self._model = model or self._prompt["model"]

    # ── Public API ───────────────────────────────────────────────────────────

    def classify(
        self,
        sensitivity: dict,
        records: list[dict[str, Any]],
        text: str = "",
    ) -> Judgment:
        """Classify extraction records and produce a judgment.

        Parameters
        ----------
        sensitivity : dict
            ``{"is_sensitive": bool, "rationale": str}`` from the Extractor.
        records : list of dict
            Validated extraction records.
        text : str
            The original input text, used for context analysis.

        Returns
        -------
        Judgment
            Policy decision including meaningfulness assessment and
            recommended action.

        Examples
        --------
        >>> judge = Judge()
        >>> j = judge.classify(
        ...     sensitivity={"is_sensitive": True, "rationale": "주민등록번호"},
        ...     records=[{"category": "RRN", "span": "901212-1234567"}],
        ...     text="주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        ... )
        >>> j.policy_action
        'mask_and_send'
        """
        is_sensitive = sensitivity.get("is_sensitive", len(records) > 0)

        if not is_sensitive:
            return Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=True,
                    rationale="민감 정보가 없습니다.",
                ),
                policy_action="allow",
                strategy="민감 정보가 없으므로 외부 API를 사용합니다.",
                rationale=sensitivity.get("rationale", "탐지된 민감 정보가 없습니다."),
            )

        records_json = json.dumps(records, ensure_ascii=False, indent=2)
        rendered = render_prompt(
            self._prompt["template"], text=text, records=records_json
        )
        messages = [{"role": "user", "content": rendered}]

        try:
            return call_llm_structured(
                messages, Judgment, model=self._model, max_tokens=2048
            )
        except Exception:
            return Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=False,
                    rationale="파싱 실패.",
                ),
                policy_action="process_locally",
                strategy="판단 실패: 로컬에서 처리합니다.",
                rationale="SLM 응답을 파싱할 수 없습니다.",
            )


# ── Module-level convenience ─────────────────────────────────────────────────


def judge(
    sensitivity: dict,
    records: list[dict[str, Any]],
    text: str = "",
) -> Judgment:
    """One-shot classification using a shared :class:`Judge` instance.

    Parameters
    ----------
    sensitivity : dict
        ``{"is_sensitive": bool, "rationale": str}`` from the Extractor.
    records : list of dict
        Validated extraction records.
    text : str
        The original input text.

    Returns
    -------
    Judgment
        Policy decision.

    Examples
    --------
    >>> from agents.judge import judge
    >>> j = judge(sensitivity={"is_sensitive": False, "rationale": "none"}, records=[], text="hello")
    >>> j.policy_action
    'allow'
    """
    global _DEFAULT_JUDGE
    if _DEFAULT_JUDGE is None:
        _DEFAULT_JUDGE = Judge()
    return _DEFAULT_JUDGE.classify(sensitivity, records, text)
