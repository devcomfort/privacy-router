"""Final end-to-end acceptance evaluation for the Privacy Router API.

The evaluator exercises the public OpenAI-compatible endpoint and records only
aggregate checks and case identifiers. Raw prompts, extracted spans, generated
responses, and API keys are never persisted in the result artifact.

Run the full five-trial acceptance suite::

    python -m eval.final_e2e --api-key "$PRIVACY_ROUTER_API_KEY"

Run one representative trial while developing::

    python -m eval.final_e2e --api-key "$PRIVACY_ROUTER_API_KEY" --trials 1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from agents import ExtractionRecord
from eval.dataset import MULTI_TURN_CONVERSATIONS
from server.api import mask_chat_messages

ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH_PATH = ROOT / "docs" / "experiments" / "ground-truth.json"
RESULTS_DIR = ROOT / "eval" / "results"
ACTION_SEVERITY = {"allow": 0, "selective_mask": 1, "block": 2}
LEGACY_ACTIONS = {
    "allow": "allow",
    "mask_and_send": "selective_mask",
    "selective_mask": "selective_mask",
    "prompt_user": "block",
    "route_to_local": "block",
    "block": "block",
}
PLACEHOLDER_RE = re.compile(r"(?:\[)?[A-Z][A-Z0-9_]*#[0-9a-fA-F]{8}(?:\])?")


@dataclass(frozen=True)
class TurnExpectation:
    """Expected cumulative privacy state at one user turn."""

    turn_index: int
    is_sensitive: bool
    action: str
    records: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AcceptanceThresholds:
    """Hard gates for the final acceptance verdict."""

    request_success: float = 1.0
    sensitivity_accuracy: float = 0.95
    action_accuracy: float = 0.95
    block_recall: float = 1.0
    route_boundary_accuracy: float = 1.0
    masking_safety_accuracy: float = 1.0
    privacy_leak_rate: float = 0.0
    placeholder_leak_rate: float = 0.0
    utility_success: float = 0.95
    max_p95_latency_s: float | None = None


@dataclass
class CaseCheck:
    """Privacy and utility checks for one endpoint response."""

    case_id: str
    scope: str
    expected_sensitive: bool
    expected_action: str
    detected_sensitive: bool | None
    detected_action: str | None
    request_success: bool
    sensitivity_correct: bool
    action_correct: bool
    route_boundary_correct: bool
    masking_safe: bool
    no_placeholder_leak: bool
    utility_success: bool
    privacy_safe: bool
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(
            (
                self.request_success,
                self.sensitivity_correct,
                self.action_correct,
                self.route_boundary_correct,
                self.masking_safe,
                self.no_placeholder_leak,
                self.utility_success,
                self.privacy_safe,
            )
        )


def normalize_action(action: str | None) -> str | None:
    """Normalize historical route labels to the current policy actions."""

    if action is None:
        return None
    try:
        return LEGACY_ACTIONS[action]
    except KeyError as exc:
        raise ValueError(f"Unknown policy action: {action}") from exc


def cumulative_expectations(conversation: dict[str, Any]) -> list[TurnExpectation]:
    """Build conservative expectations for requests containing full history.

    The public chat endpoint receives cumulative messages. Once a sensitive
    user turn enters that history, later requests must continue protecting it.
    The cumulative action therefore keeps the strongest action observed so far.
    """

    expected_actions = conversation.get("expected_actions", [])
    sensitive_turns = set(conversation.get("expected_sensitive_turns", []))
    records_per_turn = conversation.get("expected_records_per_turn", {})
    strongest_action = "allow"
    accumulated_records: list[dict[str, Any]] = []
    results: list[TurnExpectation] = []

    for index, turn in enumerate(conversation.get("turns", [])):
        action = normalize_action(expected_actions[index] if index < len(expected_actions) else "allow")
        if action is None:
            action = "allow"
        if ACTION_SEVERITY[action] > ACTION_SEVERITY[strongest_action]:
            strongest_action = action

        turn_records = records_per_turn.get(index, records_per_turn.get(str(index), []))
        accumulated_records.extend(turn_records)

        if turn.get("role") != "user":
            continue
        is_sensitive = bool(sensitive_turns.intersection(range(index + 1)))
        results.append(
            TurnExpectation(
                turn_index=index,
                is_sensitive=is_sensitive,
                action=strongest_action,
                records=tuple(accumulated_records),
            )
        )

    return results


def _message_output(response: dict[str, Any]) -> tuple[str, bool]:
    choices = response.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return "", False
    message = choices[0].get("message") or {}
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    has_tool_calls = bool(message.get("tool_calls"))
    return text, bool(text.strip() or has_tool_calls)


def _masking_audit(
    messages: list[dict[str, Any]],
    detected_records: list[dict[str, Any]],
    expected_records: list[dict[str, Any]],
) -> bool:
    if not detected_records or not expected_records:
        return False

    try:
        records = [
            ExtractionRecord(
                category=str(record["category"]),
                span=str(record["span"]),
                confidence=float(record.get("confidence", 1.0)),
                start=0,
                end=len(str(record["span"])),
                reasoning=str(record.get("reasoning", "")),
                is_essential=bool(record.get("is_essential", False)),
            )
            for record in detected_records
            if record.get("category") and record.get("span")
        ]
        masked = mask_chat_messages(messages, records)
    except (KeyError, TypeError, ValueError):
        return False

    serialized = json.dumps(masked.value, ensure_ascii=False)
    placeholders = masked.contract.placeholder_map
    expected_spans = {
        str(record["span"]) for record in expected_records if isinstance(record, dict) and record.get("span")
    }
    return bool(
        expected_spans
        and placeholders
        and all(span not in serialized for span in expected_spans)
        and all(placeholder in serialized for placeholder in placeholders)
    )


def _model_cost(
    selected_model: str | None,
    usage: dict[str, Any],
    model_costs: dict[str, tuple[float, float]],
) -> float:
    if not selected_model or selected_model not in model_costs:
        return 0.0
    input_rate, output_rate = model_costs[selected_model]
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def evaluate_response(
    *,
    case_id: str,
    expected_sensitive: bool,
    expected_action: str,
    expected_records: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    status_code: int,
    response: dict[str, Any],
    latency_s: float,
    local_model: str,
    external_model: str,
    scope: str,
    model_costs: dict[str, tuple[float, float]] | None = None,
) -> CaseCheck:
    """Evaluate one public API response without retaining sensitive content."""

    expected_action = normalize_action(expected_action) or "allow"
    request_success = status_code == 200 and isinstance(response, dict)
    meta = response.get("privacy_router", {}) if request_success else {}
    detected_sensitive = meta.get("is_sensitive")
    detected_action = normalize_action(meta.get("policy_action"))
    route = meta.get("route")
    selected_model = meta.get("model_used")
    expected_route = "local_api" if expected_action == "block" else "external_api"
    expected_model = local_model if expected_action == "block" else external_model

    sensitivity_correct = detected_sensitive is expected_sensitive
    action_correct = detected_action == expected_action
    route_boundary_correct = route == expected_route and selected_model == expected_model
    masking_safe = True
    if expected_action == "selective_mask":
        masking_safe = _masking_audit(
            messages,
            list(meta.get("extraction_records") or []),
            expected_records,
        )

    output_text, utility_success = _message_output(response)
    no_placeholder_leak = not PLACEHOLDER_RE.search(output_text)
    privacy_safe = not expected_sensitive or (action_correct and route_boundary_correct and masking_safe)
    usage = response.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)

    errors: list[str] = []
    checks = {
        "request_failed": request_success,
        "sensitivity_mismatch": sensitivity_correct,
        "action_mismatch": action_correct,
        "route_boundary_mismatch": route_boundary_correct,
        "masking_contract_failed": masking_safe,
        "placeholder_leak": no_placeholder_leak,
        "empty_output": utility_success,
        "privacy_contract_failed": privacy_safe,
    }
    errors.extend(name for name, passed in checks.items() if not passed)

    return CaseCheck(
        case_id=case_id,
        scope=scope,
        expected_sensitive=expected_sensitive,
        expected_action=expected_action,
        detected_sensitive=detected_sensitive,
        detected_action=detected_action,
        request_success=request_success,
        sensitivity_correct=sensitivity_correct,
        action_correct=action_correct,
        route_boundary_correct=route_boundary_correct,
        masking_safe=masking_safe,
        no_placeholder_leak=no_placeholder_leak,
        utility_success=utility_success,
        privacy_safe=privacy_safe,
        latency_s=latency_s,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=_model_cost(
            selected_model,
            usage,
            model_costs or {},
        ),
        errors=errors,
    )


def _ratio(checks: list[CaseCheck], attribute: str) -> float:
    if not checks:
        return 1.0
    return sum(bool(getattr(check, attribute)) for check in checks) / len(checks)


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _scope_metrics(checks: list[CaseCheck]) -> dict[str, Any]:
    sensitive = [check for check in checks if check.expected_sensitive]
    blocked = [check for check in checks if check.expected_action == "block"]
    selectively_masked = [check for check in checks if check.expected_action == "selective_mask"]
    return {
        "requests": len(checks),
        "request_success": _ratio(checks, "request_success"),
        "sensitivity_accuracy": _ratio(checks, "sensitivity_correct"),
        "action_accuracy": _ratio(checks, "action_correct"),
        "block_recall": _ratio(blocked, "action_correct"),
        "route_boundary_accuracy": _ratio(checks, "route_boundary_correct"),
        "masking_safety_accuracy": _ratio(selectively_masked, "masking_safe"),
        "privacy_leak_rate": 1.0 - _ratio(sensitive, "privacy_safe"),
        "placeholder_leak_rate": 1.0 - _ratio(checks, "no_placeholder_leak"),
        "utility_success": _ratio(checks, "utility_success"),
        "pass_rate": _ratio(checks, "passed"),
        "latency_s": {
            "p50": round(_percentile((check.latency_s for check in checks), 0.50), 3),
            "p95": round(_percentile((check.latency_s for check in checks), 0.95), 3),
            "max": round(max((check.latency_s for check in checks), default=0.0), 3),
        },
        "tokens": {
            "input": sum(check.input_tokens for check in checks),
            "output": sum(check.output_tokens for check in checks),
        },
        "estimated_cost_usd": round(sum(check.estimated_cost_usd for check in checks), 6),
    }


def _evaluate_gates(
    metrics: dict[str, Any],
    thresholds: AcceptanceThresholds,
) -> dict[str, dict[str, Any]]:
    gate_specs: dict[str, tuple[float, float, str]] = {
        "request_success": (
            metrics["request_success"],
            thresholds.request_success,
            "min",
        ),
        "sensitivity_accuracy": (
            metrics["sensitivity_accuracy"],
            thresholds.sensitivity_accuracy,
            "min",
        ),
        "action_accuracy": (
            metrics["action_accuracy"],
            thresholds.action_accuracy,
            "min",
        ),
        "block_recall": (metrics["block_recall"], thresholds.block_recall, "min"),
        "route_boundary_accuracy": (
            metrics["route_boundary_accuracy"],
            thresholds.route_boundary_accuracy,
            "min",
        ),
        "masking_safety_accuracy": (
            metrics["masking_safety_accuracy"],
            thresholds.masking_safety_accuracy,
            "min",
        ),
        "privacy_leak_rate": (
            metrics["privacy_leak_rate"],
            thresholds.privacy_leak_rate,
            "max",
        ),
        "placeholder_leak_rate": (
            metrics["placeholder_leak_rate"],
            thresholds.placeholder_leak_rate,
            "max",
        ),
        "utility_success": (
            metrics["utility_success"],
            thresholds.utility_success,
            "min",
        ),
    }
    if thresholds.max_p95_latency_s is not None:
        gate_specs["p95_latency_s"] = (
            metrics["latency_s"]["p95"],
            thresholds.max_p95_latency_s,
            "max",
        )

    return {
        name: {
            "value": value,
            "threshold": threshold,
            "operator": operator,
            "passed": value >= threshold if operator == "min" else value <= threshold,
        }
        for name, (value, threshold, operator) in gate_specs.items()
    }


def aggregate_checks(
    checks: list[CaseCheck],
    thresholds: AcceptanceThresholds,
) -> dict[str, Any]:
    """Aggregate observations and require every evaluation scope to pass."""

    metrics = _scope_metrics(checks)
    gates = _evaluate_gates(metrics, thresholds)

    scoped: dict[str, Any] = {}
    scope_gates: dict[str, Any] = {}
    for scope in sorted({check.scope for check in checks}):
        scope_metrics = _scope_metrics([check for check in checks if check.scope == scope])
        scoped[scope] = scope_metrics
        scope_gates[scope] = _evaluate_gates(scope_metrics, thresholds)

    cases: dict[str, list[CaseCheck]] = defaultdict(list)
    for check in checks:
        cases[check.case_id].append(check)
    stability = {case_id: round(_ratio(case_checks, "passed"), 3) for case_id, case_checks in sorted(cases.items())}

    overall_passed = all(gate["passed"] for gate in gates.values())
    scopes_passed = all(
        gate["passed"] for scope_gate_results in scope_gates.values() for gate in scope_gate_results.values()
    )
    return {
        "verdict": "PASS" if overall_passed and scopes_passed else "FAIL",
        "metrics": metrics,
        "gates": gates,
        "by_scope": scoped,
        "scope_gates": scope_gates,
        "case_stability": stability,
    }


def _load_single_turn_cases() -> list[dict[str, Any]]:
    document = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    return list(document["cases"])


def _request(
    client: httpx.Client,
    *,
    messages: list[dict[str, Any]],
    chat_id: str,
    max_tokens: int,
) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter()
    try:
        response = client.post(
            "/v1/chat/completions",
            headers={"x-chat-id": chat_id},
            json={
                "model": "privacy-router",
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "stream": False,
            },
        )
        latency_s = time.perf_counter() - started
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload, latency_s
    except httpx.HTTPError:
        return 0, {}, time.perf_counter() - started


def _runtime_contract(settings: dict[str, Any]) -> tuple[str, str, dict[str, tuple[float, float]]]:
    local_model = str(settings["local"]["model"])
    external_model = str(settings["external"]["model"])
    costs: dict[str, tuple[float, float]] = {}
    for model in settings.get("models", []):
        model_id = model.get("id")
        if not model_id:
            continue
        input_rate = float(model.get("cost_per_1m_tokens", 0.0) or 0.0)
        output_rate = float(model.get("cost_per_1m_output_tokens", input_rate) or input_rate)
        costs[str(model_id)] = (input_rate, output_rate)
    return local_model, external_model, costs


def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the requested single-turn and cumulative multi-turn suites."""

    headers = {"Authorization": f"Bearer {args.api_key}"}
    timeout = httpx.Timeout(args.timeout)
    checks: list[CaseCheck] = []

    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers=headers,
        timeout=timeout,
    ) as client:
        settings_response = client.get("/api/settings")
        settings_response.raise_for_status()
        local_model, external_model, model_costs = _runtime_contract(settings_response.json())

        single_cases = _load_single_turn_cases() if args.suite in {"all", "single"} else []
        conversations = list(MULTI_TURN_CONVERSATIONS) if args.suite in {"all", "multi"} else []
        if args.case_id:
            single_cases = [case for case in single_cases if case["id"] == args.case_id]
        if args.conversation_id:
            conversations = [item for item in conversations if item["id"] == args.conversation_id]

        for trial in range(args.trials):
            for case in single_cases:
                gt = case["gt"]
                messages = [{"role": "user", "content": case["text"]}]
                status, response, latency_s = _request(
                    client,
                    messages=messages,
                    chat_id=f"final-single-{trial}-{case['id']}",
                    max_tokens=args.max_tokens,
                )
                checks.append(
                    evaluate_response(
                        case_id=case["id"],
                        expected_sensitive=bool(gt["is_sensitive"]),
                        expected_action=str(gt["expected_action"]),
                        expected_records=list(gt.get("records", [])),
                        messages=messages,
                        status_code=status,
                        response=response,
                        latency_s=latency_s,
                        local_model=local_model,
                        external_model=external_model,
                        scope="single_turn",
                        model_costs=model_costs,
                    )
                )
                print(f"[{trial + 1}/{args.trials}] single {case['id']}", flush=True)

            for conversation in conversations:
                expectations = {item.turn_index: item for item in cumulative_expectations(conversation)}
                history: list[dict[str, Any]] = []
                for index, turn in enumerate(conversation["turns"]):
                    history.append(turn)
                    if turn.get("role") != "user":
                        continue
                    expectation = expectations[index]
                    status, response, latency_s = _request(
                        client,
                        messages=history,
                        chat_id=f"final-multi-{trial}-{conversation['id']}",
                        max_tokens=args.max_tokens,
                    )
                    checks.append(
                        evaluate_response(
                            case_id=f"{conversation['id']}:turn-{index}",
                            expected_sensitive=expectation.is_sensitive,
                            expected_action=expectation.action,
                            expected_records=list(expectation.records),
                            messages=history,
                            status_code=status,
                            response=response,
                            latency_s=latency_s,
                            local_model=local_model,
                            external_model=external_model,
                            scope="multi_turn_cumulative",
                            model_costs=model_costs,
                        )
                    )
                    print(
                        f"[{trial + 1}/{args.trials}] multi {conversation['id']}:turn-{index}",
                        flush=True,
                    )

    thresholds = AcceptanceThresholds(max_p95_latency_s=args.max_p95_latency)
    summary = aggregate_checks(checks, thresholds)
    failures = [
        {
            "case_id": check.case_id,
            "scope": check.scope,
            "errors": check.errors,
        }
        for check in checks
        if not check.passed
    ]
    return {
        "schema_version": "1.0.0",
        "created_at": datetime.now(UTC).isoformat(),
        "suite": args.suite,
        "trials": args.trials,
        "runtime_roles": {
            "decision": settings_response.json()["decision"]["model"],
            "local": local_model,
            "external": external_model,
        },
        "thresholds": asdict(thresholds),
        **summary,
        "failures": failures,
        "privacy_note": (
            "Raw prompts, sensitive spans, generated responses, and credentials "
            "are intentionally excluded from this artifact."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Privacy Router final end-to-end acceptance evaluation.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument(
        "--api-key",
        default=os.getenv("PRIVACY_ROUTER_API_KEY", ""),
        help="Privacy Router API key (or set PRIVACY_ROUTER_API_KEY)",
    )
    parser.add_argument("--suite", choices=("all", "single", "multi"), default="all")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--case-id")
    parser.add_argument("--conversation-id")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument(
        "--max-p95-latency",
        type=float,
        default=None,
        help="Optional environment-specific p95 latency hard gate in seconds",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.api_key:
        print(
            "PRIVACY_ROUTER_API_KEY or --api-key is required.",
            file=sys.stderr,
        )
        return 2
    if args.trials < 1:
        print("--trials must be at least 1.", file=sys.stderr)
        return 2

    try:
        result = run_evaluation(args)
    except (httpx.HTTPError, KeyError, OSError, ValueError) as exc:
        print(f"Evaluation setup failed: {type(exc).__name__}", file=sys.stderr)
        return 2

    output = args.output
    if output is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = RESULTS_DIR / f"final_e2e_{timestamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"verdict": result["verdict"], "output": str(output)}))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
