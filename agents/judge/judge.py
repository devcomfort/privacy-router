"""Judge — Privacy policy decision engine (rule-based).

The Judge receives sensitivity assessments and extraction records
from the Extractor and produces a :class:`Judgment` that tells the
Router what action to take.

No LLM calls — all decisions are based on is_essential flags.

Examples
--------
>>> judge = Judge()
>>> j = judge.classify(
...     sensitivity={"is_sensitive": True, "rationale": "..."},
...     records=[{"category": "RESIDENT_REGISTRATION_NUMBER", "is_essential": False, ...}],
...     text="주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
... )
>>> j.policy_action
'mask_and_send'
"""

from __future__ import annotations

from typing import Any

from .schemas import Judgment, MeaningfulnessAssessment

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_JUDGE: Judge | None = None
"""Module-level singleton, populated on first call to :func:`judge`."""


# ── Judge ────────────────────────────────────────────────────────────────────


class Judge:
    """Privacy policy judge that decides what action to take.

    Rule-based: no LLM calls. Decisions based on is_essential flags.

    Parameters
    ----------
    model : str or None
        Ignored (kept for backward compatibility).
    api_base : str or None
        Ignored (kept for backward compatibility).
    """

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
    ) -> None:
        pass

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
            The original input text (unused in rule-based mode).

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
        ...     records=[{"category": "RRN", "span": "901212-1234567", "is_essential": False}],
        ...     text="주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        ... )
        >>> j.policy_action
        'mask_and_send'
        """
        is_sensitive = sensitivity.get("is_sensitive", len(records) > 0)

        # No sensitive info → allow
        if not is_sensitive or not records:
            return Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=True,
                    rationale="민감 정보가 없습니다.",
                ),
                policy_action="route_to_external",
                strategy="민감 정보가 없으므로 외부 API를 사용합니다.",
                rationale=sensitivity.get("rationale", "탐지된 민감 정보가 없습니다."),
            )

        # Check is_essential flags
        essential_count = sum(1 for r in records if r.get("is_essential", False))

        if essential_count > 0:
            return Judgment(
                meaningful_after_masking=MeaningfulnessAssessment(
                    is_meaningful_after_masking=False,
                    rationale=f"essential: {essential_count}/{len(records)} records",
                ),
                policy_action="route_to_local",
                strategy="민감 정보가 질의의 핵심이므로 로컬에서 처리합니다.",
                rationale=f"essential: {essential_count}/{len(records)} records",
            )

        # All records are maskable
        return Judgment(
            meaningful_after_masking=MeaningfulnessAssessment(
                is_meaningful_after_masking=True,
                rationale=f"마스킹 가능: {len(records)} records",
            ),
            policy_action="mask_and_send",
            strategy="민감 정보를 마스킹 후 요청을 수행합니다.",
            rationale=f"마스킹 가능: {len(records)} records",
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
