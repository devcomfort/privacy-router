"""PII detector comparison benchmark.

Runs each registered privacy detector (presidio, lfm, opf, llm) over a fixed
bilingual case set and writes machine-readable results plus a human-readable
report under ``var/detector-bench/<timestamp>/``.

Usage:
    uv run python scripts/detector_bench.py [--detectors presidio,lfm,opf,llm]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from agents.extractor.lfm.extractor import LFMExtractor
from agents.extractor.llm.extractor import LLMExtractor
from agents.extractor.opf.extractor import OPFExtractor
from agents.extractor.presidio.extractor import PresidioExtractor

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "var" / "detector-bench"

# Each case lists the spans a detector should ideally recognize. Contextual
# cases double as a business/research-secret probe.
CASES = [
    {
        "id": "ko-rrn",
        "name": "주민등록번호",
        "lang": "ko",
        "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        "expected": ["901212-1234567"],
    },
    {
        "id": "ko-contact",
        "name": "이름+전화+이메일",
        "lang": "ko",
        "text": "김민수(010-1234-5678, minsu.kim@example.invalid)에게 회의 일정을 보내줘.",
        "expected": ["김민수", "010-1234-5678", "minsu.kim@example.invalid"],
    },
    {
        "id": "ko-card",
        "name": "카드번호",
        "lang": "ko",
        "text": "카드번호 1234-5678-9012-3456으로 결제해줘.",
        "expected": ["1234-5678-9012-3456"],
    },
    {
        "id": "ko-business",
        "name": "사업비밀(맥락)",
        "lang": "ko",
        "text": "삼성전자 차세대 AP 개발 건으로, TSMC 3nm 공정을 채택하기로 내부적으로 결정했다.",
        "expected": ["삼성전자 차세대 AP 개발", "TSMC 3nm 공정을 채택하기로", "내부적으로 결정"],
    },
    {
        "id": "ko-research",
        "name": "연구비밀(맥락)",
        "lang": "ko",
        "text": "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.",
        "expected": ["김동현", "광주과학기술원", "contextual distillation"],
    },
    {
        "id": "en-pii",
        "name": "EN email/phone/address",
        "lang": "en",
        "text": "Email john.doe@example.com, phone +1-415-555-2671, and visit John Doe at 123 Main St, Springfield.",
        "expected": ["john.doe@example.com", "+1-415-555-2671", "John Doe", "123 Main St, Springfield"],
    },
    {
        "id": "en-secret",
        "name": "EN business secret (contextual)",
        "lang": "en",
        "text": "Our Q3 acquisition target is Acme Corp; keep the LOI price of $4.2M confidential from the board deck.",
        "expected": ["Acme Corp", "$4.2M"],
    },
    {
        "id": "en-safe",
        "name": "EN safe query",
        "lang": "en",
        "text": "Summarize the plot of a classic novel about a detective in London.",
        "expected": [],
    },
    {
        "id": "ko-safe",
        "name": "안전 쿼리",
        "lang": "ko",
        "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.",
        "expected": [],
    },
    {
        "id": "ko-address",
        "name": "이름+주소",
        "lang": "ko",
        "text": "홍길동에게 서울특별시 강남구 테헤란로 123으로 우편을 보내줘.",
        "expected": ["홍길동", "서울특별시 강남구 테헤란로 123"],
    },
]


def build_detectors(names: list[str], device: str) -> tuple[dict, dict[str, str]]:
    detectors: dict = {}
    labels: dict[str, str] = {}
    if "presidio" in names:
        detectors["presidio"] = PresidioExtractor(language="en")
    if "lfm" in names:
        detectors["lfm"] = LFMExtractor(device=device)
    if "opf" in names:
        detectors["opf"] = OPFExtractor(device=device)
    if "llm-ollama" in names:
        model = "ollama/qwen3:1.7b"
        detectors["llm-ollama"] = LLMExtractor(model=model, api_base="http://127.0.0.1:11434")
        labels["llm-ollama"] = f"llm-ollama ({model})"
    if "llm-openrouter" in names:
        model = "openrouter/google/gemma-4-26b-a4b-it"
        detectors["llm-openrouter"] = LLMExtractor(model=model, api_base="https://openrouter.ai/api/v1")
        labels["llm-openrouter"] = f"llm-openrouter ({model})"
    if "llm-gptoss" in names:
        model = "openrouter/openai/gpt-oss-120b"
        detectors["llm-gptoss"] = LLMExtractor(model=model, api_base="https://openrouter.ai/api/v1", max_tokens=8192)
        labels["llm-gptoss"] = f"llm-gptoss ({model}, max_tokens=8192)"
    if "llm-gptoss-cerebras" in names:
        model = "openrouter/openai/gpt-oss-120b:cerebras"
        detectors["llm-gptoss-cerebras"] = LLMExtractor(model=model, api_base="https://openrouter.ai/api/v1", max_tokens=8192)
        labels["llm-gptoss-cerebras"] = "llm-gptoss-cerebras (openai/gpt-oss-120b via Cerebras, max_tokens=8192)"
    if "llm-qwen36" in names:
        model = "openai/QuantTrio/Qwen3.6-35B-A3B-AWQ"
        detectors["llm-qwen36"] = LLMExtractor(model=model, api_base="http://127.0.0.1:8012/v1")
        labels["llm-qwen36"] = "llm-qwen36 (QuantTrio/Qwen3.6-35B-A3B-AWQ, local vLLM)"
    return detectors, labels


def run_one(detector, text: str, *, allow_external: bool = False) -> dict:
    started = time.perf_counter()
    try:
        result = detector.extract(text) if not allow_external else detector.extract(text, allow_external=True)
    except Exception as exc:  # noqa: BLE001 - benchmark must record any failure
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}",
            "entities": [],
        }
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    entities = [
        {
            "tag": entity.tag,
            "span": entity.span,
            "kind": entity.kind,
            "confidence": entity.confidence,
        }
        for entity in result.entities
    ]
    error = None
    for run in result.detector_runs:
        if getattr(run, "error_code", None):
            messages = [m for msgs in result.diagnostics.values() for m in msgs]
            error = run.error_code + (f": {messages[0]}" if messages else "")
    return {
        "status": result.status,
        "latency_ms": latency_ms,
        "error": error,
        "entities": entities,
    }


def score(out: dict, expected: list[str]) -> dict:
    spans = {entity["span"].strip() for entity in out["entities"]}
    hits = [want for want in expected if any(want in got or got in want for got in spans)]
    return {
        "expected": expected,
        "hits": hits,
        "misses": [want for want in expected if want not in hits],
        "unexpected": sorted(spans - set(expected)),
    }


def verdict(score: dict, out: dict) -> str:
    """Render an explicit pass/fail verdict with failure reasons."""
    reasons: list[str] = []
    if out["status"] not in {"complete", "partial"}:
        reasons.append(f"탐지기 실패: {out['error'] or out['status']}")
    if score["misses"]:
        reasons.append("누락: " + ", ".join(score["misses"]))
    if not score["expected"] and score["unexpected"]:
        reasons.append("오탐: " + ", ".join(score["unexpected"]))
    if not reasons:
        return "합격"
    return "**실패** — " + "; ".join(reasons)


def write_report(path: Path, rows: list[dict], detector_names: list[str], labels: dict[str, str]) -> None:
    display = {name: labels.get(name, name) for name in detector_names}
    lines = ["# PII detector benchmark", ""]
    lines.append(f"- generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- detectors: {', '.join(display[name] for name in detector_names)}")
    lines.append("")
    lines.append("## Summary (expected-span recall)")
    lines.append("")
    lines.append("| detector | cases | hits | misses | total entities | avg latency ms |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for name in detector_names:
        hits = sum(len(row["per_detector"][name]["score"]["hits"]) for row in rows)
        misses = sum(len(row["per_detector"][name]["score"]["misses"]) for row in rows)
        total_entities = sum(len(row["per_detector"][name]["output"]["entities"]) for row in rows)
        latencies = [row["per_detector"][name]["output"]["latency_ms"] for row in rows]
        avg = sum(latencies) / len(latencies) if latencies else 0.0
        lines.append(f"| {display[name]} | {len(rows)} | {hits} | {misses} | {total_entities} | {avg:.0f} |")
    lines.append("")
    for row in rows:
        lines.append(f"## {row['case']['id']} — {row['case']['name']}")
        lines.append("")
        lines.append(f"입력: `{row['case']['text']}`")
        lines.append("")
        lines.append(f"기대 스팬: {', '.join(row['case']['expected']) or '(없음 — 안전 쿼리)'}")
        lines.append("")
        lines.append("| detector | status | latency ms | entities | 평가 |")
        lines.append("|---|---|---:|---|---|")
        for name in detector_names:
            entry = row["per_detector"][name]
            out = entry["output"]
            entities = (
                "; ".join(
                    f"{entity['tag']}=`{entity['span']}`"
                    + (f" ({entity['confidence']:.2f})" if entity.get("confidence") is not None else "")
                    for entity in out["entities"]
                )
                or "-"
            )
            lines.append(
                f"| {display[name]} | {out['status']} | {out['latency_ms']:.0f} | {entities} | {verdict(entry['score'], out)} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detectors", default="presidio,lfm,opf,llm-ollama,llm-openrouter")
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--from-results", type=Path, default=None, help="regenerate report.md from an existing results.json"
    )
    args = parser.parse_args()

    names = [name.strip() for name in args.detectors.split(",") if name.strip()]
    if args.from_results is not None:
        saved = json.loads(args.from_results.read_text(encoding="utf-8"))
        report_path = args.from_results.with_name("report.md")
        write_report(report_path, saved["rows"], saved["detectors"], saved.get("labels", {}))
        print(f"report:  {report_path}")
        return
    detectors, labels = build_detectors(names, args.device)
    run_dir = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for case in CASES:
        row = {"case": case, "per_detector": {}}
        for name, detector in detectors.items():
            print(f"[{name}] {case['id']} ...", flush=True)
            out = run_one(
                detector,
                case["text"],
                allow_external=name.startswith("llm-"),
            )
            row["per_detector"][name] = {"output": out, "score": score(out, case["expected"])}
        rows.append(row)

    payload = {"detectors": names, "labels": labels, "rows": rows}
    (run_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(run_dir / "report.md", rows, names, labels)
    print(f"\nresults: {run_dir / 'results.json'}")
    print(f"report:  {run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
