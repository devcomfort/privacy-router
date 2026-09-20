"""Observable router transitions, safe replay and failure boundaries."""

from dataclasses import FrozenInstanceError, asdict

import pytest

from cachier import Cachier
from contracts import (
    ConfidentialityJudgment,
    ExtractionRecord,
    ExtractionResult,
    IntentAnnotation,
    NecessityJudgment,
    Sensitivity,
)
from masker import Masker
from policy import RecommendedAction
from router import PrivacyRouter, RoutingError

TEXT = "  가상값 / 가상값  "


def intent(text=TEXT):
    return IntentAnnotation.for_text(
        text, goal="Prepare a generic draft", action="Draft", completion_condition="Draft only"
    )


def evidence(required=False):
    return ExtractionResult(
        sensitivity=Sensitivity(is_sensitive=True, rationale="synthetic"),
        masking_preserves_task=not required if required is not None else None,
        masking_reason="Private whole-source masking explanation",
        records=[
            ExtractionRecord(
                category="PRIVATE_VALUE",
                span="가상값",
                confidence=0.99,
                start=2,
                end=5,
                confidentiality=ConfidentialityJudgment(value="private", reason="A private example value"),
                necessity=NecessityJudgment(
                    value=None if required is None else "required" if required else "optional", reason="synthetic task"
                ),
            )
        ],
    )


class Annotation:
    def annotate(self, text):
        return intent(text)


class Extraction:
    def extract(self, text, *, intent):
        return evidence()


def make_router(**kwargs):
    return PrivacyRouter(
        annotator=kwargs.pop("annotator", Annotation()),
        extractor=kwargs.pop("extractor", Extraction()),
        cache=kwargs.pop("cache", Cachier()),
        detector_fingerprint="router-test",
        **kwargs,
    )


def test_events_arrive_before_work_and_cache_skips_inference():
    events = []

    class ObservedAnnotation(Annotation):
        def annotate(self, text):
            assert (events[-1].stage, events[-1].state) == ("annotation", "started")
            return super().annotate(text)

    class ObservedExtraction(Extraction):
        def extract(self, text, *, intent):
            assert (events[-1].stage, events[-1].state) == ("extraction", "started")
            return super().extract(text, intent=intent)

    router = make_router(annotator=ObservedAnnotation(), extractor=ObservedExtraction())
    first = router.route(TEXT, namespace="a", on_status=events.append)
    assert first.recommendation.action == RecommendedAction.MASK_THEN_SHARE
    assert "가상값" not in first.masking.masked_text
    assert first.hydration.hydrated_text == TEXT
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert len({event.run_id for event in events}) == 1
    assert all(a.elapsed_ms <= b.elapsed_ms for a, b in zip(events, events[1:], strict=False))
    assert (events[-1].stage, events[-1].state) == ("run", "completed")
    assert "가상값" not in str([asdict(event) for event in events])
    assert "Private whole-source masking explanation" not in str([asdict(event) for event in events])
    with pytest.raises(FrozenInstanceError):
        events[0].stage = "changed"

    replay_events = []
    # The observed dependencies would fail their started-event assertions if replay invoked either.
    replay = router.route(TEXT, namespace="a", intent=first.intent, on_status=replay_events.append)
    assert replay.cache_hit
    assert replay.recommendation == first.recommendation
    assert replay.hydration.hydrated_text == TEXT
    assert {(event.stage, event.state, event.detail) for event in replay_events} >= {
        ("annotation", "skipped", "intent_provided"),
        ("extraction", "skipped", "cache_hit"),
    }
    assert replay_events[0].run_id != events[0].run_id
    assert all(record.confidentiality.reason is None and record.necessity.reason is None for record in replay.records)
    assert replay.masking_reason is None


def test_model_failure_emits_failed_stage_without_leaking_diagnostics_or_caching():
    class BrokenExtraction:
        def extract(self, *args, **kwargs):
            raise RuntimeError("private transport diagnostic")

    cache = Cachier()
    events = []
    with pytest.raises(RoutingError) as failure:
        make_router(extractor=BrokenExtraction(), cache=cache).route(TEXT, namespace="a", on_status=events.append)
    assert failure.value.stage == "extraction"
    assert "private" not in str(failure.value)
    assert [(event.stage, event.state) for event in events[-2:]] == [("extraction", "failed"), ("run", "failed")]
    assert not any(event.stage == "policy" for event in events)
    assert len(cache) == 0


def test_observer_failure_stops_before_sensitive_work_and_propagates_original():
    disconnected = BrokenPipeError("observer disconnected")

    def observer(event):
        if event.stage == "annotation":
            raise disconnected

    class MustNotAnalyze:
        def annotate(self, text):
            pytest.fail("Annotation started after observer disconnected")

    with pytest.raises(BrokenPipeError) as failure:
        make_router(annotator=MustNotAnalyze()).route(TEXT, namespace="a", on_status=observer)
    assert failure.value is disconnected


def test_source_mismatch_fails_before_annotation_or_extraction():
    events = []
    with pytest.raises(RoutingError) as failure:
        make_router().route(TEXT + " ", namespace="a", intent=intent(), on_status=events.append)
    assert failure.value.stage == "validation"
    assert not any(event.stage in {"annotation", "extraction"} for event in events)


