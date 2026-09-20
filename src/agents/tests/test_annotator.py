"""Behavioral boundaries for source-bound intent and local-only analysis."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.annotator import IntentAnalysisUnavailable, IntentAnalyzer
from contracts import IntentAnnotation

_CONTENT = {
    "goal": "Notify the recipient of the result",
    "action": "Send the result",
    "completion_condition": "The recipient receives the result through the selected channel",
    "channel": None,
    "unresolved": ("The delivery channel has not been selected",),
}


def test_annotation_binds_exact_source_without_normalization():
    annotation = IntentAnnotation.for_text("abc", **_CONTENT)
    assert annotation.source_hash == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert annotation.matches_source("abc")
    assert not annotation.matches_source("abc\n")
    unicode_annotation = IntentAnnotation.for_text("  한글\r\n", **_CONTENT)
    assert unicode_annotation.matches_source("  한글\r\n")
    assert not unicode_annotation.matches_source("한글\n")


def test_annotation_cannot_change_through_assignment_or_caller_list():
    unresolved = ["Channel undecided"]
    annotation = IntentAnnotation.for_text("abc", **(_CONTENT | {"unresolved": unresolved}))
    fingerprint = annotation.fingerprint()
    unresolved.append("Caller mutation")
    assert annotation.unresolved == ("Channel undecided",)
    with pytest.raises(ValidationError):
        annotation.channel = "email"
    assert annotation.fingerprint() == fingerprint


def test_annotation_fingerprint_tracks_source_and_intent_not_json_key_order():
    annotation = IntentAnnotation.for_text("abc", **_CONTENT)
    reordered = IntentAnnotation.model_validate(dict(reversed(list(annotation.model_dump().items()))))
    assert reordered.fingerprint() == annotation.fingerprint()
    assert IntentAnnotation.for_text("abcd", **_CONTENT).fingerprint() != annotation.fingerprint()
    assert (
        IntentAnnotation.for_text("abc", **(_CONTENT | {"channel": "email"})).fingerprint() != annotation.fingerprint()
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"goal": " \t\n"},
        {"unresolved": ("",)},
        {"unresolved": ("Undecided",) * 13},
        {"source_hash": "ABC"},
        {"authorized": True},
    ],
)
def test_annotation_rejects_invalid_evidence(invalid):
    valid = IntentAnnotation.for_text("abc", **_CONTENT).model_dump()
    with pytest.raises(ValidationError):
        IntentAnnotation.model_validate(valid | invalid)


def test_analyzer_binds_valid_intent_locally_in_one_call():
    calls = 0

    def respond(messages, response_model, **kwargs):
        nonlocal calls
        calls += 1
        return response_model(**_CONTENT)

    text = "  user: 연락처 중 어떤 채널로 보낼지는 아직 정하지 않았어.\r\n"
    annotation = IntentAnalyzer(call_structured=respond).annotate(text)
    assert annotation.matches_source(text)
    assert not annotation.matches_source(text.strip())
    assert annotation.channel is None
    assert annotation.unresolved == _CONTENT["unresolved"]
    assert calls == 1


@pytest.mark.parametrize("invalid", [None, {}, _CONTENT | {"goal": " "}, _CONTENT | {"source_hash": "0" * 64}])
def test_analyzer_rejects_missing_invalid_or_model_supplied_binding(invalid):
    analyzer = IntentAnalyzer(call_structured=lambda *args, **kwargs: invalid)
    with pytest.raises(IntentAnalysisUnavailable):
        analyzer.annotate("private source")


def test_model_failure_exposes_no_sensitive_diagnostic():
    def unavailable(*args, **kwargs):
        raise TimeoutError("private source and transport secret")

    with pytest.raises(IntentAnalysisUnavailable) as error:
        IntentAnalyzer(call_structured=unavailable).annotate("private source")
    assert "private source" not in str(error.value)
    assert "transport secret" not in str(error.value)


def test_untrusted_external_endpoint_is_rejected_before_source_can_leave(monkeypatch):
    monkeypatch.delenv("PRIVACY_ROUTER_TRUSTED_LOCAL_MODEL_HOSTS", raising=False)

    def must_not_call(*args, **kwargs):
        pytest.fail("Untrusted endpoint received source text")

    with pytest.raises(ValueError):
        IntentAnalyzer(api_base="https://untrusted.example/v1", call_structured=must_not_call).annotate(
            "private source"
        )


def test_empty_source_cannot_produce_an_annotation():
    def must_not_call(*args, **kwargs):
        pytest.fail("Empty source reached inference")

    with pytest.raises(ValueError):
        IntentAnalyzer(call_structured=must_not_call).annotate(" \t\n")
