"""Recommended actions depend on evidence, not an information grade."""

from uuid import uuid4

import pytest

from agents.extractor.schemas import DetectionResult, LLMDetectorRun, PrivacyEntity
from cachier import Cachier
from contracts.extraction import (
    ConfidentialityJudgment,
    ExtractionRecord,
    ExtractionResult,
    NecessityJudgment,
    Sensitivity,
)
from policy import HeuristicPolicy, RecommendedAction


def result(
    *required: bool | None,
    sensitive: bool = False,
    confidentiality: str | None = "private",
    masking_preserves_task: bool | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        sensitivity=Sensitivity(is_sensitive=sensitive, rationale="synthetic assessment"),
        masking_preserves_task=masking_preserves_task,
        records=[
            ExtractionRecord(
                category="CONFIDENTIAL_DATA",
                span="private",
                confidence=0.1,
                start=0,
                end=7,
                confidentiality=ConfidentialityJudgment(value=confidentiality, reason="Disclosure assessment"),
                necessity=NecessityJudgment(
                    value=None if value is None else "required" if value else "optional",
                    reason="Task assessment",
                ),
            )
            for value in required
        ],
    )


def test_recommendations_combine_evidence_for_the_same_assessed_task():
    policy = HeuristicPolicy()
    assert policy.recommend([result(), result()]).action == RecommendedAction.SHARE_ORIGINAL
    maskable = result(False, masking_preserves_task=True)
    assert policy.recommend([maskable, result()]).action == RecommendedAction.MASK_THEN_SHARE
    assert policy.recommend([maskable, result(True), result()]).action == RecommendedAction.KEEP_LOCAL
    assert policy.recommend([result(None), result(True)]).action == RecommendedAction.KEEP_LOCAL
    assert policy.recommend([maskable, result(False)]).action is None
    assert (
        policy.recommend([result(None), result(None, masking_preserves_task=False)]).action
        == RecommendedAction.KEEP_LOCAL
    )


def test_missing_task_evidence_does_not_invent_a_recommended_action():
    recommendation = HeuristicPolicy().recommend([result(None)])
    assert recommendation.action is None
    assert recommendation.reason == "masking_impact_unknown"
    assert HeuristicPolicy().recommend([]).action is None


def test_incomplete_evidence_cannot_downgrade_to_public_or_maskable():
    policy = HeuristicPolicy()
    assert policy.recommend([result(sensitive=True, masking_preserves_task=True), result(False)]).action is None
    for status in ("failed", "partial"):
        for complete in (
            result(True),
            result(None, masking_preserves_task=False),
            result(False, masking_preserves_task=True),
        ):
            recommendation = policy.recommend([complete, DetectionResult(status=status)])
            assert recommendation.action is None
            assert recommendation.reason == "incomplete_analysis"
    with pytest.raises(TypeError):
        policy.recommend([None])


@pytest.mark.parametrize(
    ("required", "masking_preserves_task", "expected"),
    [
        (None, False, RecommendedAction.KEEP_LOCAL),
        (None, True, RecommendedAction.MASK_THEN_SHARE),
        (False, None, None),
        (True, True, RecommendedAction.KEEP_LOCAL),
    ],
)
def test_normalized_detector_outputs_follow_same_policy(required, masking_preserves_task, expected):
    run = LLMDetectorRun(
        run_id=uuid4(),
        detector_id="synthetic-v1",
        adapter_version="synthetic-v1",
        status="complete",
        model_id="local/test",
    )
    entity = PrivacyEntity(
        tag="INTERNAL_PROJECT",
        kind="contextual",
        span="private",
        offsets=(0, 7),
        detection_method="llm",
        run_id=run.run_id,
        confidentiality=ConfidentialityJudgment(value="private", reason="Disclosure assessment"),
        necessity=NecessityJudgment(
            value=None if required is None else "required" if required else "optional",
            reason="Task assessment",
        ),
    )
    evidence = DetectionResult(entities=[entity], detector_runs=[run], masking_preserves_task=masking_preserves_task)
    assert HeuristicPolicy().recommend([result(), evidence]).action == expected


def test_cached_assessment_keeps_session_policy_without_raw_values():
    cache = Cachier()
    key = cache.make_key(namespace="session-a", message="private", history=[], detector_fingerprint="local-v1")
    cache.put(key, result(False, masking_preserves_task=True))
    assert HeuristicPolicy().recommend([result(), cache.get(key)]).action == RecommendedAction.MASK_THEN_SHARE
    cache.put(key, result(None))
    assert HeuristicPolicy().recommend([cache.get(key)]).action is None


def test_alternative_contact_uncertainty_does_not_hide_joint_masking_loss():
    assessment = ExtractionResult(
        **(
            result(None, None).model_dump()
            | {
                "masking_preserves_task": False,
                "masking_reason": "Either contact works, but hiding both prevents delivery.",
            }
        )
    )
    assert HeuristicPolicy().recommend([assessment]).action == RecommendedAction.KEEP_LOCAL


def test_joint_masking_evidence_can_resolve_individual_uncertainty():
    assessment = ExtractionResult(
        **(
            result(None).model_dump()
            | {"masking_preserves_task": True, "masking_reason": "The generic draft needs no original values."}
        )
    )
    assert HeuristicPolicy().recommend([assessment]).action == RecommendedAction.MASK_THEN_SHARE


def test_individual_dispensability_does_not_prove_joint_masking_safe():
    assert HeuristicPolicy().recommend([result(False, False)]).action is None


def test_known_essential_value_blocks_contradictory_joint_masking_permission():
    assessment = result(True, masking_preserves_task=True)
    assert HeuristicPolicy().recommend([assessment]).action == RecommendedAction.KEEP_LOCAL


def test_public_required_items_do_not_require_local_processing_or_joint_masking_evidence():
    policy = HeuristicPolicy()
    public = result(True, confidentiality="public", masking_preserves_task=False)
    assert policy.recommend([public]).action == RecommendedAction.SHARE_ORIGINAL
    private = result(None, masking_preserves_task=True)
    assert policy.recommend([public, private]).action == RecommendedAction.MASK_THEN_SHARE


def test_unassessed_confidentiality_blocks_even_known_joint_masking_and_essential_values():
    policy = HeuristicPolicy()
    unassessed = result(True, confidentiality=None, masking_preserves_task=True)
    recommendation = policy.recommend([unassessed, result(True)])
    assert recommendation.action is None
    assert recommendation.reason == "confidentiality_unassessed"
    incomplete = policy.recommend([unassessed, DetectionResult(status="partial")])
    assert incomplete.action is None
    assert incomplete.reason == "incomplete_analysis"


def test_public_records_do_not_hide_unlocated_sensitive_evidence():
    assessment = result(True, sensitive=True, confidentiality="public", masking_preserves_task=True)
    recommendation = HeuristicPolicy().recommend([assessment])
    assert recommendation.action is None
    assert recommendation.reason == "incomplete_analysis"
