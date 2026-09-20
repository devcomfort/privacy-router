"""Privacy references must not cross context, model or session boundaries."""

from dataclasses import FrozenInstanceError

import pytest

from agents.extractor.schemas import DetectionResult, LLMDetectorRun, PrivacyEntity
from cachier import Cachier
from contracts.annotation import IntentAnnotation
from contracts.extraction import (
    ConfidentialityJudgment,
    ExtractionRecord,
    ExtractionResult,
    NecessityJudgment,
    Sensitivity,
)
from policy import HeuristicPolicy, RecommendedAction

SECRET = "synthetic-confidential-value"


def extraction(
    required: bool | None = False,
    *,
    confidentiality: str | None = "private",
    masking_preserves_task: bool | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        sensitivity=Sensitivity(is_sensitive=confidentiality != "public", rationale=f"Detected {SECRET}"),
        masking_preserves_task=masking_preserves_task,
        masking_reason=f"MASKING_EXPLANATION about {SECRET}",
        records=[
            ExtractionRecord(
                category="CONFIDENTIAL",
                span=SECRET,
                confidence=0.9,
                start=0,
                end=len(SECRET),
                confidentiality=ConfidentialityJudgment(
                    value=confidentiality, reason=f"DISCLOSURE_EXPLANATION about {SECRET}"
                ),
                necessity=NecessityJudgment(
                    value=None if required is None else "required" if required else "optional",
                    reason=f"NECESSITY_EXPLANATION about {SECRET}",
                ),
            )
        ],
    )


def key(cache, *, namespace="session-a", message=SECRET, history=(), fingerprint="detector-v1", intent=None):
    return cache.make_key(
        namespace=namespace, message=message, history=history, detector_fingerprint=fingerprint, intent=intent
    )


def test_hits_are_scoped_by_message_context_session_and_model():
    cache = Cachier()
    original = key(cache, history=("prior",))
    assert cache.get(original) is None
    cache.put(original, extraction())
    assert cache.get(key(cache, history=("prior",))).references[0].necessity == "optional"
    assert cache.get(key(cache, history=("changed",))) is None
    assert cache.get(key(cache, history=("prior",), namespace="session-b")) is None
    assert cache.get(key(cache, history=("prior",), fingerprint="detector-v2")) is None
    assert cache.get(key(cache, history=("prior",), message=SECRET.encode())) is None


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize(
    ("masking_preserves_task", "expected"),
    [
        (False, RecommendedAction.KEEP_LOCAL),
        (True, RecommendedAction.MASK_THEN_SHARE),
        (None, None),
    ],
)
def test_cache_replays_decisions_without_retaining_mutable_results_or_reasoning(
    normalized, masking_preserves_task, expected
):
    cache = Cachier()
    request_key = key(cache)
    original = extraction(None, masking_preserves_task=masking_preserves_task)
    if normalized:
        run = LLMDetectorRun(
            detector_id="synthetic-v1",
            adapter_version="synthetic-v1",
            status="complete",
            model_id="local/test",
        )
        original = DetectionResult(
            entities=[
                PrivacyEntity(
                    tag="CONFIDENTIAL",
                    kind="contextual",
                    span=SECRET,
                    offsets=(0, len(SECRET)),
                    detection_method="llm",
                    run_id=run.run_id,
                    confidentiality=original.records[0].confidentiality,
                    necessity=original.records[0].necessity,
                )
            ],
            detector_runs=[run],
            masking_preserves_task=masking_preserves_task,
            masking_reason=original.masking_reason,
        )
    policy = HeuristicPolicy()
    assert policy.recommend([original]).action == expected
    cache.put(request_key, original)
    cached = cache.get(request_key)
    assert policy.recommend([cached]).action == expected
    assert SECRET not in repr(cached)
    assert "MASKING_EXPLANATION" not in repr(cached)
    assert "DISCLOSURE_EXPLANATION" not in repr(cached)
    assert "NECESSITY_EXPLANATION" not in repr(cached)
    assert not hasattr(cached, "masking_reason")
    original.masking_preserves_task = not masking_preserves_task
    records = original.entities if normalized else original.records
    records[0].necessity = NecessityJudgment(value="required", reason="Changed task assessment")
    records[0].confidentiality = ConfidentialityJudgment(value="public", reason="Changed disclosure assessment")
    assert policy.recommend([cache.get(request_key)]).action == expected
    with pytest.raises(FrozenInstanceError):
        cached.masking_preserves_task = False


def test_failed_or_partial_replacement_evicts_previous_success():
    cache = Cachier()
    request_key = key(cache)
    for status in ("failed", "partial"):
        cache.put(request_key, extraction())
        cache.put(request_key, DetectionResult(status=status))
        assert cache.get(request_key) is None


