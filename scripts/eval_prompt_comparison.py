#!/usr/bin/env python3
"""Privacy Router — Prompt Variant Comparison Experiment.

Compares 3 prompt variants across online models:
  A (baseline): Current Socratic dynamic derivation
  B (twostep):  Three-Harm Test first -> Socratic category derivation
  C (hybrid):   Three-Harm questions integrated into Socratic chain

Usage:
    python scripts/eval_prompt_comparison.py                          # all models, all prompts
    python scripts/eval_prompt_comparison.py --models ministral-3b-2512  # one model
    python scripts/eval_prompt_comparison.py --prompts baseline hybrid   # specific prompts
    python scripts/eval_prompt_comparison.py --trials 3                  # 3 trials instead of 5
    python scripts/eval_prompt_comparison.py --report                    # generate report from cached
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "dummy")

RESULTS_DIR = ROOT / "eval" / "results" / "prompt_comparison"


# ── Prompt variants ─────────────────────────────────────────────────────────

PROMPTS = {
    "baseline": str(ROOT / "eval" / "prompts" / "extract.baseline.prompt"),
    "threeharm": str(ROOT / "eval" / "prompts" / "extract.threeharm.prompt"),
    "twostep": str(ROOT / "eval" / "prompts" / "extract.twostep.prompt"),
    "hybrid": str(ROOT / "eval" / "prompts" / "extract.hybrid.prompt"),
}


# ── Test cases ───────────────────────────────────────────────────────────────

CASES = [
    # ── morphological: 패턴 기반 탐지 (정규식, 키워드) ──
    {
        "name": "PII 포함(creation)",
        "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        "action": "selective_mask",
        "tags": ["identity", "creation"],
        "detection_type": "morphological",
    },
    {
        "name": "PII 직접(interrogation)",
        "text": "내 주민등록번호가 뭐야?",
        "action": "block",
        "tags": ["identity", "interrogation"],
        "detection_type": "morphological",
    },
    {
        "name": "전화번호포함(creation)",
        "text": "연락처: hong@example.com, 010-1234-5678. 위 연락처를 포함한 안내 메일을 작성해줘.",
        "action": "selective_mask",
        "tags": ["identity", "creation"],
        "detection_type": "morphological",
    },
    {
        "name": "내부URL",
        "text": "https://internal.company.com/project-x 에서 이번 분기 실적 데이터를 확인해줘.",
        "action": "block",
        "tags": ["safety", "access"],
        "detection_type": "morphological",
    },
    # ── contextual: 의미 기반 탐지 (AI 추론 필요) ──
    {
        "name": "이름+소속",
        "text": "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.",
        "action": "selective_mask",
        "tags": ["identity", "competitive"],
        "detection_type": "contextual",
    },
    {
        "name": "사업비밀(creation)",
        "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘.",
        "action": "selective_mask",
        "tags": ["competitive", "creation"],
        "detection_type": "contextual",
    },
    {
        "name": "연구아이디어(consultation)",
        "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘.",
        "action": "block",
        "tags": ["competitive", "consultation"],
        "detection_type": "contextual",
    },
    {
        "name": "전략근거(statement)",
        "text": "경영진 회의에서 TSMC 대신 삼성 파운드리를 선택하기로 결정했어. 이유는 단가가 15% 저렴해서야.",
        "action": "block",
        "tags": ["competitive", "statement"],
        "detection_type": "contextual",
    },
    {
        "name": "모호한실험결과(creation)",
        "text": "이 실험 결과를 바탕으로 논문 초안을 작성해줘.",
        "action": "selective_mask",
        "tags": ["competitive", "creation"],
        "detection_type": "contextual",
    },
    {
        "name": "연구방법론(consultation)",
        "text": "안녕, 나는 광주과학기술원 김동현이야. contextual distillation 연구 중인데, 긴 문서를 청킹해서 유의미한 정보만 추출하는 파이프라인을 만들고 있어. 청킹 방법 조언해줘.",
        "action": "block",
        "tags": ["identity", "competitive", "consultation"],
        "detection_type": "contextual",
    },
    {
        "name": "미공개상태",
        "text": "아직 논문에 제출하지 않은 연구 아이디어를 정리해줘.",
        "action": "selective_mask",
        "tags": ["competitive", "creation"],
        "detection_type": "contextual",
    },
    {
        "name": "프로젝트예산(statement)",
        "text": "프로젝트 블루스카이 예산은 1,200억원이고 인건비는 350억원이야.",
        "action": "block",
        "tags": ["competitive", "statement"],
        "detection_type": "contextual",
    },
    {
        "name": "비밀유지마커",
        "text": "우리가 개발한 새로운 배터리 소재는 비밀로 해줘. 다음 주에 출원할 예정이야.",
        "action": "block",
        "tags": ["competitive", "statement"],
        "detection_type": "contextual",
    },
    # ── mixed: 패턴 + 의미 혼합 ──
    {
        "name": "다중span+혼합동사",
        "text": "김철수 과장이 010-1234-5678로 연락해서 TSMC 3nm 공정 결정을 알려달라고 했어.",
        "action": "block",
        "tags": ["identity", "competitive", "interrogation"],
        "detection_type": "mixed",
    },
    # ── none: 비민감 ──
    {
        "name": "일반날씨",
        "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.",
        "action": "allow",
        "tags": ["none"],
        "detection_type": "none",
    },
    {
        "name": "일반지식",
        "text": "Python에서 리스트를 정렬하는 방법을 알려줘.",
        "action": "allow",
        "tags": ["none"],
        "detection_type": "none",
    },
    {
        "name": "일반창업조언",
        "text": "스타트업을 창업하려고 하는데, 사업계획서 작성을 도와줄 수 있어?",
        "action": "allow",
        "tags": ["none"],
        "detection_type": "none",
    },
]

SENSITIVE_CASES = {c["name"] for c in CASES if c["action"] != "allow"}

# ── Online models only ──────────────────────────────────────────────────────

MODELS = {
    "ministral-3b-2512": {
        "model": "openrouter/mistralai/ministral-3b-2512",
        "api_base": None,
        "tier": "edge",
        "params": "3B",
        "platform": "OpenRouter",
        "cost_input": 0.10,
    },
    "granite-4.1-8b": {
        "model": "openrouter/ibm-granite/granite-4.1-8b",
        "api_base": None,
        "tier": "edge",
        "params": "8B",
        "platform": "OpenRouter",
        "cost_input": 0.05,
    },
    "qwen3.5-9b": {
        "model": "openrouter/qwen/qwen3.5-9b",
        "api_base": None,
        "tier": "performant",
        "params": "9B",
        "platform": "OpenRouter",
        "cost_input": 0.04,
    },
    "deepseek-v4-flash": {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "api_base": None,
        "tier": "performant",
        "params": "—",
        "platform": "OpenRouter",
        "cost_input": 0.10,
    },
    "gemma-4-26b-a4b-it": {
        "model": "openrouter/google/gemma-4-26b-a4b-it",
        "api_base": None,
        "tier": "performant",
        "params": "26B",
        "platform": "OpenRouter",
        "cost_input": 0.06,
    },
    "gemini-3.1-flash-lite": {
        "model": "openrouter/google/gemini-3.1-flash-lite",
        "api_base": None,
        "tier": "frontier",
        "params": "—",
        "platform": "OpenRouter",
        "cost_input": 0.25,
    },
}


# ── File helpers ─────────────────────────────────────────────────────────────


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "_", s)
    return s.strip("_")


def result_path(prompt_key: str, model_key: str, case_name: str, trial: int) -> Path:
    return RESULTS_DIR / safe_name(prompt_key) / safe_name(model_key) / f"{safe_name(case_name)}_t{trial}.json"


def has_result(prompt_key: str, model_key: str, case_name: str, trial: int) -> bool:
    return result_path(prompt_key, model_key, case_name, trial).is_file()


def save_result(prompt_key: str, model_key: str, case_name: str, trial: int, data: dict) -> None:
    p = result_path(prompt_key, model_key, case_name, trial)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_result(prompt_key: str, model_key: str, case_name: str, trial: int) -> dict | None:
    p = result_path(prompt_key, model_key, case_name, trial)
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── Runner ───────────────────────────────────────────────────────────────────


def run_single(prompt_key: str, model_key: str, case: dict, trial: int) -> dict:
    """Run one prompt x model x case x trial."""
    from agents.llm import load_prompt, render_prompt
    from agents.router import PrivacyRouter

    cfg = MODELS[model_key]
    model_id = cfg["model"]
    api_base = cfg.get("api_base")
    prompt_path = PROMPTS[prompt_key]

    router = PrivacyRouter(decision_model=model_id, api_base=api_base, extractor_prompt_path=prompt_path)

    result = {
        "prompt_key": prompt_key,
        "model_key": model_key,
        "model_id": model_id,
        "case_name": case["name"],
        "text": case["text"],
        "expected_action": case["action"],
        "tags": case["tags"],
        "trial": trial,
        "timestamp": datetime.now(UTC).isoformat(),
        "llm_input": None,
        "llm_output_content": None,
        "extracted_records": [],
        "sensitivity": None,
        "actual_action": None,
        "target_ok": None,
        "context_ok": None,
        "ok": None,
        "time_s": None,
        "error": None,
    }

    t0 = time.time()

    try:
        prompt = load_prompt(prompt_path)
        result["llm_input"] = render_prompt(prompt["template"], text=case["text"])[:3000]

        r = router.process(case["text"])

        result["sensitivity"] = {"is_sensitive": r.sensitivity.is_sensitive, "rationale": r.sensitivity.rationale}
        result["extracted_records"] = [
            {
                "category": rec.category,
                "span": rec.span,
                "confidence": rec.confidence,
                "detection_type": rec.detection_type,
                "reasoning": rec.reasoning,
                "is_essential": rec.is_essential,
            }
            for rec in r.records
        ]
        result["actual_action"] = r.judgment.policy_action

        expected_sensitive = case["name"] in SENSITIVE_CASES
        actual_sensitive = r.sensitivity.is_sensitive or len(r.records) > 0
        result["target_ok"] = expected_sensitive == actual_sensitive
        result["context_ok"] = r.judgment.policy_action == case["action"]
        result["ok"] = result["target_ok"] and result["context_ok"]

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["ok"] = False
        result["target_ok"] = False
        result["context_ok"] = False

    result["time_s"] = round(time.time() - t0, 1)
    return result


# ── Aggregation ──────────────────────────────────────────────────────────────


def aggregate_model(prompt_key: str, model_key: str, n_trials: int) -> dict:
    """Aggregate N trials per case for a prompt x model."""
    cfg = MODELS[model_key]
    case_results = []

    for case in CASES:
        trials = []
        for t in range(1, n_trials + 1):
            r = load_result(prompt_key, model_key, case["name"], t)
            if r:
                trials.append(r)

        if not trials:
            continue

        ok_count = sum(1 for t in trials if t.get("ok"))
        target_ok_count = sum(1 for t in trials if t.get("target_ok"))
        context_ok_count = sum(1 for t in trials if t.get("context_ok"))
        times = [t["time_s"] for t in trials if t.get("time_s")]
        records_counts = [len(t.get("extracted_records", [])) for t in trials]

        # Consistency: same action across all trials
        actions = [t.get("actual_action", "ERROR") for t in trials]
        consistency = (
            1.0 if len(set(actions)) == 1 else round(1 - (len(set(actions)) - 1) / max(len(actions) - 1, 1), 2)
        )

        # Majority vote
        action_votes: dict[str, int] = {}
        for a in actions:
            action_votes[a] = action_votes.get(a, 0) + 1
        majority_action = max(action_votes, key=lambda k: action_votes[k])

        case_results.append(
            {
                "name": case["name"],
                "text": case["text"],
                "expected_action": case["action"],
                "tags": case["tags"],
                "detection_type": case.get("detection_type", "unknown"),
                "actual_action": majority_action,
                "trials_total": len(trials),
                "ok_rate": round(ok_count / len(trials), 2),
                "target_ok_rate": round(target_ok_count / len(trials), 2),
                "context_ok_rate": round(context_ok_count / len(trials), 2),
                "ok": ok_count == len(trials),
                "target_ok": target_ok_count == len(trials),
                "context_ok": context_ok_count == len(trials),
                "consistency": consistency,
                "avg_time_s": round(sum(times) / len(times), 1) if times else 0,
                "avg_records": round(sum(records_counts) / len(records_counts), 1) if records_counts else 0,
                "trials": trials,
            }
        )

    total = len(case_results)
    if total == 0:
        return {"prompt_key": prompt_key, "model_key": model_key, "total": 0}

    passed = sum(1 for c in case_results if c["ok"])
    target_passed = sum(1 for c in case_results if c["target_ok"])
    context_passed = sum(1 for c in case_results if c["context_ok"])
    avg_consistency = sum(c["consistency"] for c in case_results) / total
    avg_time = sum(c["avg_time_s"] for c in case_results) / total

    # Per-detection_type accuracy
    detection_types = {}
    for dt in ["morphological", "contextual", "mixed", "none"]:
        dt_cases = [c for c in case_results if c["detection_type"] == dt]
        if dt_cases:
            dt_passed = sum(1 for c in dt_cases if c["ok"])
            detection_types[dt] = {
                "total": len(dt_cases),
                "passed": dt_passed,
                "accuracy_pct": round(100 * dt_passed / len(dt_cases), 1),
            }

    return {
        "prompt_key": prompt_key,
        "model_key": model_key,
        "model_id": cfg["model"],
        "tier": cfg["tier"],
        "params": cfg["params"],
        "platform": cfg["platform"],
        "cost_input": cfg["cost_input"],
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "accuracy_pct": round(100 * passed / total, 1),
        "target_pct": round(100 * target_passed / total, 1),
        "context_pct": round(100 * context_passed / total, 1),
        "consistency_pct": round(100 * avg_consistency, 1),
        "avg_s": round(avg_time, 1),
        "detection_types": detection_types,
        "cases": case_results,
    }


# ── HTML report ──────────────────────────────────────────────────────────────


def generate_comparison_report(all_results: list[dict], n_trials: int) -> str:
    """Generate HTML report comparing prompt variants."""
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    data_json = json.dumps({"timestamp": ts, "n_trials": n_trials, "results": all_results}, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy Router -- Prompt Variant Comparison (N={n_trials})</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',-apple-system,sans-serif;background:#0a0e1a;color:#e2e8f0;line-height:1.6;padding:32px 24px}}
.c{{max-width:1400px;margin:0 auto}}
h1{{font-size:24px;font-weight:800;margin-bottom:8px}}
.sub{{color:#64748b;font-size:13px;margin-bottom:32px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:32px}}
th{{text-align:left;padding:10px 12px;background:#111827;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #1e293b;font-weight:600}}
td{{padding:10px 12px;border-bottom:1px solid #111827}}tr:hover td{{background:#111827}}
.vg{{color:#4ade80}}.vb{{color:#60a5fa}}.vy{{color:#fbbf24}}.vr{{color:#f87171}}
.prompt-section{{margin-bottom:48px}}
.prompt-title{{font-size:18px;font-weight:700;margin-bottom:16px;padding:12px 16px;background:#1e293b;border-radius:8px}}
</style>
</head>
<body>
<div class="c">
<h1>Prompt Variant Comparison</h1>
<p class="sub">Generated {ts} -- N={n_trials} trials per case -- Online models only</p>
<div id="app"></div>
</div>
<script>
const D={data_json};

const prompts = [...new Set(D.results.map(r => r.prompt_key))];
const models = [...new Set(D.results.map(r => r.model_key))];

let html = '<div class="prompt-section"><div class="prompt-title">Summary: Accuracy by Prompt x Model</div>';
html += '<table><tr><th>Prompt</th><th>Model</th><th>Params</th><th>Target</th><th>Context</th><th>Overall</th><th>Morphological</th><th>Contextual</th><th>Consistency</th><th>Time</th></tr>';
for (const p of prompts) {{
  for (const m of models) {{
    const r = D.results.find(x => x.prompt_key === p && x.model_key === m);
    if (!r || r.total === 0) continue;
    const accClass = r.accuracy_pct >= 90 ? 'vg' : r.accuracy_pct >= 70 ? 'vb' : r.accuracy_pct >= 50 ? 'vy' : 'vr';
    const conClass = r.consistency_pct >= 90 ? 'vg' : r.consistency_pct >= 70 ? 'vb' : 'vy';
    const morph = r.detection_types?.morphological?.accuracy_pct ?? '-';
    const ctx = r.detection_types?.contextual?.accuracy_pct ?? '-';
    const morphClass = typeof morph === 'number' ? (morph >= 90 ? 'vg' : morph >= 70 ? 'vb' : morph >= 50 ? 'vy' : 'vr') : '';
    const ctxClass = typeof ctx === 'number' ? (ctx >= 90 ? 'vg' : ctx >= 70 ? 'vb' : ctx >= 50 ? 'vy' : 'vr') : '';
    html += `<tr>
      <td>${{p}}</td><td>${{m}}</td><td>${{r.params}}</td>
      <td>${{r.target_pct}}%</td><td>${{r.context_pct}}%</td>
      <td class="${{accClass}}">${{r.accuracy_pct}}%</td>
      <td class="${{morphClass}}">${{morph}}%</td>
      <td class="${{ctxClass}}">${{ctx}}%</td>
      <td class="${{conClass}}">${{r.consistency_pct}}%</td>
      <td>${{r.avg_s}}s</td>
    </tr>`;
  }}
}}
html += '</table></div>';

for (const p of prompts) {{
  html += `<div class="prompt-section"><div class="prompt-title">Prompt: ${{p}}</div>`;
  html += '<table><tr><th>Case</th><th>Expected</th>';
  for (const m of models) {{
    html += `<th>${{m}}</th>`;
  }}
  html += '</tr>';

  const first = D.results.find(x => x.prompt_key === p);
  if (first && first.cases) {{
    for (const c of first.cases) {{
      html += `<tr><td>${{c.name}}</td><td>${{c.expected_action}}</td>`;
      for (const m of models) {{
        const r = D.results.find(x => x.prompt_key === p && x.model_key === m);
        const cc = r ? r.cases.find(x => x.name === c.name) : null;
        if (cc) {{
          const cls = cc.ok ? 'vg' : cc.target_ok ? 'vy' : 'vr';
          html += `<td class="${{cls}}">${{cc.actual_action}} (${{cc.ok_rate}})</td>`;
        }} else {{
          html += '<td>--</td>';
        }}
      }}
      html += '</tr>';
    }}
  }}
  html += '</table></div>';
}}

document.getElementById('app').innerHTML = html;
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Prompt Variant Comparison Experiment")
    parser.add_argument("--models", nargs="*", help="Model keys to test")
    parser.add_argument("--prompts", nargs="*", default=list(PROMPTS.keys()), help="Prompt variants (default: all)")
    parser.add_argument("--trials", type=int, default=5, help="Trials per case (default 5)")
    parser.add_argument("--report", action="store_true", help="Only generate report from cached results")
    args = parser.parse_args()

    model_keys = args.models or list(MODELS.keys())
    prompt_keys = args.prompts
    n_trials = args.trials

    for pk in prompt_keys:
        if pk not in PROMPTS:
            print(f"Unknown prompt: {pk}. Available: {list(PROMPTS.keys())}")
            sys.exit(1)
    for mk in model_keys:
        if mk not in MODELS:
            print(f"Unknown model: {mk}")
            sys.exit(1)

    if not args.report:
        total_new = 0
        total_cached = 0

        for pk in prompt_keys:
            for mk in model_keys:
                cfg = MODELS[mk]
                print(f"\n{'=' * 60}")
                print(f"Prompt: {pk} | Model: {mk} ({cfg['model']})")
                print(f"{'=' * 60}")

                for case in CASES:
                    for t in range(1, n_trials + 1):
                        if has_result(pk, mk, case["name"], t):
                            total_cached += 1
                            continue

                        total_new += 1
                        print(f"  [{case['name']}] trial {t}...", end="", flush=True)
                        try:
                            result = run_single(pk, mk, case, t)
                            save_result(pk, mk, case["name"], t, result)
                            mark = "OK" if result["ok"] else "FAIL"
                            print(f" {mark} {result['actual_action']} ({result['time_s']}s)")
                        except Exception as e:
                            print(f" ERR {e}")
                            save_result(
                                pk,
                                mk,
                                case["name"],
                                t,
                                {
                                    "prompt_key": pk,
                                    "model_key": mk,
                                    "case_name": case["name"],
                                    "trial": t,
                                    "ok": False,
                                    "target_ok": False,
                                    "context_ok": False,
                                    "actual_action": "ERROR",
                                    "error": str(e),
                                    "time_s": 0,
                                    "extracted_records": [],
                                    "sensitivity": None,
                                    "expected_action": case["action"],
                                    "tags": case["tags"],
                                },
                            )

        print(f"\nNew: {total_new} | Cached: {total_cached}")

    # Generate report
    print("\nGenerating report...")
    all_results = []
    for pk in prompt_keys:
        for mk in model_keys:
            agg = aggregate_model(pk, mk, n_trials)
            all_results.append(agg)

    html = generate_comparison_report(all_results, n_trials)
    report_path = RESULTS_DIR / "comparison_report.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")

    agg_path = RESULTS_DIR / "comparison_aggregated.json"
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(
            {"timestamp": datetime.now(UTC).isoformat(), "n_trials": n_trials, "results": all_results},
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\nJSON: {agg_path}")
    print(f"HTML: {report_path}")

    # Print summary
    print(
        f"\n{'Prompt':<12} | {'Model':<25} | {'Target':>6} | {'Context':>6} | {'Acc':>6} | {'Morph':>6} | {'Ctx':>6} | {'Consist':>6} | {'Time':>6}"
    )
    print("-" * 105)
    for r in sorted(all_results, key=lambda x: (x.get("prompt_key", ""), -x.get("accuracy_pct", 0))):
        if r["total"] == 0:
            continue
        morph = r.get("detection_types", {}).get("morphological", {}).get("accuracy_pct", "-")
        ctx = r.get("detection_types", {}).get("contextual", {}).get("accuracy_pct", "-")
        morph_str = f"{morph:>5.1f}%" if isinstance(morph, (int, float)) else f"{morph:>6}"
        ctx_str = f"{ctx:>5.1f}%" if isinstance(ctx, (int, float)) else f"{ctx:>6}"
        print(
            f"{r['prompt_key']:<12} | {r['model_key']:<25} | {r['target_pct']:>5.1f}% | {r['context_pct']:>5.1f}% | {r['accuracy_pct']:>5.1f}% | {morph_str} | {ctx_str} | {r['consistency_pct']:>5.1f}% | {r['avg_s']:>5.1f}s"
        )


if __name__ == "__main__":
    main()
