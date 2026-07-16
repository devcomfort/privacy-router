#!/usr/bin/env python3
"""Unified evaluation runner for Privacy Router extractor tuning.

Supports multi-engine (vLLM, llama-server, SGLang), multi-model,
N≥5 independent trials, and both single-turn and multi-turn test cases.

Usage:
    # Single model, single engine, 5 trials
    python scripts/eval_runner.py --model ministral-3b --engine vllm --trials 5

    # All models on one engine
    python scripts/eval_runner.py --engine vllm --trials 5

    # Full matrix
    python scripts/eval_runner.py --all --trials 5

    # Report only (no new runs)
    python scripts/eval_runner.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "dummy")

RESULTS_DIR = ROOT / "docs" / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# Model Registry
# ═══════════════════════════════════════════════════════════════════════════

MODELS = {
    # OpenRouter models (cloud)
    "ministral-3b-openrouter": {
        "model": "openrouter/mistralai/ministral-3b-2512",
        "api_base": None,
        "engine": "openrouter",
        "params": "3B",
    },
    "gemma4-e4b-openrouter": {
        "model": "openrouter/google/gemma-4-e4b-it",
        "api_base": None,
        "engine": "openrouter",
        "params": "4B",
    },
    "gemma4-e2b-openrouter": {
        "model": "openrouter/google/gemma-4-e2b-it",
        "api_base": None,
        "engine": "openrouter",
        "params": "2B",
    },
    # vLLM models (port 8000)
    "ministral-3b-vllm": {
        "model": "openai/mistralai/Ministral-3-3B-Instruct-2512",
        "api_base": "http://localhost:8000/v1",
        "engine": "vllm",
        "params": "3B",
    },
    "gemma4-e4b-vllm": {
        "model": "openai/google/gemma-4-E4B-it",
        "api_base": "http://localhost:8000/v1",
        "engine": "vllm",
        "params": "4B",
    },
    "gemma4-e2b-vllm": {
        "model": "openai/google/gemma-4-E2B-it",
        "api_base": "http://localhost:8000/v1",
        "engine": "vllm",
        "params": "2B",
    },
    "exaone-1.2b-vllm": {
        "model": "openai/LGAI-EXAONE/EXAONE-4.0-1.2B",
        "api_base": "http://localhost:8000/v1",
        "engine": "vllm",
        "params": "1.2B",
    },
    # llama-server models (port 8002)
    "exaone-1.2b-llama": {
        "model": "openai/EXAONE-4.0-1.2B-Q4_K_M.gguf",
        "api_base": "http://localhost:8002/v1",
        "engine": "llama",
        "params": "1.2B Q4_K_M",
    },
    "gemma4-e4b-llama": {
        "model": "openai/gemma-4-e4b-it-q4_k_m",
        "api_base": "http://localhost:8002/v1",
        "engine": "llama",
        "params": "4B Q4_K_M",
    },
    "gemma4-e2b-llama": {
        "model": "openai/gemma-4-e2b-it-q4_k_m",
        "api_base": "http://localhost:8002/v1",
        "engine": "llama",
        "params": "2B Q4_K_M",
    },
    # SGLang models (port 8003)
    "ministral-3b-sglang": {
        "model": "openai/mistralai/Ministral-3-3B-Instruct-2512",
        "api_base": "http://localhost:8003/v1",
        "engine": "sglang",
        "params": "3B",
    },
    "gemma4-e4b-sglang": {
        "model": "openai/google/gemma-4-E4B-it",
        "api_base": "http://localhost:8003/v1",
        "engine": "sglang",
        "params": "4B",
    },
    "gemma4-e2b-sglang": {
        "model": "openai/google/gemma-4-E2B-it",
        "api_base": "http://localhost:8003/v1",
        "engine": "sglang",
        "params": "2B",
    },
    "exaone-1.2b-sglang": {
        "model": "openai/LGAI-EXAONE/EXAONE-4.0-1.2B",
        "api_base": "http://localhost:8003/v1",
        "engine": "sglang",
        "params": "1.2B",
    },
}

# Engine → base model key mapping (for grouping results)
ENGINE_PORTS = {"vllm": 8000, "llama": 8002, "sglang": 8003, "openrouter": None}
# ═══════════════════════════════════════════════════════════════════════════
# Test Cases — Single-Turn
# ═══════════════════════════════════════════════════════════════════════════

SINGLE_TURN_CASES = [
    # ── IDENTITY harm ────────────────────────────────────────────────────
    {
        "id": "pii_mask",
        "name": "PII 포함 (마스킹 후 작업 가능)",
        "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        "expected_sensitive": True,
        "expected_action": "selective_mask",
        "expected_essential": False,
        "tags": ["identity", "creation"],
    },
    {
        "id": "pii_essential",
        "name": "PII 직접 기재 요청",
        "text": "세금 신고서를 작성해야 하는데, 내 주민등록번호 901212-1234567을 기재해줘.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["identity", "interrogation"],
    },
    {
        "id": "name_affiliation",
        "name": "이름+소속",
        "text": "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.",
        "expected_sensitive": True,
        "expected_action": "selective_mask",
        "expected_essential": False,
        "tags": ["identity", "competitive"],
    },
    # ── COMPETITIVE harm ─────────────────────────────────────────────────
    {
        "id": "biz_decision",
        "name": "사업비밀 (creation)",
        "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘.",
        "expected_sensitive": True,
        "expected_action": "selective_mask",
        "expected_essential": False,
        "tags": ["competitive", "creation"],
    },
    {
        "id": "research_idea",
        "name": "연구아이디어 (consultation)",
        "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["competitive", "consultation"],
    },
    {
        "id": "strategy_rationale",
        "name": "전략근거 (statement)",
        "text": "경영진 회의에서 TSMC 대신 삼성 파운드리를 선택하기로 결정했어. 이유는 단가가 15% 저렴해서야.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["competitive", "statement"],
    },
    {
        "id": "vague_experiment",
        "name": "모호한실험결과 (creation)",
        "text": "이 실험 결과를 바탕으로 논문 초안을 작성해줘.",
        "expected_sensitive": True,
        "expected_action": "selective_mask",
        "expected_essential": False,
        "tags": ["competitive", "creation"],
    },
    {
        "id": "methodology",
        "name": "연구방법론 (consultation)",
        "text": "안녕, 나는 광주과학기술원 김동현이야. contextual distillation 연구 중인데, 긴 문서를 청킹해서 유의미한 정보만 추출하는 파이프라인을 만들고 있어. 청킹 방법 조언해줘.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["identity", "competitive", "consultation"],
    },
    {
        "id": "pre_publication",
        "name": "미공개상태",
        "text": "아직 논문에 제출하지 않은 연구 아이디어를 정리해줘.",
        "expected_sensitive": True,
        "expected_action": "selective_mask",
        "expected_essential": False,
        "tags": ["competitive", "creation"],
    },
    {
        "id": "budget",
        "name": "프로젝트예산 (statement)",
        "text": "프로젝트 블루스카이 예산은 1,200억원이고 인건비는 350억원이야.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["competitive", "statement"],
    },
    # ── SAFETY harm ──────────────────────────────────────────────────────
    {
        "id": "internal_url",
        "name": "내부URL",
        "text": "https://internal.company.com/project-x 에서 이번 분기 실적 데이터를 확인해줘.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["safety", "consultation"],
    },
    # ── 명시적 비밀유지 마커 ──────────────────────────────────────────────
    {
        "id": "confidentiality_marker",
        "name": "비밀유지마커",
        "text": "우리가 개발한 새로운 배터리 소재는 비밀로 해줘. 다음 주에 출원할 예정이야.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["competitive", "statement"],
    },
    # ── 복합 케이스 ──────────────────────────────────────────────────────
    {
        "id": "multi_span",
        "name": "다중span+혼합동사",
        "text": "김철수 과장이 010-1234-5678로 연락해서 TSMC 3nm 공정 결정을 알려달라고 했어.",
        "expected_sensitive": True,
        "expected_action": "block",
        "expected_essential": True,
        "tags": ["identity", "competitive", "interrogation"],
    },
    {
        "id": "multiple_pii",
        "name": "전화번호포함 (creation)",
        "text": "연락처: hong@example.com, 010-1234-5678. 위 연락처를 포함한 안내 메일을 작성해줘.",
        "expected_sensitive": True,
        "expected_action": "selective_mask",
        "expected_essential": False,
        "tags": ["identity", "creation"],
    },
    # ── 비민감 ───────────────────────────────────────────────────────────
    {
        "id": "weather",
        "name": "일반날씨",
        "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.",
        "expected_sensitive": False,
        "expected_action": "allow",
        "expected_essential": False,
        "tags": ["none"],
    },
    {
        "id": "python_syntax",
        "name": "일반지식",
        "text": "Python에서 리스트를 정렬하는 방법을 알려줘.",
        "expected_sensitive": False,
        "expected_action": "allow",
        "expected_essential": False,
        "tags": ["none"],
    },
    {
        "id": "startup_advice",
        "name": "일반창업조언",
        "text": "스타트업을 창업하려고 하는데, 사업계획서 작성을 도와줄 수 있어?",
        "expected_sensitive": False,
        "expected_action": "allow",
        "expected_essential": False,
        "tags": ["none"],
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# LLM Calling
# ═══════════════════════════════════════════════════════════════════════════


def call_model(
    model_id: str,
    api_base: str | None,
    prompt_text: str,
    params: dict[str, Any] | None = None,
) -> tuple[str | None, float]:
    """Call a model via litellm. Returns (content, latency_s) or (None, latency_s)."""
    import litellm

    params = params or {}
    messages = [{"role": "user", "content": prompt_text}]

    kwargs = {
        "model": model_id,
        "messages": messages,
        "temperature": params.get("temperature", 0.0),
        "max_tokens": params.get("max_tokens", 4096),
    }
    if api_base:
        kwargs["api_base"] = api_base
    if params.get("top_p") is not None:
        kwargs["top_p"] = params["top_p"]
    if params.get("response_format"):
        kwargs["response_format"] = params["response_format"]

    t0 = time.time()
    try:
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content.strip()
        return content, time.time() - t0
    except Exception:
        import traceback

        traceback.print_exc()
        return None, time.time() - t0


def parse_json_response(content: str | None) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences."""
    if not content:
        return None
    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ```
    m = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try extracting first { ... }
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Extractor Evaluation
# ═══════════════════════════════════════════════════════════════════════════
EXTRACT_PROMPT_PATH = ROOT / "agents" / "extractor" / "extract.prompt"
EXTRACT_SHORT_PROMPT_PATH = ROOT / "agents" / "extractor" / "extract.short.prompt"
_extract_prompt_template: str | None = None
_extract_short_template: str | None = None


def get_extract_prompt(short: bool = False) -> str:
    global _extract_prompt_template, _extract_short_template
    if short:
        if _extract_short_template is None:
            text = EXTRACT_SHORT_PROMPT_PATH.read_text()
            _extract_short_template = text.strip()
        return _extract_short_template
    if _extract_prompt_template is None:
        text = EXTRACT_PROMPT_PATH.read_text()
        parts = text.split("---", 2)
        _extract_prompt_template = parts[-1].strip() if len(parts) >= 3 else text
    return _extract_prompt_template


def evaluate_single_turn(
    model_id: str,
    api_base: str | None,
    case: dict,
    params: dict[str, Any] | None = None,
    engine: str = "vllm",
) -> dict:
    """Evaluate one case. Returns detailed result dict."""
    use_short = "1.2B" in model_id or "E2B" in model_id
    prompt_template = get_extract_prompt(short=use_short)
    prompt_text = prompt_template.replace("{{text}}", case["text"])

    call_params = dict(params or {})
    if "1.2B" in model_id or "E2B" in model_id:
        call_params.setdefault("max_tokens", 512)
    if engine == "vllm" and "EXAONE" in model_id.upper():
        call_params["response_format"] = {"type": "json_object"}

    content, latency = call_model(model_id, api_base, prompt_text, call_params)
    parsed = parse_json_response(content)

    # Evaluate results
    is_sensitive = False
    detected_spans = []
    detected_action = "allow"

    if parsed:
        sens = parsed.get("sensitivity", {})
        is_sensitive = sens.get("is_sensitive", False)
        records = parsed.get("records", parsed.get("extraction_records", []))
        detected_spans = [r.get("span", "") for r in records]
        # Derive action from is_sensitive + is_essential
        if is_sensitive:
            has_essential = any(r.get("is_essential", False) for r in records)
            detected_action = "block" if has_essential else "selective_mask"

    # Compare
    expected_sensitive = case["expected_sensitive"]
    expected_action = case["expected_action"]

    sensitivity_correct = is_sensitive == expected_sensitive
    action_correct = detected_action == expected_action
    json_valid = parsed is not None

    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "text": case["text"][:100],
        "expected_sensitive": expected_sensitive,
        "expected_action": expected_action,
        "detected_sensitive": is_sensitive,
        "detected_action": detected_action,
        "detected_spans": detected_spans,
        "sensitivity_correct": sensitivity_correct,
        "action_correct": action_correct,
        "json_valid": json_valid,
        "latency_s": round(latency, 3),
        "raw_response": content[:500] if content else None,
        "parsed": parsed,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Turn Evaluation
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_multi_turn(
    model_id: str,
    api_base: str | None,
    conversation: dict,
    params: dict[str, Any] | None = None,
    engine: str = "vllm",
) -> dict:
    """Evaluate a multi-turn conversation. Tests each user turn independently."""
    results = []

    for i, turn in enumerate(conversation["turns"]):
        if turn["role"] != "user":
            continue

        case_stub = {
            "id": f"{conversation['id']}_turn{i}",
            "name": f"{conversation['description']} turn {i}",
            "text": turn["content"],
            "expected_sensitive": i in conversation.get("expected_sensitive_turns", []),
            "expected_action": conversation["expected_actions"][i]
            if i < len(conversation.get("expected_actions", []))
            else "allow",
            "expected_essential": False,
            "tags": conversation.get("tags", []),
        }
        result = evaluate_single_turn(model_id, api_base, case_stub, params, engine)
        result["turn_index"] = i
        results.append(result)

    sensitivity_correct = sum(1 for r in results if r["sensitivity_correct"])
    action_correct = sum(1 for r in results if r["action_correct"])

    return {
        "conversation_id": conversation["id"],
        "persona": conversation.get("persona", ""),
        "description": conversation.get("description", ""),
        "n_turns": len(results),
        "sensitivity_accuracy": sensitivity_correct / max(len(results), 1),
        "action_accuracy": action_correct / max(len(results), 1),
        "turn_results": results,
    }


# ═══════════════════════════════════════════════════════════════════════════
# N-Trial Aggregation
# ═══════════════════════════════════════════════════════════════════════════


def run_trials(
    model_key: str,
    model_id: str,
    api_base: str | None,
    engine: str,
    n_trials: int = 5,
    params: dict[str, Any] | None = None,
    cases: list[dict] | None = None,
) -> dict:
    """Run N independent trials on all cases. Returns aggregated results."""
    cases = cases or SINGLE_TURN_CASES
    all_trials = []

    for trial in range(n_trials):
        trial_results = []
        for case in cases:
            result = evaluate_single_turn(model_id, api_base, case, params, engine)
            result["trial"] = trial
            trial_results.append(result)
            # Brief pause to avoid rate limiting
            time.sleep(0.1)
        all_trials.append(trial_results)

    # Aggregate per-case
    case_stats = []
    for ci, case in enumerate(cases):
        case_trials = [all_trials[t][ci] for t in range(n_trials)]
        sensitivity_accs = [t["sensitivity_correct"] for t in case_trials]
        action_accs = [t["action_correct"] for t in case_trials]
        json_valids = [t["json_valid"] for t in case_trials]
        latencies = [t["latency_s"] for t in case_trials]

        case_stats.append(
            {
                "case_id": case["id"],
                "case_name": case["name"],
                "expected_sensitive": case["expected_sensitive"],
                "expected_action": case["expected_action"],
                "tags": case.get("tags", []),
                "sensitivity_accuracy": statistics.mean(sensitivity_accs),
                "sensitivity_std": statistics.stdev(sensitivity_accs) if len(sensitivity_accs) > 1 else 0,
                "action_accuracy": statistics.mean(action_accs),
                "action_std": statistics.stdev(action_accs) if len(action_accs) > 1 else 0,
                "json_validity": statistics.mean(json_valids),
                "avg_latency_s": statistics.mean(latencies),
                "std_latency_s": statistics.stdev(latencies) if len(latencies) > 1 else 0,
                "per_trial": [
                    {
                        "trial": t,
                        "sensitivity_correct": case_trials[t]["sensitivity_correct"],
                        "action_correct": case_trials[t]["action_correct"],
                        "json_valid": case_trials[t]["json_valid"],
                        "latency_s": case_trials[t]["latency_s"],
                        "detected_sensitive": case_trials[t]["detected_sensitive"],
                        "detected_action": case_trials[t]["detected_action"],
                    }
                    for t in range(n_trials)
                ],
            }
        )

    # Overall metrics
    overall_sensitivity = statistics.mean([c["sensitivity_accuracy"] for c in case_stats])
    overall_action = statistics.mean([c["action_accuracy"] for c in case_stats])
    overall_json = statistics.mean([c["json_validity"] for c in case_stats])
    overall_latency = statistics.mean([c["avg_latency_s"] for c in case_stats])

    # Surface-level metrics (형태적 vs 맥락적)
    FORMAL_TAGS = {"identity"}
    CONTEXTUAL_TAGS = {"competitive", "consultation", "statement", "safety"}
    formal_cases = [c for c in case_stats if set(c.get("tags", [])) & FORMAL_TAGS]
    contextual_cases = [c for c in case_stats if set(c.get("tags", [])) & CONTEXTUAL_TAGS]
    none_cases = [c for c in case_stats if "none" in c.get("tags", [])]

    def _avg(lst, key):
        return round(statistics.mean([c[key] for c in lst]), 4) if lst else 0.0

    surface_metrics = {
        "formal": {
            "n_cases": len(formal_cases),
            "sensitivity_accuracy": _avg(formal_cases, "sensitivity_accuracy"),
            "action_accuracy": _avg(formal_cases, "action_accuracy"),
        },
        "contextual": {
            "n_cases": len(contextual_cases),
            "sensitivity_accuracy": _avg(contextual_cases, "sensitivity_accuracy"),
            "action_accuracy": _avg(contextual_cases, "action_accuracy"),
        },
        "none": {
            "n_cases": len(none_cases),
            "sensitivity_accuracy": _avg(none_cases, "sensitivity_accuracy"),
            "action_accuracy": _avg(none_cases, "action_accuracy"),
        },
    }

    return {
        "model_key": model_key,
        "model_id": model_id,
        "engine": engine,
        "params": params or {},
        "n_trials": n_trials,
        "n_cases": len(cases),
        "timestamp": datetime.now().isoformat(),
        "overall": {
            "sensitivity_accuracy": round(overall_sensitivity, 4),
            "action_accuracy": round(overall_action, 4),
            "json_validity": round(overall_json, 4),
            "avg_latency_s": round(overall_latency, 3),
        },
        "surface": surface_metrics,
        "per_case": case_stats,
        "raw_trials": all_trials,
    }


# ═══════════════════════════════════════════════════════════════════════════
# File I/O
# ═══════════════════════════════════════════════════════════════════════════


def safe_name(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "_", s).strip("_")


def save_result(model_key: str, result: dict) -> Path:
    p = RESULTS_DIR / safe_name(model_key)
    p.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    f = p / f"eval_{ts}.json"
    with open(f, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)
    return f


def load_latest_result(model_key: str) -> dict | None:
    d = RESULTS_DIR / safe_name(model_key)
    if not d.exists():
        return None
    files = sorted(d.glob("eval_*.json"), reverse=True)
    if not files:
        return None
    with open(files[0]) as fp:
        return json.load(fp)


# ═══════════════════════════════════════════════════════════════════════════
# Health Check
# ═══════════════════════════════════════════════════════════════════════════


def check_engine(engine: str) -> bool:
    """Check if an engine is running and responsive."""
    import urllib.request

    # OpenRouter is always available (cloud)
    if engine == "openrouter":
        return True

    port = ENGINE_PORTS.get(engine, 8000)
    url = f"http://localhost:{port}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Report Generation
# ═══════════════════════════════════════════════════════════════════════════


def generate_report(model_keys: list[str] | None = None) -> str:
    """Generate a summary report from saved results."""
    if model_keys is None:
        model_keys = [d.name for d in RESULTS_DIR.iterdir() if d.is_dir()]

    rows = []
    for mk in sorted(model_keys):
        result = load_latest_result(mk)
        if not result:
            continue
        o = result["overall"]
        s = result.get("surface", {})
        rows.append(
            {
                "model": mk,
                "engine": result.get("engine", "?"),
                "params": result.get("params", {}),
                "n_trials": result.get("n_trials", 0),
                "sensitivity_acc": o["sensitivity_accuracy"],
                "action_acc": o["action_accuracy"],
                "json_validity": o["json_validity"],
                "avg_latency": o["avg_latency_s"],
                "formal_act": s.get("formal", {}).get("action_accuracy", 0),
                "formal_n": s.get("formal", {}).get("n_cases", 0),
                "contextual_act": s.get("contextual", {}).get("action_accuracy", 0),
                "contextual_n": s.get("contextual", {}).get("n_cases", 0),
            }
        )

    if not rows:
        return "No results found."

    rows.sort(key=lambda r: r["action_acc"], reverse=True)

    lines = [
        "═══════════════════════════════════════════════════════════════════════════════",
        "  Privacy Router — Model Evaluation Report",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "═══════════════════════════════════════════════════════════════════════════════",
        "",
        f"{'Model':<25} {'Engine':<8} {'N':>3} {'Sens%':>7} {'Act%':>7} {'형태적%':>8} {'맥락적%':>8} {'JSON%':>7} {'Lat':>7}",
        "─" * 82,
    ]
    for r in rows:
        lines.append(
            f"{r['model']:<25} {r['engine']:<8} {r['n_trials']:>3} "
            f"{r['sensitivity_acc']:>6.1%} {r['action_acc']:>6.1%} "
            f"{r['formal_act']:>7.1%} {r['contextual_act']:>7.1%} "
            f"{r['json_validity']:>6.1%} {r['avg_latency']:>6.2f}s"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Privacy Router unified eval runner")
    parser.add_argument("--model", help="Model key from MODELS registry")
    parser.add_argument("--engine", choices=["vllm", "llama", "sglang"], help="Filter models by engine")
    parser.add_argument("--all", action="store_true", help="Run all models across all engines")
    parser.add_argument("--trials", type=int, default=5, help="Number of independent trials (N≥5)")
    parser.add_argument("--report", action="store_true", help="Generate report from saved results")
    parser.add_argument("--check", action="store_true", help="Check engine health")
    parser.add_argument("--params", help="JSON string of LLM params to override")
    args = parser.parse_args()

    if args.report:
        keys = [args.model] if args.model else None
        print(generate_report(keys))
        return

    if args.check:
        for engine in ENGINE_PORTS:
            ok = check_engine(engine)
            status = "✅ UP" if ok else "❌ DOWN"
            print(f"  {engine:>8} (:{ENGINE_PORTS[engine]}): {status}")
        return

    # Determine which models to run
    if args.all:
        models_to_run = list(MODELS.keys())
    elif args.model:
        if args.model not in MODELS:
            print(f"Unknown model: {args.model}")
            print(f"Available: {', '.join(MODELS.keys())}")
            sys.exit(1)
        models_to_run = [args.model]
    elif args.engine:
        models_to_run = [k for k, v in MODELS.items() if v["engine"] == args.engine]
    else:
        parser.print_help()
        sys.exit(1)

    params = json.loads(args.params) if args.params else None
    n_trials = max(args.trials, 5)  # Enforce N≥5

    print(f"Running {len(models_to_run)} model(s), {n_trials} trials each")
    print(f"Results: {RESULTS_DIR}")
    print()

    for mk in models_to_run:
        cfg = MODELS[mk]
        engine = cfg["engine"]

        # Check engine
        if not check_engine(engine):
            print(f"  ⚠️  {mk}: engine '{engine}' not running, skipping")
            continue

        print(f"  Running {mk} ({cfg['params']}) on {engine}...")
        result = run_trials(
            model_key=mk,
            model_id=cfg["model"],
            api_base=cfg.get("api_base"),
            engine=engine,
            n_trials=n_trials,
            params=params,
        )
        path = save_result(mk, result)
        o = result["overall"]
        print(
            f"    Sensitivity: {o['sensitivity_accuracy']:.1%}  Action: {o['action_accuracy']:.1%}  "
            f"JSON: {o['json_validity']:.1%}  Latency: {o['avg_latency_s']:.2f}s"
        )
        print(f"    Saved: {path}")
        print()

    # Final report
    print(generate_report(models_to_run))


if __name__ == "__main__":
    main()
