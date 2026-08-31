from __future__ import annotations

from types import SimpleNamespace

from agents.extractor.schemas import ExtractionResult, Sensitivity
from agents.router import router as router_module


class FakeExtractor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract(self, text: str) -> ExtractionResult:
        self.calls.append(text)
        return ExtractionResult(sensitivity=Sensitivity(is_sensitive=False, rationale="clean"), records=[])


def test_privacy_router_reuses_extractor_for_multiple_process_calls(monkeypatch):
    config = SimpleNamespace(
        decision=SimpleNamespace(model="local/decision", api_base="http://127.0.0.1:8000/v1"),
    )
    extractor = FakeExtractor()
    created: list[dict[str, object]] = []

    def extractor_factory(**kwargs: object) -> FakeExtractor:
        created.append(kwargs)
        return extractor

    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(router_module, "resolve_local_api_base", lambda *_args: config.decision.api_base)
    monkeypatch.setattr(router_module, "Extractor", extractor_factory)

    privacy_router = router_module.PrivacyRouter()
    privacy_router.process("first")
    privacy_router.process("second")

    assert len(created) == 1
    assert extractor.calls == ["first", "second"]
