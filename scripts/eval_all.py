#!/usr/bin/env python3
"""Privacy Router — Evaluation with per-case caching and N trials.

Each test result is saved as an individual file:
    results/{model_safe}/{case_safe}_t{N}.json

Already-completed tests are skipped (cached). Add models or cases
to the config and re-run — only new work is performed.

Usage:
    python scripts/eval_all.py                              # all models, all cases
    python scripts/eval_all.py --models ministral-3b-2512   # one model
    python scripts/eval_all.py --trials 3                   # 3 trials instead of 5
    python scripts/eval_all.py --report                     # generate HTML from cached results
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "dummy")

RESULTS_DIR = ROOT / "docs" / "devlog" / "results"


# ── Test cases ───────────────────────────────────────────────────────────────

CASES = [
    {"name": "PII 포함(creation)", "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.", "action": "selective_mask", "tags": ["identity", "creation"]},
    {"name": "PII 직접(interrogation)", "text": "내 주민등록번호가 뭐야?", "action": "block", "tags": ["identity", "interrogation"]},
    {"name": "이름+소속", "text": "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.", "action": "selective_mask", "tags": ["identity", "competitive"]},
    {"name": "사업비밀(creation)", "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘.", "action": "selective_mask", "tags": ["competitive", "creation"]},
    {"name": "연구아이디어(consultation)", "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘.", "action": "block", "tags": ["competitive", "consultation"]},
    {"name": "전략근거(statement)", "text": "경영진 회의에서 TSMC 대신 삼성 파운드리를 선택하기로 결정했어. 이유는 단가가 15% 저렴해서야.", "action": "block", "tags": ["competitive", "statement"]},
    {"name": "모호한실험결과(creation)", "text": "이 실험 결과를 바탕으로 논문 초안을 작성해줘.", "action": "selective_mask", "tags": ["competitive", "creation"]},
    {"name": "연구방법론(consultation)", "text": "안녕, 나는 광주과학기술원 김동현이야. contextual distillation 연구 중인데, 긴 문서를 청킹해서 유의미한 정보만 추출하는 파이프라인을 만들고 있어. 청킹 방법 조언해줘.", "action": "block", "tags": ["identity", "competitive", "consultation"]},
    {"name": "미공개상태", "text": "아직 논문에 제출하지 않은 연구 아이디어를 정리해줘.", "action": "selective_mask", "tags": ["competitive", "creation"]},
    {"name": "프로젝트예산(statement)", "text": "프로젝트 블루스카이 예산은 1,200억원이고 인건비는 350억원이야.", "action": "block", "tags": ["competitive", "statement"]},
    {"name": "내부URL", "text": "https://internal.company.com/project-x 에서 이번 분기 실적 데이터를 확인해줘.", "action": "block", "tags": ["safety", "access"]},
    {"name": "비밀유지마커", "text": "우리가 개발한 새로운 배터리 소재는 비밀로 해줘. 다음 주에 출원할 예정이야.", "action": "block", "tags": ["competitive", "statement"]},
    {"name": "다중span+혼합동사", "text": "김철수 과장이 010-1234-5678로 연락해서 TSMC 3nm 공정 결정을 알려달라고 했어.", "action": "block", "tags": ["identity", "competitive", "interrogation"]},
    {"name": "전화번호포함(creation)", "text": "연락처: hong@example.com, 010-1234-5678. 위 연락처를 포함한 안내 메일을 작성해줘.", "action": "selective_mask", "tags": ["identity", "creation"]},
    {"name": "일반날씨", "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.", "action": "allow", "tags": ["none"]},
    {"name": "일반지식", "text": "Python에서 리스트를 정렬하는 방법을 알려줘.", "action": "allow", "tags": ["none"]},
    {"name": "일반창업조언", "text": "스타트업을 창업하려고 하는데, 사업계획서 작성을 도와줄 수 있어?", "action": "allow", "tags": ["none"]},
]

SENSITIVE_CASES = {c["name"] for c in CASES if c["action"] != "allow"}


# ── Model configs ────────────────────────────────────────────────────────────

MODELS = {
    # OpenRouter models
    "ministral-3b-2512": {"model": "openrouter/mistralai/ministral-3b-2512", "api_base": None, "tier": "edge", "params": "3B", "platform": "OpenRouter", "quantization": "—", "cost_input": 0.10, "note": "초경량 SLM"},
    "granite-4.1-8b": {"model": "openrouter/ibm-granite/granite-4.1-8b", "api_base": None, "tier": "edge", "params": "8B", "platform": "OpenRouter", "quantization": "—", "cost_input": 0.05, "note": "이 파이프라인에 부적합"},
    "qwen3.5-9b": {"model": "openrouter/qwen/qwen3.5-9b", "api_base": None, "tier": "performant", "params": "9B", "platform": "OpenRouter", "quantization": "—", "cost_input": 0.04, "note": "느리고 부정확"},
    "deepseek-v4-flash": {"model": "openrouter/deepseek/deepseek-v4-flash", "api_base": None, "tier": "performant", "params": "—", "platform": "OpenRouter", "quantization": "—", "cost_input": 0.10, "note": "양호한 성능"},
    "gemma-4-26b-a4b-it": {"model": "openrouter/google/gemma-4-26b-a4b-it", "api_base": None, "tier": "performant", "params": "26B", "platform": "OpenRouter", "quantization": "—", "cost_input": 0.06, "note": "100% 정확도, 가성비 최고"},
    "gemini-3.1-flash-lite": {"model": "openrouter/google/gemini-3.1-flash-lite", "api_base": None, "tier": "frontier", "params": "—", "platform": "OpenRouter", "quantization": "—", "cost_input": 0.25, "note": "100% 정확도, 속도 최고"},
    "gemma-4-26b-a4b-local": {"model": "openai/google/gemma-4-26B-A4B-it", "api_base": "http://localhost:8000/v1", "tier": "frontier", "params": "26B MoE", "platform": "로컬 GPU (vLLM)", "quantization": "BF16", "cost_input": 0.0, "note": "26B MoE 로컬 (OpenRouter와 비교용)"},
    # Local models (vLLM, GPU) — 한 번에 하나씩 서버 시작 필요
    "gemma-4-e4b-bf16": {"model": "openai/google/gemma-4-E4B-it", "api_base": "http://localhost:8000/v1", "tier": "edge", "params": "4B", "platform": "로컬 GPU (vLLM)", "quantization": "BF16", "cost_input": 0.0, "note": "E4B 원본"},
    "gemma-4-e2b-bf16": {"model": "openai/google/gemma-4-E2B-it", "api_base": "http://localhost:8000/v1", "tier": "edge", "params": "2B", "platform": "로컬 GPU (vLLM)", "quantization": "BF16", "cost_input": 0.0, "note": "E2B 원본"},
    "gemma-4-12b-bf16": {"model": "openai/google/gemma-4-12B-it", "api_base": "http://localhost:8000/v1", "tier": "performant", "params": "12B", "platform": "로컬 GPU (vLLM nightly)", "quantization": "BF16", "cost_input": 0.0, "note": "12B Gemma4Unified"},
    "exaone-4.5-33b-fp8": {"model": "openai//tmp/exaone45-fp8-fixed", "api_base": "http://localhost:8000/v1", "tier": "performant", "params": "33B", "platform": "로컬 GPU (vLLM nightly)", "quantization": "FP8", "cost_input": 0.0, "note": "EXAONE 4.5 33B"},
}


# ── File helpers ─────────────────────────────────────────────────────────────

def safe_name(s: str) -> str:
    """Convert string to filesystem-safe name."""
    s = re.sub(r"[^\w가-힣]+", "_", s)
    return s.strip("_")


def result_path(model_key: str, case_name: str, trial: int) -> Path:
    return RESULTS_DIR / safe_name(model_key) / f"{safe_name(case_name)}_t{trial}.json"


def has_result(model_key: str, case_name: str, trial: int) -> bool:
    return result_path(model_key, case_name, trial).is_file()


def save_result(model_key: str, case_name: str, trial: int, data: dict) -> None:
    p = result_path(model_key, case_name, trial)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_result(model_key: str, case_name: str, trial: int) -> dict | None:
    p = result_path(model_key, case_name, trial)
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── Runner ───────────────────────────────────────────────────────────────────

def run_single(model_key: str, case: dict, trial: int) -> dict:
    """Run one model × case × trial. Returns result dict."""
    from agents.router import PrivacyRouter
    import litellm
    from agents.llm import load_prompt, render_prompt

    cfg = MODELS[model_key]
    model_id = cfg["model"]
    api_base = cfg.get("api_base")

    router = PrivacyRouter(extractor_model=model_id, api_base=api_base)

    result = {
        "model_key": model_key, "model_id": model_id,
        "case_name": case["name"], "text": case["text"],
        "expected_action": case["action"], "tags": case["tags"],
        "trial": trial, "timestamp": datetime.now(timezone.utc).isoformat(),
        "llm_input": None, "llm_output_content": None, "llm_output_reasoning": None,
        "extracted_records": [], "sensitivity": None,
        "actual_action": None, "target_ok": None, "context_ok": None,
        "ok": None, "time_s": None, "error": None,
    }

    t0 = time.time()

    try:
        # Store prompt for logging (no separate LLM call)
        from agents.llm import load_prompt, render_prompt
        prompt = load_prompt(str(ROOT / "agents" / "extractor" / "extract.prompt"))
        result["llm_input"] = render_prompt(prompt["template"], text=case["text"])[:3000]

        # Run pipeline (single LLM call)
        r = router.process(case["text"])

        result["sensitivity"] = {"is_sensitive": r.sensitivity.is_sensitive, "rationale": r.sensitivity.rationale}
        result["extracted_records"] = [
            {"category": rec.category, "span": rec.span, "confidence": rec.confidence,
             "detection_type": rec.detection_type, "reasoning": rec.reasoning,
             "is_load_bearing": rec.is_load_bearing}
            for rec in r.records
        ]
        result["actual_action"] = r.judgment.policy_action

        expected_sensitive = case["name"] in SENSITIVE_CASES
        actual_sensitive = r.sensitivity.is_sensitive or len(r.records) > 0
        result["target_ok"] = (expected_sensitive == actual_sensitive)
        result["context_ok"] = (
            r.judgment.policy_action == case["action"]
            or (r.judgment.policy_action == "process_locally" and case["action"] == "block")
        )
        result["ok"] = result["target_ok"] and result["context_ok"]

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["ok"] = False
        result["target_ok"] = False
        result["context_ok"] = False

    result["time_s"] = round(time.time() - t0, 1)
    return result


# ── Aggregation ──────────────────────────────────────────────────────────────

def aggregate_model(model_key: str, n_trials: int) -> dict:
    """Aggregate N trials per case for a model."""
    cfg = MODELS[model_key]
    case_results = []

    for case in CASES:
        trials = []
        for t in range(1, n_trials + 1):
            r = load_result(model_key, case["name"], t)
            if r:
                trials.append(r)

        if not trials:
            continue

        # Aggregate trials
        ok_count = sum(1 for t in trials if t.get("ok"))
        target_ok_count = sum(1 for t in trials if t.get("target_ok"))
        context_ok_count = sum(1 for t in trials if t.get("context_ok"))
        times = [t["time_s"] for t in trials if t.get("time_s")]
        records_counts = [len(t.get("extracted_records", [])) for t in trials]

        # Use majority vote for action
        action_votes = {}
        for t in trials:
            a = t.get("actual_action", "ERROR")
            action_votes[a] = action_votes.get(a, 0) + 1
        majority_action = max(action_votes, key=lambda k: action_votes[k]) if action_votes else "ERROR"

        case_results.append({
            "name": case["name"], "text": case["text"],
            "expected_action": case["action"], "tags": case["tags"],
            "actual_action": majority_action,
            "trials_total": len(trials),
            "ok_rate": round(ok_count / len(trials), 2),
            "target_ok_rate": round(target_ok_count / len(trials), 2),
            "context_ok_rate": round(context_ok_count / len(trials), 2),
            "ok": ok_count == len(trials),
            "target_ok": target_ok_count == len(trials),
            "context_ok": context_ok_count == len(trials),
            "avg_time_s": round(sum(times) / len(times), 1) if times else 0,
            "avg_records": round(sum(records_counts) / len(records_counts), 1) if records_counts else 0,
            "trials": trials,  # full trial data for HTML drill-down
        })

    total = len(case_results)
    if total == 0:
        return {"model_key": model_key, "total": 0}

    passed = sum(1 for c in case_results if c["ok"])
    target_passed = sum(1 for c in case_results if c["target_ok"])
    context_passed = sum(1 for c in case_results if c["context_ok"])
    avg_time = sum(c["avg_time_s"] for c in case_results) / total

    return {
        "model_key": model_key,
        "model_id": cfg["model"],
        "tier": cfg["tier"], "params": cfg["params"],
        "platform": cfg["platform"], "quantization": cfg["quantization"],
        "cost_input": cfg["cost_input"], "note": cfg["note"],
        "passed": passed, "failed": total - passed, "total": total,
        "accuracy_pct": round(100 * passed / total, 1),
        "target_pct": round(100 * target_passed / total, 1),
        "context_pct": round(100 * context_passed / total, 1),
        "avg_s": round(avg_time, 1),
        "cases": case_results,
    }


# ── HTML report ──────────────────────────────────────────────────────────────

def generate_report(all_results: list[dict], n_trials: int) -> str:
    """Generate HTML report from aggregated results."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data_json = json.dumps({"timestamp": ts, "n_trials": n_trials, "models": all_results}, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy Router — Evaluation Report (N={n_trials})</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',-apple-system,sans-serif;background:#0a0e1a;color:#e2e8f0;line-height:1.6}}
