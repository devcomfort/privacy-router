"""Offline native data manipulation experiment (not a serializer benchmark).

Run from repository root:
  uv run --no-project --isolated --with-requirements \
    spikes/chat-format-versions/manipulation-requirements.txt \
    python spikes/chat-format-versions/probes/probe_manipulation.py \
    --output spikes/chat-format-versions/manipulation-results.json

JSON below is experiment reporting only; payloads never take a JSON roundtrip.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path as FilePath
from time import perf_counter_ns
from typing import Any

from manipulation.core import Patch, Slot, Step, path_label
from manipulation.engines import COPY_POLICY, EDITOR_NAMES, SOURCES, make_editor
from manipulation.evidence import capture, different_paths, expected_changes
from manipulation.fixtures import SDK_SOURCES, Case, build_cases
from manipulation.native import ADAPTER_RANGES, UnsupportedEdit, select_adapter
from pydantic import BaseModel, ConfigDict, PrivateAttr

PROVIDERS = ("openai", "anthropic", "litellm", "langchain-core")


def item(*keys: str | int) -> tuple[Step, ...]:
    return tuple(Step("item", key) for key in keys)


def exercise(provider: str, engine: str, case: Case) -> dict[str, Any]:
    adapter = select_adapter(provider, make_editor(engine))
    before = capture(case.payload)
    started = perf_counter_ns()
    slots = adapter.extract(case.payload)
    by_path = {slot.path: slot for slot in slots}
    result: dict[str, Any] = {
        "case": case.name,
        "provider": provider,
        "editor": engine,
        "slots": len(slots),
        "categories": dict(Counter(slot.category for slot in slots)),
        "restricted_or_uninterpreted": [
            {"path": path_label(slot.path), "editable": slot.editable, "note": slot.note} for slot in slots if slot.note
        ],
    }
    try:
        assert adapter.apply(case.payload, []) is case.payload, "No-op must preserve original identity"
        for path, category in case.required_categories.items():
            assert path in by_path, f"Required native value was not exposed: {path_label(path)}"
            assert by_path[path].category == category, (
                f"Category mismatch: {path_label(path)} expected {category}, got {by_path[path].category}"
            )
        for path in case.protected_paths:
            assert path in by_path and not by_path[path].editable, (
                f"Protected native data is editable: {path_label(path)}"
            )
        patches = [Patch(by_path[path], replacement) for path, replacement in case.edits.items()]
        for patch in patches:
            assert adapter.editor.get(case.payload, patch.slot.path) == patch.slot.value, (
                "Editor extraction did not read native value"
            )
        updated = adapter.apply(case.payload, patches)
        output_diff = different_paths(expected_changes(before, case.edits), capture(updated))
        input_diff = different_paths(before, capture(case.payload))
        result.update(
            {
                "status": "preserved" if not output_diff and not input_diff else "changed_unselected_data",
                "changed_paths": [path_label(path) for path in case.edits],
                "unexpected_output_changes": output_diff,
                "unexpected_source_changes": input_diff,
                "no_op_identity": True,
            }
        )
    except Exception as exc:
        result.update(
            {
                "status": "unsupported",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "unexpected_source_changes": different_paths(before, capture(case.payload)),
            }
        )
    result["elapsed_ms"] = round((perf_counter_ns() - started) / 1_000_000, 3)
    return result


def boundary_cases(handle: Any) -> list[Case]:
    class WithPrivateState(BaseModel):
        model_config = ConfigDict(extra="allow")
        content: str = "default text"
        _runtime: Any = PrivateAttr(default_factory=object)

    class FrozenData(BaseModel):
        model_config = ConfigDict(frozen=True)
        content: str

    text_path = item("messages", 0, "content")

    def request(**extras: Any) -> dict:
        return {"messages": [{"role": "user", "content": "synthetic original"}], **extras}

    return [
        Case(
            "tuple_item_and_literal_keys",
            request(metadata={"pair": ("original", 7), "a.b": {9: "original"}}),
            {item("metadata", "pair", 0): "changed", item("metadata", "a.b", 9): "changed"},
            {},
        ),
        Case("opaque_identity_unedited", request(extra_payload=object()), {text_path: "changed"}, {}),
        Case(
            "open_file_identity_and_position",
            request(attachment=("synthetic.bin", handle, "application/octet-stream")),
            {text_path: "changed"},
            {},
        ),
        Case(
            "private_state_and_omitted_field",
            WithPrivateState(model_dump="uninterpreted extra"),
            {(Step("attr", "content"),): "changed"},
            {},
        ),
        Case(
            "extra_field_colliding_with_method",
            WithPrivateState(model_dump="uninterpreted extra"),
            {(Step("attr", "__pydantic_extra__"), Step("item", "model_dump")): "changed"},
            {},
        ),
        Case("frozen_model", FrozenData(content="original"), {(Step("attr", "content"),): "changed"}, {}),
    ]


def guard_scenarios(engine: str) -> list[dict[str, Any]]:
    adapter = select_adapter("openai", make_editor(engine))
    cases = []

    def check(name: str, payload: Any, make_patches) -> None:
        before = capture(payload)
        try:
            adapter.apply(payload, make_patches(adapter.extract(payload)))
        except (UnsupportedEdit, ValueError):
            cases.append(
                {
                    "case": name,
                    "editor": engine,
                    "rejected": True,
                    "source_unchanged": not different_paths(before, capture(payload)),
                }
            )
        else:
            cases.append(
                {
                    "case": name,
                    "editor": engine,
                    "rejected": False,
                    "source_unchanged": not different_paths(before, capture(payload)),
                }
            )

    def root() -> dict:
        return {"messages": [{"role": "user", "content": "original"}]}

    target = item("messages", 0, "content")

    def choose(slots):
        return next(slot for slot in slots if slot.path == target)

    check(
        "invalid_second_edit_is_atomic",
        root(),
        lambda slots: [Patch(choose(slots), "changed"), Patch(Slot(item("missing"), "text", "original"), "changed")],
    )
    check("native_type_change_rejected", root(), lambda slots: [Patch(choose(slots), b"changed")])
    check("stale_value_rejected", root(), lambda slots: [Patch(Slot(target, "text", "stale"), "changed")])
    check(
        "duplicate_edit_rejected", root(), lambda slots: [Patch(choose(slots), "first"), Patch(choose(slots), "second")]
    )
    check(
        "role_control_rejected",
        root(),
        lambda slots: [Patch(next(slot for slot in slots if slot.path == item("messages", 0, "role")), "assistant")],
    )
    arguments = item("messages", 0, "tool_calls", 0, "function", "arguments")
    tool_payload = {
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "weather", "arguments": '{ "city": "Seoul" }'},
                    }
                ],
            }
        ]
    }
    check(
        "invalid_json_argument_rejected",
        tool_payload,
        lambda slots: [Patch(next(slot for slot in slots if slot.path == arguments), '{"city":')],
    )
    shared = root()
    shared["alias"] = shared["messages"][0]
    check("shared_mutable_graph_explicitly_rejected", shared, lambda slots: [Patch(choose(slots), "changed")])
    cyclic = root()
    cyclic["self"] = cyclic
    check("cyclic_graph_explicitly_rejected", cyclic, lambda slots: [Patch(choose(slots), "changed")])
    return cases


def benchmark(provider: str, engine: str, case: Case) -> dict:
    adapter = select_adapter(provider, make_editor(engine))
    slots = {slot.path: slot for slot in adapter.extract(case.payload)}
    patches = [Patch(slots[path], value) for path, value in case.edits.items()]
    before = capture(case.payload)
    iterations = 30
    started = perf_counter_ns()
    for _ in range(iterations):
        adapter.apply(case.payload, patches)
    return {
        "provider": provider,
        "editor": engine,
        "case": case.name,
        "iterations": iterations,
        "mean_ms": round((perf_counter_ns() - started) / iterations / 1_000_000, 4),
        "source_unchanged": not different_paths(before, capture(case.payload)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=FilePath, required=True)
    args = parser.parse_args()
    observations = []
    timings = []
    for provider in PROVIDERS:
        for engine in EDITOR_NAMES:
            for case in build_cases(provider):
                observations.append(exercise(provider, engine, case))
            first = build_cases(provider)[0]
            if (
                next(
                    row
                    for row in observations
                    if row["provider"] == provider and row["editor"] == engine and row["case"] == first.name
                )["status"]
                == "preserved"
            ):
                timings.append(benchmark(provider, engine, first))
    boundaries = []
    with tempfile.TemporaryFile() as handle:
        handle.write(b"synthetic attachment bytes")
        handle.seek(5)
        for engine in EDITOR_NAMES:
            for case in boundary_cases(handle):
                row = exercise("openai", engine, case)
                row["file_position_unchanged"] = handle.tell() == 5
                boundaries.append(row)
    guards = [row for engine in EDITOR_NAMES for row in guard_scenarios(engine)]
    version_checks = []
    for provider in PROVIDERS:
        for unsupported in ("0.0.0", "999.0.0"):
            try:
                select_adapter(provider, make_editor("lenses"), installed_version=unsupported)
            except UnsupportedEdit:
                version_checks.append({"provider": provider, "version": unsupported, "rejected": True})
            else:
                version_checks.append({"provider": provider, "version": unsupported, "rejected": False})
    directory = FilePath(__file__).parent
    sources = [FilePath(__file__), *sorted((directory / "manipulation").glob("*.py"))]
    source_info = {
        str(path.relative_to(directory.parent)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "nonblank_noncomment_lines": sum(
                bool(line.strip()) and not line.lstrip().startswith("#") for line in path.read_text().splitlines()
            ),
        }
        for path in sources
    }
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "os": platform.system(),
            "architecture": platform.machine(),
            "packages": {
                package: version(package) for package in (*PROVIDERS, "pydantic", "glom", "lenses", "packaging")
            },
        },
        "scope": {
            "goal": "Extract native leaves and reinsert selected replacements without serializing or rebuilding SDK payloads.",
            "preservation": "All observed unedited values, concrete types, dictionary order/keys, tuple/bytes, model extras, original field presence, private state and opaque identity. An edited originally-unset field becomes explicitly set. Source unchanged during apply, not a detached mutable clone. Immutable tuple identity is not a contract; mutable aliases/cycles are refused.",
            "not_claimed": [
                "All past/future SDK versions",
                "OCR/audio/PDF inspection",
                "Fetching URL/file-ID attachment contents",
                "Decoding escaped JSON tool-argument substrings",
                "Changing signed blocks while retaining valid signatures",
                "Tool execution hooks or side effects",
                "Remote provider acceptance",
                "Arbitrary custom object internals or alias/cycle editing",
                "Full provider schema validation after replacement",
            ],
        },
        "common_protocol": {
            "extract": "extract(payload) -> tuple[Slot, ...]",
            "apply": "apply(payload, list[Patch]) -> native payload",
            "caller_example": [
                "def replace_selected(provider, payload, replacements):",
                "    adapter = select_adapter(provider, make_editor('lenses'))",
                "    slots = adapter.extract(payload)",
                "    patches = [Patch(s, replacements[s.path]) for s in slots if s.path in replacements]",
                "    return adapter.apply(payload, patches)",
            ],
            "production_files_modified": [],
            "maintenance": "Add or change a provider semantic rule and its native fixtures/version registration; the extract/apply caller and path editor stay unchanged. Opaque new object types need a separate traversal rule.",
        },
        "version_ranges": {key: [interval for interval, _ in rows] for key, rows in ADAPTER_RANGES.items()},
        "copy_policies": COPY_POLICY,
        "source_files": source_info,
        "sources": {"editors": SOURCES, "sdks": SDK_SOURCES},
        "native_sdk_cases": observations,
        "boundary_cases": boundaries,
        "guard_scenarios": guards,
        "unsupported_version_scenarios": version_checks,
        "timings": {
            "caveat": "Offline synthetic fixtures; includes extraction/preflight for each apply, warm process, no statistical performance claim.",
            "runs": timings,
        },
        "summary": {
            engine: dict(Counter(row["status"] for row in observations if row["editor"] == engine))
            for engine in EDITOR_NAMES
        },
        "findings_ko": [
            "직렬화 없이 원본 객체의 경로를 추출하고 선택한 값만 교체했다. JSON은 결과 기록과 도구 인자 문법 검사에만 사용했다.",
            "lenses는 변경된 경로의 상위 객체만 복사하므로 수정하지 않은 파일 핸들과 private 객체의 동일성을 보존했다. 반환값은 완전히 독립된 복사본이 아니다.",
            "glom Assign 자체는 제자리 변경이다. 비교용 deepcopy 래퍼는 튜플 항목 교체에 실패하고, 파일 핸들을 복사하지 못하며, 일부 수정하지 않은 객체의 동일성을 바꿨다.",
            "LiteLLM 도구 호출의 function/id/type이 Pydantic extras에 저장되어 있었다. 물리적 저장 경로와 의미 분류를 분리해야 SDK별 차이를 국소적으로 처리할 수 있다.",
            "첨부 데이터는 보존하거나 전체 bytes를 교체할 수 있지만 내부 개인정보 탐지까지 구현한 것은 아니다. 서명된 내용, 분할 스트림, 순환/공유 가변 객체는 별도 처리가 필요하다.",
        ],
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "native_sdk_cases": report["summary"],
                "boundaries": {
                    engine: dict(Counter(row["status"] for row in boundaries if row["editor"] == engine))
                    for engine in EDITOR_NAMES
                },
                "guard_checks_passed": sum(row["rejected"] and row["source_unchanged"] for row in guards),
                "guard_checks_total": len(guards),
                "unsupported_versions_rejected": sum(row["rejected"] for row in version_checks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    # Candidate-library failures are findings, not probe infrastructure failures.
    # A candidate must still establish all SDK-native scenarios before success.
    if not all(row["rejected"] and row["source_unchanged"] for row in guards) or not all(
        row["rejected"] for row in version_checks
    ):
        raise SystemExit(1)
    if not any(
        all(row["status"] == "preserved" for row in observations if row["editor"] == engine) for engine in EDITOR_NAMES
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
