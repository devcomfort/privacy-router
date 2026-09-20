"""Recommended handling actions driven only by existing privacy evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agents.extractor.schemas import DetectionResult
from cachier import CachedAssessment
from contracts.extraction import ExtractionResult

SessionEvidence = ExtractionResult | DetectionResult | CachedAssessment


class RecommendedAction(StrEnum):
    """Handling recommendations, not information grades or authorization."""

    SHARE_ORIGINAL = "share_original"
    MASK_THEN_SHARE = "mask_then_share"
    KEEP_LOCAL = "keep_local"


@dataclass(frozen=True, slots=True)
class PolicyRecommendation:
    """A supported action, or no recommendation when evidence is insufficient."""

    action: RecommendedAction | None
    reason: str


class Policy(Protocol):
    def recommend(self, results: Iterable[SessionEvidence]) -> PolicyRecommendation:
        """Recommend handling using evidence from the same assessed task and context."""
        ...


class HeuristicPolicy:
    """Recommend an action without another model call.

    Incomplete evidence or unassessed confidentiality leaves the action unset.
    Public items never require masking or local processing. Known task-essential
    private values or known loss from joint masking warrant local processing.
    Otherwise, masking requires a known whole-source preservation assessment for
    every sensitive result, independently of item-specific necessity. Evidence
    must concern the same assessed task and context. Complete public-only
    evidence permits sharing the original; None never permits external sharing.
    """

    def recommend(self, results: Iterable[SessionEvidence]) -> PolicyRecommendation:
        sensitive = False
        masking_loses_meaning = False
        unknown = False
        incomplete = False
        confidentiality_unassessed = False
        seen = False
        for result in results:
            seen = True
            if isinstance(result, ExtractionResult):
                incomplete |= result.status != "complete"
                sensitive_here = result.sensitivity.is_sensitive
                judgments = ((record.confidentiality.value, record.necessity.value) for record in result.records)
            elif isinstance(result, DetectionResult):
                incomplete |= result.status != "complete"
                sensitive_here = False
                judgments = ((entity.confidentiality.value, entity.necessity.value) for entity in result.entities)
            elif isinstance(result, CachedAssessment):
                sensitive_here = result.is_sensitive
                judgments = ((reference.confidentiality, reference.necessity) for reference in result.references)
            else:
                raise TypeError(
                    "Session evidence must be an extraction result or cached assessment; a cache miss is not evidence"
                )
            protected_present = False
            for confidentiality, necessity in judgments:
                if confidentiality == "public":
                    continue
                protected_present = True
                confidentiality_unassessed |= confidentiality is None
                masking_loses_meaning |= confidentiality == "private" and necessity == "required"
            sensitive_here |= protected_present
            incomplete |= sensitive_here and not protected_present
            sensitive |= sensitive_here
            if sensitive_here:
                masking_loses_meaning |= result.masking_preserves_task is False
                unknown |= result.masking_preserves_task is not True and result.masking_preserves_task is not False
        if not seen:
            return PolicyRecommendation(None, "no_evidence")
        if incomplete:
            return PolicyRecommendation(None, "incomplete_analysis")
        if confidentiality_unassessed:
            return PolicyRecommendation(None, "confidentiality_unassessed")
        if masking_loses_meaning:
            return PolicyRecommendation(RecommendedAction.KEEP_LOCAL, "masking_loses_meaning")
        if unknown:
            return PolicyRecommendation(None, "masking_impact_unknown")
        if sensitive:
            return PolicyRecommendation(RecommendedAction.MASK_THEN_SHARE, "masking_preserves_task")
        return PolicyRecommendation(RecommendedAction.SHARE_ORIGINAL, "no_sensitive_data")
