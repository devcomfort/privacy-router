#!/usr/bin/env python3
"""Deterministic Privacy Router local pipeline benchmark.

This benchmark intentionally avoids live LLM/network calls. It exercises the
rule-based Judge, deterministic Masker/Hydrator, and Router path selection with
curated extractor outputs that cover allow, selective-mask, and block policies.
"""

from __future__ import annotations

import logging
import statistics
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", message='Field name "schema".*')
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("litellm").setLevel(logging.ERROR)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agents import Judge  # noqa: E402
from agents.router import Router  # noqa: E402


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    sensitivity: dict[str, Any]
    records: list[dict[str, Any]]
    expected_policy: str


def _record(text: str, category: str, span: str, is_essential: bool) -> dict[str, Any]:
    start = text.index(span)
    return {
        "category": category,
        "span": span,
        "start": start,
        "end": start + len(span),
        "confidence": 0.99,
        "reasoning": "deterministic benchmark fixture",
        "is_essential": is_essential,
    }


def build_cases() -> list[Case]:
    safe_en = "Summarize the public Privacy Router architecture for a class demo."
    safe_ko = "공개된 Privacy Router 구조를 수업 발표용으로 요약해줘."

    pii_mask = "Draft a shipping update for Mina Kim at 010-1234-5678 without exposing the phone number."
    rrn_block = "Check whether resident registration number 901212-1234567 is valid."
    secret_mask = "Rewrite this launch note but hide codename ORCHID-RAIN before sending it outside."
    secret_block = "Use internal project codename ORCHID-RAIN to identify the unreleased roadmap item."
    research_mask = "Polish the abstract mentioning unpublished method GraphMask-v7 for an external editor."
    research_block = "Compare unpublished method GraphMask-v7 against our private ablation results."
    korean_mask = "외부 메일 초안에서 전화번호 010-2222-3333은 숨기고 문장만 다듬어줘."
    korean_block = "주민등록번호 800101-1234567의 소유자 정보를 확인해줘."

    return [
        Case(
            name="allow_public_en",
            text=safe_en,
            sensitivity={"is_sensitive": False, "rationale": "public architecture summary"},
            records=[],
            expected_policy="allow",
        ),
        Case(
            name="allow_public_ko",
            text=safe_ko,
            sensitivity={"is_sensitive": False, "rationale": "public architecture summary"},
            records=[],
            expected_policy="allow",
        ),
        Case(
            name="mask_phone_en",
            text=pii_mask,
            sensitivity={"is_sensitive": True, "rationale": "phone number can be masked"},
            records=[_record(pii_mask, "MOBILE_PHONE_NUMBER", "010-1234-5678", False)],
            expected_policy="selective_mask",
        ),
        Case(
            name="block_rrn_en",
            text=rrn_block,
            sensitivity={"is_sensitive": True, "rationale": "identifier is the query target"},
            records=[_record(rrn_block, "RESIDENT_REGISTRATION_NUMBER", "901212-1234567", True)],
            expected_policy="block",
        ),
        Case(
            name="mask_business_secret_en",
            text=secret_mask,
            sensitivity={"is_sensitive": True, "rationale": "internal codename can be masked"},
            records=[_record(secret_mask, "INTERNAL_PROJECT_NAME", "ORCHID-RAIN", False)],
            expected_policy="selective_mask",
        ),
        Case(
            name="block_business_secret_en",
            text=secret_block,
            sensitivity={"is_sensitive": True, "rationale": "internal codename is needed to identify the item"},
            records=[_record(secret_block, "INTERNAL_PROJECT_NAME", "ORCHID-RAIN", True)],
            expected_policy="block",
        ),
        Case(
            name="mask_research_secret_en",
            text=research_mask,
            sensitivity={"is_sensitive": True, "rationale": "unpublished method can be masked"},
            records=[_record(research_mask, "UNPUBLISHED_RESEARCH_CONCEPT", "GraphMask-v7", False)],
            expected_policy="selective_mask",
        ),
        Case(
            name="block_research_secret_en",
            text=research_block,
            sensitivity={"is_sensitive": True, "rationale": "unpublished method is central to the request"},
            records=[_record(research_block, "UNPUBLISHED_RESEARCH_CONCEPT", "GraphMask-v7", True)],
            expected_policy="block",
        ),
        Case(
            name="mask_phone_ko",
            text=korean_mask,
            sensitivity={"is_sensitive": True, "rationale": "phone number can be masked"},
            records=[_record(korean_mask, "MOBILE_PHONE_NUMBER", "010-2222-3333", False)],
            expected_policy="selective_mask",
        ),
        Case(
            name="block_rrn_ko",
            text=korean_block,
            sensitivity={"is_sensitive": True, "rationale": "identifier is the query target"},
            records=[_record(korean_block, "RESIDENT_REGISTRATION_NUMBER", "800101-1234567", True)],
            expected_policy="block",
        ),
    ]