def test_overlapping_spans_mask_their_union_and_all_repeats():
    text = "abcde / abcde"

    class Overlap:
        def extract(self, text, *, intent):
            return ExtractionResult(
                sensitivity=Sensitivity(is_sensitive=True, rationale="synthetic"),
                records=[
                    ExtractionRecord(
                        category="PRIVATE",
                        span=span,
                        start=start,
                        end=end,
                        confidence=1,
                        confidentiality=ConfidentialityJudgment(
                            value="private", reason="Private overlapping information"
                        ),
                        necessity=NecessityJudgment(value="optional", reason="generic task"),
                    )
                    for span, start, end in [("abc", 0, 3), ("cde", 2, 5)]
                ],
            )

    result = make_router(extractor=Overlap()).route(text, namespace="a")
    assert "abc" not in result.masking.masked_text and "cde" not in result.masking.masked_text
    assert result.hydration.hydrated_text == text
    assert len(result.records) == 2


def test_invalid_cached_span_cannot_be_shared_or_reused():
    cache = Cachier()
    annotation = intent()
    key = cache.make_key(namespace="a", message=TEXT, history=(), detector_fingerprint="router-test", intent=annotation)
    wrong = evidence()
    wrong.records[0].span = "different"
    cache.put(key, wrong)
    with pytest.raises(RoutingError) as failure:
        make_router(cache=cache).route(TEXT, namespace="a", intent=annotation)
    assert failure.value.stage == "cache"
    assert cache.get(key) is None


def test_hydration_failure_never_commits_assessment_or_completes_run():
    class BrokenMasker(Masker):
        def hydrate(self, text, contract):
            raise RuntimeError("restore failure")

    cache = Cachier()
    events = []
    with pytest.raises(RoutingError) as failure:
        make_router(cache=cache, masker=BrokenMasker()).route(TEXT, namespace="a", on_status=events.append)
    assert failure.value.stage == "masking"
    assert len(cache) == 0
    assert (events[-1].stage, events[-1].state) == ("run", "failed")


def test_cache_commit_failure_does_not_retract_a_completed_stage():
    class FailedCommit(Cachier):
        def put(self, key, result):
            raise RuntimeError("private storage failure")

    events = []
    with pytest.raises(RoutingError) as failure:
        make_router(cache=FailedCommit()).route(TEXT, namespace="a", on_status=events.append)
    assert failure.value.stage == "run"
    assert (events[-1].stage, events[-1].state) == ("run", "failed")
    terminals = [(event.stage, event.state) for event in events if event.state != "started"]
    assert len({stage for stage, state in terminals}) == len(terminals)


def test_public_required_record_remains_visible_and_unmasked_on_replay():
    class PublicExtraction:
        def extract(self, text, *, intent):
            return ExtractionResult.model_validate(
                {
                    "sensitivity": {"is_sensitive": False, "rationale": "Public information"},
                    "masking_preserves_task": True,
                    "records": [
                        {
                            "category": "PUBLIC_VALUE",
                            "span": "가상값",
                            "start": 2,
                            "end": 5,
                            "confidence": 1,
                            "confidentiality": {"value": "public", "reason": "A published example value"},
                            "necessity": {"value": "required", "reason": "The request is about this exact example"},
                        }
                    ],
                }
            )

    router = make_router(extractor=PublicExtraction())
    first = router.route(TEXT, namespace="public")
    replay = router.route(TEXT, namespace="public", intent=first.intent)
    for result in (first, replay):
        assert result.recommendation.action == RecommendedAction.SHARE_ORIGINAL
        assert result.masking.masked_text == TEXT
        assert result.hydration.hydrated_text == TEXT
        assert len(result.records) == 1
        assert result.records[0].confidentiality.value == "public"
        assert result.records[0].necessity.value == "required"


def test_unassessed_confidentiality_blocks_sharing_and_protects_value_on_replay():
    class UnassessedExtraction:
        def extract(self, text, *, intent):
            record = (
                evidence()
                .records[0]
                .model_copy(
                    update={
                        "confidentiality": ConfidentialityJudgment(value=None, reason="Publication context is missing"),
                        "necessity": NecessityJudgment(
                            value="optional", reason="A generic draft does not need the value"
                        ),
                    }
                )
            )
            return ExtractionResult(
                sensitivity=Sensitivity(is_sensitive=False, rationale="No confirmed private label"),
                records=[record],
                masking_preserves_task=True,
            )

    router = make_router(extractor=UnassessedExtraction())
    first = router.route(TEXT, namespace="unassessed")
    replay = router.route(TEXT, namespace="unassessed", intent=first.intent)
    for result in (first, replay):
        assert result.recommendation.action is None
        assert result.recommendation.reason == "confidentiality_unassessed"
        assert result.records[0].confidentiality.value is None
        assert result.records[0].confidentiality.status == "unassessed"
        assert result.records[0].necessity.value == "optional"
        assert "가상값" not in result.masking.masked_text
        assert result.hydration.hydrated_text == TEXT
