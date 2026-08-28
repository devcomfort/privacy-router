from __future__ import annotations

from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from typing import Any

from agents.extractor.lfm_extractor import LFMExtractor

TEXT = "문의: synthetic@example.invalid"


def test_lfm_decoded_span_maps_native_label_and_score():
    def predictor(_: str) -> list[dict[str, object]]:
        return [{"label": "contact.email", "start": 4, "end": 29, "score": 0.91}]

    result = LFMExtractor(
        predictor=predictor,
        model_revision="hf-revision",
        decoder_revision="decoder-revision",
    ).extract(TEXT)

    entity = result.entities[0]
    run = result.detector_runs[0]
    assert result.status == "complete"
    assert entity.tag == "EMAIL"
    assert entity.native_label == "contact.email"
    assert entity.span == "synthetic@example.invalid"
    assert entity.confidence == 0.91
    assert run.detector_type == "lfm"
    assert run.model_revision == "hf-revision"
    assert run.decoder_revision == "decoder-revision"


def test_lfm_import_failure_is_a_failed_run_not_a_clean_negative():
    def unavailable(_: str) -> list[dict[str, Any]]:
        raise ImportError("transformers unavailable")

    result = LFMExtractor(predictor=unavailable).extract("synthetic")

    assert result.status == "failed"
    assert result.entities == []
    assert result.detector_runs[0].status == "failed"
    assert result.detector_runs[0].error_code == "LFM_BACKEND_ERROR"


def test_lfm_empty_prediction_is_complete():
    result = LFMExtractor(predictor=lambda _: []).extract("no sensitive data")

    assert result.status == "complete"
    assert result.entities == []
    assert result.detector_runs[0].status == "complete"


def test_lfm_default_loader_pins_revision_and_enables_trusted_code(monkeypatch):
    import sys

    revision = "b8c9cf3d2d6ae52501b35a27ba46f271449c9ce2"
    downloads: list[tuple[str, str, str | None]] = []
    tokenizer_calls: list[dict[str, Any]] = []
    model_calls: list[dict[str, Any]] = []

    huggingface_hub = ModuleType("huggingface_hub")

    def hf_hub_download(repo_id: str, filename: str, revision: str | None = None) -> str:
        downloads.append((repo_id, filename, revision))
        return "/tmp/lfm/pii_hybrid_decode.py"

    huggingface_hub.hf_hub_download = hf_hub_download

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> FakeTokenizer:
            tokenizer_calls.append(kwargs)
            return cls()

    class FakeModel:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> FakeModel:
            model_calls.append(kwargs)
            return cls()

        def to(self, device: str) -> FakeModel:
            assert device == "cpu"
            return self

        def eval(self) -> None:
            return None

    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = FakeTokenizer
    transformers.AutoModelForTokenClassification = FakeModel
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_hub)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    class FakeLoader:
        def create_module(self, spec: object) -> None:
            return None

        def exec_module(self, module: ModuleType) -> None:
            module.predict = lambda text, tokenizer, model: []
    helper_module = ModuleType("privacy_router_lfm_decoder")
    monkeypatch.setattr(
        "agents.extractor.lfm_extractor.importlib.util.module_from_spec",
        lambda spec: helper_module,
    )

    monkeypatch.setattr(
        "agents.extractor.lfm_extractor.importlib.util.spec_from_file_location",
        lambda name, location: SimpleNamespace(name=name, loader=FakeLoader()),
    )

    extractor = LFMExtractor()
    extractor._load_predictor()

    assert downloads == [
        (extractor._model_id, "pii_hybrid_decode.py", revision),
        (extractor._model_id, "context_cued.py", revision),
    ]
    assert tokenizer_calls == [{"revision": revision, "trust_remote_code": True}]
    assert model_calls == [{"revision": revision, "trust_remote_code": True}]


def test_lfm_loader_is_cached_between_extract_calls(monkeypatch):
    calls = 0
    extractor = LFMExtractor()

    def load_predictor() -> Callable[[str], list[dict[str, object]]]:
        nonlocal calls
        calls += 1

        def predict(_: str) -> list[dict[str, object]]:
            return []

        return predict

    monkeypatch.setattr(extractor, "_load_predictor", load_predictor)

    first = extractor.extract("no sensitive data")
    second = extractor.extract("still no sensitive data")

    assert first.status == "complete"
    assert second.status == "complete"
    assert calls == 1