def test_lru_and_namespace_invalidation_do_not_remove_other_sessions():
    cache = Cachier(max_entries=2)
    first = key(cache, message="one")
    second = key(cache, message="two", namespace="session-b")
    third = key(cache, message="three")
    cache.put(first, extraction())
    cache.put(second, extraction())
    cache.get(first)
    cache.put(third, extraction())
    assert cache.get(second) is None
    assert cache.get(first) is not None
    cache.put(second, extraction())
    assert cache.invalidate("session-a") == 1
    assert cache.get(second) is not None
    cache.clear()
    assert cache.get(second) is None


def test_history_framing_prevents_concatenation_collisions():
    cache = Cachier()
    assert key(cache, history=("ab", "c")) != key(cache, history=("a", "bc"))
    assert key(cache, history=("a", "b")) != key(cache, history=("b", "a"))
    with pytest.raises(ValueError):
        key(cache, namespace=" ")
    with pytest.raises(ValueError):
        key(cache, fingerprint="")


def test_same_source_with_different_intent_cannot_reuse_necessity():
    cache = Cachier()
    draft = IntentAnnotation.for_text(
        SECRET, goal="Compose email", action="Draft", completion_condition="Draft ready", channel="email"
    )
    send = IntentAnnotation.for_text(
        SECRET, goal="Compose email", action="Send", completion_condition="Email delivered", channel="email"
    )
    draft_key = key(cache, intent=draft)
    cache.put(draft_key, extraction(False, masking_preserves_task=True))

    assert cache.get(key(cache, intent=send)) is None
    assert cache.get(key(cache)) is None
    cache.put(key(cache, intent=send), extraction(True, masking_preserves_task=False))
    assert cache.get(draft_key).references[0].necessity == "optional"
    assert cache.get(key(cache, intent=send)).references[0].necessity == "required"
    restored = IntentAnnotation.model_validate_json(draft.model_dump_json())
    assert cache.get(key(cache, intent=restored)).references[0].necessity == "optional"


def test_cache_never_retains_annotation_text():
    cache = Cachier()
    intent = IntentAnnotation.for_text(
        SECRET,
        goal="PRIVATE_GOAL",
        action="PRIVATE_ACTION",
        completion_condition="PRIVATE_COMPLETION",
        channel="PRIVATE_CHANNEL",
        unresolved=("PRIVATE_UNRESOLVED",),
    )
    request_key = key(cache, intent=intent)
    cache.put(request_key, extraction())

    retained = repr(request_key) + repr(cache.get(request_key))
    for private in (SECRET, *intent.model_dump(exclude={"source_hash", "unresolved"}).values(), *intent.unresolved):
        assert private not in retained


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize(
    ("confidentiality", "required", "expected", "reason"),
    [
        ("public", True, RecommendedAction.SHARE_ORIGINAL, "no_sensitive_data"),
        ("private", True, RecommendedAction.KEEP_LOCAL, "masking_loses_meaning"),
        ("private", None, RecommendedAction.MASK_THEN_SHARE, "masking_preserves_task"),
        (None, True, None, "confidentiality_unassessed"),
    ],
)
def test_cache_preserves_public_and_unassessed_judgments(normalized, confidentiality, required, expected, reason):
    original = extraction(required, confidentiality=confidentiality, masking_preserves_task=True)
    if normalized:
        run = LLMDetectorRun(
            detector_id="synthetic-v1",
            adapter_version="synthetic-v1",
            status="complete",
            model_id="local/test",
        )
        original = DetectionResult(
            entities=[
                PrivacyEntity(
                    tag="INFORMATION",
                    kind="contextual",
                    span=SECRET,
                    offsets=(0, len(SECRET)),
                    detection_method="llm",
                    run_id=run.run_id,
                    confidentiality=original.records[0].confidentiality,
                    necessity=original.records[0].necessity,
                )
            ],
            detector_runs=[run],
            masking_preserves_task=True,
        )
    cache = Cachier()
    request_key = key(cache)
    cache.put(request_key, original)
    cached = cache.get(request_key)
    assert cached.references[0].confidentiality == confidentiality
    assert cached.references[0].necessity == (None if required is None else "required")
    assert cached.is_sensitive is (confidentiality != "public")
    for evidence in (original, cached):
        recommendation = HeuristicPolicy().recommend([evidence])
        assert recommendation.action == expected
        assert recommendation.reason == reason


def test_cache_preserves_unlocated_sensitive_evidence_alongside_public_records():
    original = extraction(True, confidentiality="public", masking_preserves_task=True)
    original.sensitivity = Sensitivity(is_sensitive=True, rationale="An unlocated private item was omitted")
    cache = Cachier()
    request_key = key(cache)
    cache.put(request_key, original)
    for evidence in (original, cache.get(request_key)):
        recommendation = HeuristicPolicy().recommend([evidence])
        assert recommendation.action is None
        assert recommendation.reason == "incomplete_analysis"
