from __future__ import annotations

from types import SimpleNamespace

from agents.extractor.opf_extractor import OPFExtractor

TEXT = "문의: synthetic@example.invalid"


class FakeOPF:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def redact(self, text: str) -> dict[str, object]:
        self.calls.append(text)
        return self.payload


def opf_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "text": TEXT,
        "detected_spans": [
            {
                "label": "private_email",
                "start": 4,
                "end": 29,
                "text": "synthetic@example.invalid",
                "placeholder": "<PRIVATE_EMAIL>",
            }
        ],
        "redacted_text": "문의: <PRIVATE_EMAIL>",
    }


def test_opf_typed_spans_map_to_project_tags_without_using_redacted_text():
    opf = FakeOPF(opf_payload())

    result = OPFExtractor(opf=opf).extract(TEXT)

    entity = result.entities[0]
    assert result.status == "complete"
    assert entity.tag == "EMAIL"
    assert entity.native_label == "private_email"
    assert entity.span == "synthetic@example.invalid"
    assert entity.native_metadata["placeholder"] == "<PRIVATE_EMAIL>"
    assert "redacted_text" not in entity.native_metadata
    assert opf.calls == [TEXT]


def test_opf_failure_is_a_failed_run():
    class BrokenOPF(FakeOPF):
        def redact(self, text: str) -> dict[str, object]:
            raise RuntimeError("opf unavailable")

    result = OPFExtractor(opf=BrokenOPF(opf_payload())).extract(TEXT)

    assert result.status == "failed"
    assert result.entities == []
    assert result.detector_runs[0].detector_type == "opf"
    assert result.detector_runs[0].error_code == "OPF_BACKEND_ERROR"


def test_opf_accepts_json_string_from_cli_boundary():
    class JsonOPF(FakeOPF):
        def redact(self, text: str) -> str:
            import json

            return json.dumps(self.payload)

    result = OPFExtractor(opf=JsonOPF(opf_payload())).extract(TEXT)

    assert result.entities[0].tag == "EMAIL"


def test_opf_loader_is_cached_between_extract_calls(monkeypatch):
    calls = 0
    opf = FakeOPF(opf_payload())
    extractor = OPFExtractor()

    def load_opf() -> FakeOPF:
        nonlocal calls
        calls += 1
        return opf

    monkeypatch.setattr(extractor, "_load_opf", load_opf)

    first = extractor.extract(TEXT)
    second = extractor.extract(TEXT)

    assert first.status == "complete"
    assert second.status == "complete"
    assert calls == 1


def test_injected_opf_decode_mode_is_preserved_in_provenance():
    opf = FakeOPF(opf_payload())
    opf._decoder_config = SimpleNamespace(decode_mode="argmax")

    result = OPFExtractor(opf=opf, decode_mode="viterbi").extract(TEXT)

    assert result.detector_runs[0].decode_mode == "argmax"
