"""Privacy Router — End-to-end evaluation script.

Runs each test case through the full PrivacyRouter pipeline
(Extractor → rule-based routing) and verifies the output matches
expected actions. No multi-trial aggregation needed — the pipeline
is deterministic at temperature=0.

Usage:
    python agents/eval.py                 # test default model
    python agents/eval.py <model_id>      # test specific model
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.router import PrivacyRouter


# ── Test cases ───────────────────────────────────────────────────────────────
# Each case has: name, text, expected action, and tags for analysis.

EXAMPLES = [
    # ── IDENTITY harm ────────────────────────────────────────────────────────
    {
        "name": "PII 포함(creation)",
        "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘.",
        "action": "mask_and_send",
        "tags": ["identity", "creation", "explicit_value"],
    },
    {
        "name": "PII 직접(interrogation)",
        "text": "내 주민등록번호가 뭐야?",
        "action": "prompt_user",
        "tags": ["identity", "interrogation", "topic_only"],
    },
    {
        "name": "이름+소속",
        "text": "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.",
        "action": "mask_and_send",
        "tags": ["identity", "competitive", "creation"],
    },
    # ── COMPETITIVE harm ─────────────────────────────────────────────────────
    {
        "name": "사업비밀(creation)",
        "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘.",
        "action": "mask_and_send",
        "tags": ["competitive", "creation", "business_decision"],
    },
    {
        "name": "연구아이디어(consultation)",
        "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘.",
        "action": "prompt_user",
        "tags": ["competitive", "consultation", "research_idea"],
    },
    {
        "name": "전략근거(statement)",
        "text": "경영진 회의에서 TSMC 대신 삼성 파운드리를 선택하기로 결정했어. 이유는 단가가 15% 저렴해서야.",
        "action": "prompt_user",
        "tags": ["competitive", "statement", "strategy_rationale"],
    },
    {
        "name": "모호한실험결과(creation)",
        "text": "이 실험 결과를 바탕으로 논문 초안을 작성해줘.",
        "action": "mask_and_send",
        "tags": ["competitive", "creation", "vague_reference"],
    },
    {
        "name": "연구방법론(consultation)",
        "text": "안녕, 나는 광주과학기술원 김동현이야. contextual distillation 연구 중인데, 긴 문서를 청킹해서 유의미한 정보만 추출하는 파이프라인을 만들고 있어. 청킹 방법 조언해줘.",
        "action": "prompt_user",
        "tags": ["identity", "competitive", "consultation", "methodology"],
    },
    {
        "name": "미공개상태",
        "text": "아직 논문에 제출하지 않은 연구 아이디어를 정리해줘.",
        "action": "mask_and_send",
        "tags": ["competitive", "creation", "pre_publication_status"],
    },
    {
        "name": "프로젝트예산(statement)",
        "text": "프로젝트 블루스카이 예산은 1,200억원이고 인건비는 350억원이야.",
        "action": "prompt_user",
        "tags": ["competitive", "statement", "budget"],
    },
    # ── SAFETY harm ──────────────────────────────────────────────────────────
    {
        "name": "내부URL",
        "text": "https://internal.company.com/project-x 에서 이번 분기 실적 데이터를 확인해줘.",
        "action": "prompt_user",
        "tags": ["safety", "consultation", "internal_url"],
    },
    # ── 명시적 비밀유지 마커 ──────────────────────────────────────────────────
    {
        "name": "비밀유지마커",
        "text": "우리가 개발한 새로운 배터리 소재는 비밀로 해줘. 다음 주에 출원할 예정이야.",
        "action": "prompt_user",
        "tags": ["competitive", "statement", "explicit_confidentiality"],
    },
    # ── 복합 케이스 ──────────────────────────────────────────────────────────
    {
        "name": "다중span+혼합동사",
        "text": "김철수 과장이 010-1234-5678로 연락해서 TSMC 3nm 공정 결정을 알려달라고 했어.",
        "action": "prompt_user",
        "tags": ["identity", "competitive", "interrogation", "multi_span"],
    },
    {
        "name": "전화번호포함(creation)",
        "text": "연락처: hong@example.com, 010-1234-5678. 위 연락처를 포함한 안내 메일을 작성해줘.",
        "action": "mask_and_send",
        "tags": ["identity", "creation", "multiple_pii"],
    },
    # ── 비민감 ───────────────────────────────────────────────────────────────
    {
        "name": "일반날씨",
        "text": "오늘 서울 날씨는 맑고 기온은 25도입니다.",
        "action": "allow",
        "tags": ["none"],
    },
    {
        "name": "일반지식",
        "text": "Python에서 리스트를 정렬하는 방법을 알려줘.",
        "action": "allow",
        "tags": ["none"],
    },
    {
        "name": "일반창업조언",
        "text": "스타트업을 창업하려고 하는데, 사업계획서 작성을 도와줄 수 있어?",
        "action": "allow",
        "tags": ["none"],
    },
]


def run_eval(model: str | None = None) -> dict:
    """Run all test cases and return results.

    Parameters
    ----------
    model : str or None
        Override model identifier.

    Returns
    -------
    dict
        ``passed``, ``failed``, ``total``, ``time_s``, ``results``.
    """
    router = PrivacyRouter(extractor_model=model) if model else PrivacyRouter()
    results = []
    passed = 0
    t0 = time.time()

    for ex in EXAMPLES:
        records_count = 0
        try:
            r = router.process(ex["text"])
            actual = r.judgment.policy_action
            records_count = len(r.records)
        except Exception as e:
            actual = f"ERROR: {e}"

        ok = actual == ex["action"]
        passed += ok
        results.append({
            "name": ex["name"],
            "expected": ex["action"],
            "actual": actual,
            "ok": ok,
            "records": records_count,
            "tags": ex["tags"],
        })

    return {
        "passed": passed,
        "failed": len(EXAMPLES) - passed,
        "total": len(EXAMPLES),
        "time_s": time.time() - t0,
        "results": results,
    }


def print_report(eval_result: dict, model: str = "") -> None:
    """Print evaluation results as a formatted report."""
    print(f"\n{'='*70}")
    print(f"Model: {model or '(default)'}")
    print(f"{'='*70}")
    print(f"{'케이스':<20} | {'기대':<17} {'실제':<17} | {'레코드':>3} | 결과")
    print("-" * 70)

    for r in eval_result["results"]:
        mark = "✅" if r["ok"] else "❌"
        print(f"{r['name']:<20} | {r['expected']:<17} {r['actual']:<17} | {r['records']:>3} | {mark}")

    print("-" * 70)
    passed = eval_result["passed"]
    total = eval_result["total"]
    elapsed = eval_result["time_s"]
    print(f"통과: {passed}/{total} ({100*passed/total:.0f}%) | 시간: {elapsed:.1f}s | 평균: {elapsed/total:.1f}s")

    # Print failure details
    failures = [r for r in eval_result["results"] if not r["ok"]]
    if failures:
        print(f"\n실패 ({len(failures)}건):")
        for f in failures:
            tags = ", ".join(f["tags"])
            print(f"  ❌ {f['name']}: expected={f['expected']} actual={f['actual']} [{tags}]")


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_eval(model)
    print_report(result, model or "")


if __name__ == "__main__":
    main()