def external_echo(text: str) -> str:
    return f"external processed: {text}"


def local_echo(text: str) -> str:
    return f"local processed: {text}"


def run_once(cases: list[Case]) -> tuple[int, int, int]:
    judge = Judge()
    router = Router()
    policy_correct = 0
    route_correct = 0
    hydration_correct = 0

    for case in cases:
        judgment = judge.classify(case.sensitivity, case.records, case.text)
        if judgment.policy_action == case.expected_policy:
            policy_correct += 1

        response = router.execute(
            case.text,
            judgment.policy_action,
            case.records,
            call_external=external_echo,
            call_local=local_echo,
        )

        if judgment.policy_action == "allow" and response == external_echo(case.text):
            route_correct += 1
            hydration_correct += 1
        elif judgment.policy_action == "selective_mask":
            contains_original = all(record["span"] in response for record in case.records)
            contains_placeholder = any("#" in token for token in response.split())
            if response.startswith("external processed:"):
                route_correct += 1
            if contains_original and not contains_placeholder:
                hydration_correct += 1
        elif judgment.policy_action == "block" and response == local_echo(case.text):
            route_correct += 1
            hydration_correct += 1

    return policy_correct, route_correct, hydration_correct


def main() -> int:
    cases = build_cases()
    warmup_rounds = 25
    measured_rounds = 250
    timings_ms: list[float] = []

    for _ in range(warmup_rounds):
        run_once(cases)

    total_policy = 0
    total_route = 0
    total_hydration = 0
    expected_total = len(cases) * measured_rounds

    for _ in range(measured_rounds):
        start = time.perf_counter_ns()
        policy_correct, route_correct, hydration_correct = run_once(cases)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        timings_ms.append(elapsed_ms)
        total_policy += policy_correct
        total_route += route_correct
        total_hydration += hydration_correct

    if total_policy != expected_total or total_route != expected_total or total_hydration != expected_total:
        print(
            "ERROR correctness failed: "
            f"policy={total_policy}/{expected_total} "
            f"route={total_route}/{expected_total} "
            f"hydration={total_hydration}/{expected_total}",
            file=sys.stderr,
        )
        return 1

    median_ms = statistics.median(timings_ms)
    p95_ms = sorted(timings_ms)[int(len(timings_ms) * 0.95) - 1]
    cases_per_second = len(cases) / (median_ms / 1000)

    print(f"METRIC pipeline_latency_ms={median_ms:.6f}")
    print(f"METRIC pipeline_p95_latency_ms={p95_ms:.6f}")
    print(f"METRIC pipeline_cases_per_second={cases_per_second:.6f}")
    print(f"METRIC policy_accuracy={total_policy / expected_total:.6f}")
    print(f"METRIC route_accuracy={total_route / expected_total:.6f}")
    print(f"METRIC hydration_accuracy={total_hydration / expected_total:.6f}")
    print(f"METRIC benchmark_cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