.c{{max-width:1400px;margin:0 auto;padding:32px 24px}}
.hdr{{margin-bottom:32px;border-bottom:1px solid #1e293b;padding-bottom:24px}}
.hdr h1{{font-size:24px;font-weight:800}}.hdr .sub{{color:#64748b;font-size:13px;margin-top:4px}}
.sec{{margin-bottom:32px}}.st{{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;margin-bottom:16px;font-weight:600}}
.sg{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.sc{{background:#111827;border:1px solid #1e293b;border-radius:10px;padding:16px}}
.sc .l{{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:#64748b;margin-bottom:4px}}
.sc .v{{font-size:28px;font-weight:800}}.sc .d{{font-size:11px;color:#94a3b8;margin-top:4px}}
.vg{{color:#4ade80}}.vb{{color:#60a5fa}}.vy{{color:#fbbf24}}.vp{{color:#c084fc}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:10px 12px;background:#111827;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #1e293b;font-weight:600}}
td{{padding:10px 12px;border-bottom:1px solid #111827}}tr:hover td{{background:#111827}}
.mn{{font-weight:700}}.tier{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600}}
.tier-edge{{background:#1e3a5f;color:#60a5fa}}.tier-performant{{background:#1e3a2f;color:#4ade80}}.tier-frontier{{background:#3b1e5f;color:#c084fc}}
.ab{{display:inline-flex;align-items:center;gap:6px}}.abt{{width:70px;height:6px;background:#1e293b;border-radius:3px;overflow:hidden}}
.abf{{height:100%;border-radius:3px}}.ag{{background:#4ade80}}.ay{{background:#fbbf24}}.ar{{background:#f87171}}
.tabs{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.tab{{background:#111827;border:1px solid #1e293b;color:#94a3b8;padding:6px 14px;border-radius:6px;font-size:12px;cursor:pointer}}
.tab:hover{{border-color:#334155;color:#e2e8f0}}.tab.a{{background:#1e293b;border-color:#3b82f6;color:#e2e8f0}}
.cc{{background:#111827;border:1px solid #1e293b;border-radius:10px;margin-bottom:16px;overflow:hidden}}
.ch{{padding:12px 16px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #1e293b;cursor:pointer;flex-wrap:wrap}}
.ch:hover{{background:#1a2035}}.cn{{font-weight:700;font-size:14px;flex:1}}
.cat{{font-size:10px;text-transform:uppercase;letter-spacing:.8px;padding:2px 8px;border-radius:3px;font-weight:600}}
.ct{{background:#1e3a5f;color:#60a5fa}}.cx{{background:#3b1e5f;color:#c084fc}}
.ce{{font-size:11px;color:#94a3b8}}.cb{{padding:12px 16px;display:none}}.cb.open{{display:block}}
.tx{{font-size:13px;line-height:1.8;color:#cbd5e1;padding:10px 14px;background:#0a0e1a;border-radius:6px;border-left:3px solid #334155;margin-bottom:12px}}
.gt{{background:rgba(251,191,36,.15);color:#fbbf24;padding:1px 3px;border-radius:2px;font-weight:600;border-bottom:2px solid #fbbf24}}
.tg{{display:inline-block;background:#1e293b;color:#94a3b8;padding:2px 8px;border-radius:4px;font-size:11px;margin-right:4px;margin-bottom:4px}}
.md{{background:#111827;border:1px solid #1e293b;border-radius:8px;margin-top:12px;overflow:hidden}}
.md-h{{padding:10px 14px;display:flex;align-items:center;gap:10px;cursor:pointer;background:#0f172a}}
.md-h:hover{{background:#1a2035}}.md-m{{font-weight:700;font-size:13px;flex:1}}
.md-r{{font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600}}
.md-r.ok{{background:#0a2e1a;color:#4ade80}}.md-r.fail{{background:#2e0a0a;color:#f87171}}
.md-b{{padding:14px;display:none;border-top:1px solid #1e293b}}.md-b.open{{display:block}}
.md-s{{margin-bottom:12px}}.md-st{{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#64748b;margin-bottom:6px;font-weight:600}}
.md-pre{{background:#0a0e1a;border:1px solid #1e293b;border-radius:6px;padding:10px 14px;font-size:11px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;word-break:break-all;color:#94a3b8;max-height:300px;overflow-y:auto}}
.md-pre .think{{color:#6366f1}}.md-pre .cont{{color:#4ade80}}
.rec{{background:#0a0e1a;border:1px solid #1e293b;border-radius:6px;padding:8px 12px;margin-bottom:6px;font-size:12px}}
.rec .rc{{color:#60a5fa;font-weight:600}}.rec .rs{{color:#fbbf24}}
.rec .rt{{font-size:10px;color:#64748b;margin-top:3px}}
.rec .rlb{{font-size:10px;margin-top:2px}}.rec .rlb.y{{color:#f87171}}.rec .rlb.n{{color:#4ade80}}
.dg{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px;margin-bottom:12px}}
.di{{background:#0a0e1a;border:1px solid #1e293b;border-radius:6px;padding:8px 12px;font-size:12px}}
.di .dl{{font-size:10px;color:#64748b;margin-bottom:2px}}.di .dv{{font-weight:600}}
.rate{{font-size:11px;color:#64748b}}
</style>
</head>
<body>
<div class="c">
<div class="hdr"><h1>🛡️ Privacy Router — Evaluation Report</h1><div class="sub" id="ts"></div></div>
<div class="sec"><div class="st">Executive Summary</div><div class="sg" id="sg"></div></div>
<div class="sec"><div class="st">Model Comparison (N trials per case)</div>
<table><thead><tr><th>Model</th><th>Tier</th><th>Params</th><th>Platform</th><th>Quant.</th><th>$/1M</th><th>타겟 식별</th><th>맥락적 식별</th><th>종합</th><th>AvgTime</th><th>비고</th></tr></thead><tbody id="mt"></tbody></table></div>
<div class="sec"><div class="st">Test Cases</div><div class="tabs" id="tabs"></div><div id="cl"></div></div>
<script>
const D={data_json};
function init(){{document.getElementById('ts').textContent=D.timestamp+' | N='+D.n_trials;rs();rt();rb();rc('all')}}
function rs(){{
  const e=D.models.filter(m=>m.total>0);if(!e.length)return;
  const best=e.reduce((a,b)=>a.accuracy_pct>b.accuracy_pct?a:b);
  const fast=e.reduce((a,b)=>a.avg_s<b.avg_s?a:b);
  const perf=e.filter(x=>x.accuracy_pct===100);
  document.getElementById('sg').innerHTML=`
    <div class="sc"><div class="l">최고 정확도</div><div class="v vg">${{best.accuracy_pct}}%</div><div class="d">${{best.model_key}}</div></div>
    <div class="sc"><div class="l">타겟 식별 100%</div><div class="v vb">${{e.filter(x=>x.target_pct===100).length}}개 모델</div></div>
    <div class="sc"><div class="l">맥락적 식별 100%</div><div class="v vp">${{e.filter(x=>x.context_pct===100).length}}개 모델</div></div>
    <div class="sc"><div class="l">최고 속도</div><div class="v vy">${{fast.avg_s}}s</div><div class="d">${{fast.model_key}}</div></div>
    <div class="sc"><div class="l">100% 모델</div><div class="v vg">${{perf.length}}개</div></div>
    <div class="sc"><div class="l">테스트 케이스</div><div class="v">${{D.models[0]?.total||0}}</div><div class="d">${{e.length}}개 모델 × N=${{D.n_trials}}</div></div>`;
}}
function rt(){{
  const tb=document.getElementById('mt');
  D.models.filter(m=>m.total>0).sort((a,b)=>b.accuracy_pct-a.accuracy_pct).forEach(m=>{{
    tb.innerHTML+=`<tr><td class="mn">${{m.model_key}}</td><td><span class="tier tier-${{m.tier}}">${{m.tier}}</span></td><td>${{m.params}}</td><td style="font-size:11px">${{m.platform}}</td><td style="font-size:11px">${{m.quantization}}</td><td>${{m.cost_input!=null?'$'+m.cost_input:'—'}}</td><td>${{bar(m.target_pct)}}</td><td>${{bar(m.context_pct)}}</td><td>${{bar(m.accuracy_pct)}}</td><td>${{m.avg_s}}s</td><td style="font-size:11px;color:#94a3b8">${{m.note||''}}</td></tr>`;
  }});
}}
function bar(p){{const c=p>=80?'ag':p>=60?'ay':'ar';return`<div class="ab"><div class="abt"><div class="abf ${{c}}" style="width:${{p}}%"></div></div><span>${{p}}%</span></div>`;}}
function rb(){{
  const t=document.getElementById('tabs');
  [['all','전체'],['target','타겟 식별'],['context','맥락적 식별']].forEach(([k,l],i)=>{{
    const el=document.createElement('div');el.className='tab'+(i===0?' a':'');el.textContent=l;
    el.onclick=()=>{{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('a'));el.classList.add('a');rc(k);}};
    t.appendChild(el);
  }});
}}
function rc(f){{
  const cl=document.getElementById('cl');cl.innerHTML='';
  const allCases={{}};
  D.models.forEach(m=>{{
    (m.cases||[]).forEach(c=>{{
      if(!allCases[c.name])allCases[c.name]={{...c,models:{{}}}};
      allCases[c.name].models[m.model_key]=c;
    }});
  }});
  Object.values(allCases).filter(c=>f==='all'||(f==='target'&&c.tags?.some(t=>['identity','safety'].includes(t)))||(f==='context'&&c.tags?.some(t=>['competitive','consultation','statement','interrogation'].includes(t)))).forEach(c=>{{
    const catL=c.tags?.some(t=>['identity','safety'].includes(t))?'타겟 식별':'맥락적 식별';
    const catC=c.tags?.some(t=>['identity','safety'].includes(t))?'ct':'cx';
    const tagsH=(c.tags||[]).map(t=>`<span class="tg">${{t}}</span>`).join('');
    let modelsH='';
    Object.entries(c.models).forEach(([mk,mc])=>{{
      const oc=mc.ok?'ok':'fail';const mark=mc.ok?'✅':'❌';
      const tL=mc.target_ok?'✅ 타겟 식별':'❌ 타겟 식별';
      const cL=mc.context_ok?'✅ 맥락적 식별':'❌ 맥락적 식별';
      let recsH='';
      const bestTrial=(mc.trials||[]).reduce((a,b)=>(a.extracted_records?.length||0)>=(b.extracted_records?.length||0)?a:b,{{}});
      (bestTrial.extracted_records||[]).forEach(r=>{{
        recsH+=`<div class="rec"><span class="rc">${{r.category}}</span>: <span class="rs">"${{esc(r.span)}}"</span><div class="rt">confidence: ${{r.confidence}} | detection_type: ${{r.detection_type}}</div><div class="rt">${{esc(r.reasoning||'')}}</div><div class="rlb ${{r.is_load_bearing?'y':'n'}}">load_bearing: ${{r.is_load_bearing}}</div></div>`;
      }});
      if(!recsH)recsH='<div style="font-size:12px;color:#64748b">추출된 레코드 없음</div>';
      let trialDetail='';
      (mc.trials||[]).forEach((t,i)=>{{
        const tt=t.time_s||0;const tok=t.ok?'✅':'❌';
        trialDetail+=`<div style="font-size:11px;color:#64748b">Trial ${{i+1}}: ${{tok}} ${{t.actual_action||'ERROR'}} (${{tt}}s)</div>`;
      }});
      const inputH=bestTrial.llm_input?`<div class="md-s"><div class="md-st">LLM 입력</div><div class="md-pre">${{esc(bestTrial.llm_input).substring(0,1500)}}</div></div>`:'';
      const reasonH=bestTrial.llm_output_reasoning?`<div class="md-s"><div class="md-st">사고 과정 (Reasoning)</div><div class="md-pre think">${{esc(bestTrial.llm_output_reasoning).substring(0,2000)}}</div></div>`:'';
      const contentH=bestTrial.llm_output_content?`<div class="md-s"><div class="md-st">LLM 출력</div><div class="md-pre cont">${{esc(bestTrial.llm_output_content)}}</div></div>`:'';
      modelsH+=`
        <div class="md">
          <div class="md-h" onclick="this.nextElementSibling.classList.toggle('open')">
            <span class="md-m">${{mk}}</span>
            <span class="md-r ${{oc}}">${{mark}} 정확도 ${{mc.ok_rate*100}}% (${{mc.trials_total}} trials)</span>
            <span class="rate">타겟 ${{mc.target_ok_rate*100}}% | 맥락 ${{mc.context_ok_rate*100}}% | avg ${{mc.avg_time_s}}s</span>
          </div>
          <div class="md-b">
            <div class="dg">
              <div class="di"><div class="dl">기대 판단</div><div class="dv">${{mc.expected_action}}</div></div>
              <div class="di"><div class="dl">실제 판단 (다수결)</div><div class="dv">${{mc.actual_action}}</div></div>
              <div class="di"><div class="dl">타겟 식별 통과율</div><div class="dv">${{mc.target_ok_rate*100}}%</div></div>
              <div class="di"><div class="dl">맥락적 식별 통과율</div><div class="dv">${{mc.context_ok_rate*100}}%</div></div>
              <div class="di"><div class="dl">평균 추출 레코드</div><div class="dv">${{mc.avg_records}}건</div></div>
              <div class="di"><div class="dl">평균 소요 시간</div><div class="dv">${{mc.avg_time_s}}s</div></div>
            </div>
            <div class="md-s"><div class="md-st">시행별 결과</div>${{trialDetail}}</div>
            <div class="md-s"><div class="md-st">추출된 레코드 (최다 추출 시행 기준)</div>${{recsH}}</div>
            ${{inputH}}${{reasonH}}${{contentH}}
          </div>
        </div>`;
    }});
    cl.innerHTML+=`<div class="cc"><div class="ch" onclick="this.nextElementSibling.classList.toggle('open')"><span class="cn">${{c.name}}</span><span class="cat ${{catC}}">${{catL}}</span><span class="ce">Expected: ${{c.expected_action}} | N=${{D.n_trials}}</span></div><div class="cb"><div class="tx">${{esc(c.text)}}</div><div style="margin-bottom:12px">${{tagsH}}</div>${{modelsH}}</div></div>`;
  }});
}}
function esc(s){{const d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
init();
</script>
</body>
</html>'''


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", help="Model keys to test")
    parser.add_argument("--trials", type=int, default=5, help="Trials per case (default 5)")
    parser.add_argument("--report", action="store_true", help="Only generate report from cached results")
    args = parser.parse_args()

    model_keys = args.models or list(MODELS.keys())
    n_trials = args.trials

    if not args.report:
        # Run tests
        total_new = 0
        total_cached = 0

        for mk in model_keys:
            if mk not in MODELS:
                print(f"Unknown model: {mk}")
                continue

            cfg = MODELS[mk]
            print(f"\n{'='*60}")
            print(f"Model: {mk} ({cfg['model']})")
            print(f"{'='*60}")

            for case in CASES:
                for t in range(1, n_trials + 1):
                    if has_result(mk, case["name"], t):
                        total_cached += 1
                        continue

                    total_new += 1
                    print(f"  [{case['name']}] trial {t}...", end="", flush=True)
                    try:
                        result = run_single(mk, case, t)
                        save_result(mk, case["name"], t, result)
                        mark = "✅" if result["ok"] else "❌"
                        print(f" {mark} {result['actual_action']} ({result['time_s']}s)")
                    except Exception as e:
                        print(f" 💥 {e}")
                        save_result(mk, case["name"], t, {
                            "model_key": mk, "case_name": case["name"], "trial": t,
                            "ok": False, "target_ok": False, "context_ok": False,
                            "actual_action": "ERROR", "error": str(e), "time_s": 0,
                            "extracted_records": [], "sensitivity": None,
                            "expected_action": case["action"], "tags": case["tags"],
                        })

        print(f"\n📊 New: {total_new} | Cached: {total_cached}")

    # Generate report
    print("\nGenerating report...")
    all_results = []
    for mk in model_keys:
        if mk in MODELS:
            agg = aggregate_model(mk, n_trials)
            all_results.append(agg)

    html = generate_report(all_results, n_trials)
    report_path = RESULTS_DIR / "eval_report.html"
    report_path.write_text(html, encoding="utf-8")

    # Also save aggregated JSON
    agg_path = RESULTS_DIR / "eval_aggregated.json"
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now(timezone.utc).isoformat(), "n_trials": n_trials, "models": all_results}, f, ensure_ascii=False, indent=2)

    print(f"\n📄 JSON: {agg_path}")
    print(f"🌐 HTML: {report_path}")

    # Print summary
    print(f"\n{'Model':<25} | {'타겟 식별':>8} | {'맥락적 식별':>8} | {'종합':>8} | {'AvgTime':>8}")
    print("-" * 70)
    for m in sorted(all_results, key=lambda x: x.get("accuracy_pct", 0), reverse=True):
        if m["total"] == 0:
            continue
        print(f"{m['model_key']:<25} | {m['target_pct']:>7.1f}% | {m['context_pct']:>7.1f}% | {m['accuracy_pct']:>7.1f}% | {m['avg_s']:>7.1f}s")


if __name__ == "__main__":
    main()
