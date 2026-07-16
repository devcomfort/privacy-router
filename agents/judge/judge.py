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
'selective_mask'
"""

from __future__ import annotations

from typing import Any, Literal

from .schemas import Judgment, MeaningfulnessAssessment

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_JUDGE: Judge | None = None
"""Module-level singleton, populated on first call to :func:`judge`."""
_ASSESSMENT_CACHE: dict[tuple[bool, str], MeaningfulnessAssessment] = {}


def _meaningfulness(is_meaningful: bool, rationale: str) -> MeaningfulnessAssessment:
    """Return a cached masking-meaningfulness assessment."""
    key = (is_meaningful, rationale)
    assessment = _ASSESSMENT_CACHE.get(key)
    if assessment is None:
        assessment = MeaningfulnessAssessment(
            is_meaningful_after_masking=is_meaningful,
            rationale=rationale,
        )
        _ASSESSMENT_CACHE[key] = assessment
    return assessment


def resolve_policy_action(
    declared_sensitive: bool,
    record_count: int,
    essential_count: int,
) -> Literal["allow", "selective_mask", "block"]:
    """Resolve the fail-closed action for an extraction state."""
    if record_count == 0:
        return "block" if declared_sensitive else "allow"
    return "block" if essential_count > 0 else "selective_mask"


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
        'selective_mask'
        """
        declared_sensitive = bool(sensitivity.get("is_sensitive", False))
        essential_count = sum(1 for r in records if r.get("is_essential", False))
        policy_action = resolve_policy_action(
            declared_sensitive,
            len(records),
            essential_count,
        )

        if policy_action == "allow":
            return Judgment(
                meaningful_after_masking=_meaningfulness(
                    True,
                    "마스킹할 민감 정보가 없습니다.",
                ),
                policy_action="allow",
                strategy="외부 LLM에 원문을 전송합니다.",
                rationale=sensitivity.get("rationale", "민감 정보 없음"),
            )

        if not records:
            return Judgment(
                meaningful_after_masking=_meaningfulness(
                    False,
                    "민감 정보로 판정되었지만 마스킹할 범위를 확인할 수 없습니다.",
                ),
                policy_action="block",
                strategy="원문을 외부로 전송하지 않고 로컬 LLM으로 라우팅합니다.",
                rationale=sensitivity.get(
                    "rationale",
                    "민감 정보로 판정되었지만 마스킹 범위가 없습니다.",
                ),
            )

        if policy_action == "block":
            return Judgment(
                meaningful_after_masking=_meaningfulness(
                    False,
                    f"essential: {essential_count}/{len(records)} records",
                ),
                policy_action="block",
                strategy="민감 정보가 질의의 핵심이므로 로컬에서 처리합니다.",
                rationale=f"essential: {essential_count}/{len(records)} records",
            )

        # All records are maskable
        return Judgment(
            meaningful_after_masking=_meaningfulness(
                True,
                f"마스킹 가능: {len(records)} records",
            ),
            policy_action="selective_mask",
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
