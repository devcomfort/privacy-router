from __future__ import annotations

import pytest

from agents.extractor.registry import DetectorRegistry, PrivacyExtractor
from agents.extractor.schemas import DetectionResult


class FakeDetector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract(self, text: str) -> DetectionResult:
        self.calls.append(text)
        return DetectionResult(status="complete")


def test_registry_dispatches_to_named_detector():
    detector = FakeDetector()
    registry = DetectorRegistry({"llm": detector})

    result = registry.extract("llm", "synthetic")

    assert result.status == "complete"
    assert detector.calls == ["synthetic"]


def test_registry_rejects_unknown_detector():
    with pytest.raises(KeyError, match="missing"):
        DetectorRegistry({}).extract("missing", "synthetic")


def test_registry_rejects_non_detector_registration():
    with pytest.raises(TypeError):
        DetectorRegistry({"bad": object()})


def test_registry_lists_registered_names():
    registry = DetectorRegistry({"presidio": FakeDetector(), "llm": FakeDetector()})

    assert registry.names() == ("llm", "presidio")


def test_new_detector_contract_is_publicly_exported():
    from agents.extractor import (
        ConfidentialityJudgment,
        DetectionResult,
        DetectorRegistry,
        LFMExtractor,
        LLMExtractor,
        NecessityJudgment,
        OPFExtractor,
        PresidioExtractor,
        PrivacyEntity,
    )

    assert all(
        item is not None
        for item in (
            DetectionResult,
            DetectorRegistry,
            LFMExtractor,
            LLMExtractor,
            OPFExtractor,
            PresidioExtractor,
            PrivacyEntity,
            ConfidentialityJudgment,
            NecessityJudgment,
        )
    )


assert isinstance(FakeDetector(), PrivacyExtractor)


def test_root_agents_exports_new_detector_contract():
    from agents import DetectionResult, LFMExtractor, LLMExtractor, OPFExtractor, PresidioExtractor, PrivacyEntity

    assert DetectionResult is not None
    assert PrivacyEntity is not None
    assert LLMExtractor is not None
    assert PresidioExtractor is not None
    assert OPFExtractor is not None
    assert LFMExtractor is not None
