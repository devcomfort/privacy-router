from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.extractor.presidio import PresidioExtractor

TEXT = "문의: synthetic@example.invalid"


@dataclass
class FakeRecognizer:
    name: str
    identifier: str
    version: str = "1"


@dataclass
class FakePresidioResult:
    entity_type: str
    start: int
    end: int
    score: float
    analysis_explanation: object | None = None
    recognition_metadata: dict[str, str] | None = None


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_recognizers(
        self,
        *,
        language: str,
        entities: list[str] | None = None,
        all_fields: bool = False,
    ) -> list[FakeRecognizer]:
        self.calls.append({"language": language, "entities": entities, "all_fields": all_fields})
        return [FakeRecognizer("EmailRecognizer", "email_recognizer")]


class FakeAnalyzer:
    def __init__(self, results: list[FakePresidioResult]) -> None:
        self.registry = FakeRegistry()
        self.results = results
        self.calls: list[dict[str, Any]] = []

    def analyze(self, **kwargs: Any) -> list[FakePresidioResult]:
        self.calls.append(kwargs)
        return self.results


def test_presidio_result_maps_entity_and_recognizer_metadata():
    analyzer = FakeAnalyzer(
        [
            FakePresidioResult(
                entity_type="EMAIL_ADDRESS",
                start=4,
                end=29,
                score=0.85,
                analysis_explanation={"textual_explanation": "Email recognizer match"},
                recognition_metadata={
                    "recognizer_name": "EmailRecognizer",
                    "recognizer_identifier": "email_recognizer",
                },
            )
        ]
    )

    result = PresidioExtractor(analyzer=analyzer, language="ko").extract(TEXT)

    entity = result.entities[0]
    assert result.status == "complete"
    assert entity.tag == "EMAIL"
    assert entity.native_label == "EMAIL_ADDRESS"
    assert entity.native_metadata["recognizer_name"] == "EmailRecognizer"
    assert entity.confidentiality.value == "private"
    assert entity.necessity.value is None
    assert result.detector_runs[0].configured_recognizers[0].name == "EmailRecognizer"
    assert analyzer.calls[0]["language"] == "ko"
    assert analyzer.calls[0]["return_decision_process"] is True
    assert analyzer.registry.calls[0] == {"language": "ko", "entities": None, "all_fields": True}


def test_presidio_failure_is_a_failed_run():
    class BrokenAnalyzer(FakeAnalyzer):
        def analyze(self, **kwargs: Any) -> list[FakePresidioResult]:
            raise RuntimeError("presidio unavailable")

    result = PresidioExtractor(analyzer=BrokenAnalyzer([])).extract(TEXT)

    assert result.status == "failed"
    assert result.entities == []
    assert result.detector_runs[0].status == "failed"
    assert result.detector_runs[0].error_code == "PRESIDIO_BACKEND_ERROR"


def test_presidio_loader_is_cached_between_extract_calls(monkeypatch):
    calls = 0
    analyzer = FakeAnalyzer([])
    extractor = PresidioExtractor()

    def load_analyzer() -> FakeAnalyzer:
        nonlocal calls
        calls += 1
        return analyzer

    monkeypatch.setattr(extractor, "_load_analyzer", load_analyzer)

    first = extractor.extract("no sensitive data")
    second = extractor.extract("still no sensitive data")

    assert first.status == "complete"
    assert second.status == "complete"
    assert calls == 1
