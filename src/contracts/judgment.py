"""Schemas for the Judge package.

All Pydantic models used by the Judge — the privacy policy decision
engine. Models are documented with pydantic.Field including
descriptions and examples.

Notes
-----
``Judgment`` is the primary output. ``MeaningfulnessAssessment``
encodes the two-axis evaluation result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MeaningfulnessAssessment(BaseModel):
    """Whether a query remains meaningful after sensitive spans are masked.

    Attributes
    ----------
    is_meaningful_after_masking : bool
        True if the user's intent survives placeholder substitution.
    rationale : str
        Korean explanation of the assessment.

    Examples
    --------
    >>> m = MeaningfulnessAssessment(is_meaningful_after_masking=True, rationale="메인 동사 '작성해줘'는 이메일 작성을 향함.")
    >>> m.is_meaningful_after_masking
    True
    """

    is_meaningful_after_masking: bool = Field(
        ...,
        description="Whether the query is still meaningful after all sensitive spans are replaced with placeholders.",
        examples=[True, False],
    )
    rationale: str = Field(
        ...,
        description="Explanation of why the query does or does not survive masking (Korean).",
        examples=[
            "메인 동사 '작성해줘'는 이메일 작성을 향함. 마스킹 후에도 요청 의미 유지.",
            "메인 동사 '뭐야'가 민감 정보 자체를 향함. 마스킹 시 질문 의미 상실.",
        ],
    )


class Judgment(BaseModel):
    """Full output of the Judge phase.

    Attributes
    ----------
    meaningful_after_masking : MeaningfulnessAssessment
        Whether the query survives masking.
    policy_action : str
        One of ``"allow"``, ``"selective_mask"``, or ``"block"``.
    strategy : str
        Korean recommendation for the routing layer.
    rationale : str
        Korean explanation of the overall decision.

    Examples
    --------
    >>> mam = MeaningfulnessAssessment(is_meaningful_after_masking=True, rationale="컨텍스트")
    >>> j = Judgment(meaningful_after_masking=mam, policy_action="selective_mask", strategy="마스킹 후 전송", rationale="컨텍스트이므로")
    >>> j.policy_action
    'selective_mask'
    """

    meaningful_after_masking: MeaningfulnessAssessment = Field(
        ...,
        description="Assessment of whether masking preserves query intent.",
    )
    policy_action: str = Field(
        ...,
        description="Recommended action: 'allow', 'selective_mask', or 'block'.",
        examples=["selective_mask", "block", "allow"],
    )
    strategy: str = Field(
        ...,
        description="Human-readable strategy recommendation (Korean).",
        examples=["민감 정보를 마스킹 처리한 후 요청을 수행합니다."],
    )
    rationale: str = Field(
        ...,
        description="Explanation of the overall decision (Korean).",
        examples=["메인 동사가 민감 정보 자체가 아닌 작업 수행을 목적으로 하므로 마스킹 후 전송 적절."],
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the judgment as a plain dictionary."""
        return self.model_dump()
