#!/usr/bin/env python3
"""Generate scripted demo artifacts through the Privacy Router API.

Usage:
    python scripts/generate_demo_logs.py [--api-url http://localhost:8787] [--api-key pr-...]

The fixed scenarios are useful for documentation and demos. Generated output is
not runtime telemetry, a production-availability measurement, or a model-quality study.
"""

import argparse
import json
import urllib.request
from pathlib import Path

# Fixed scenario corpus for repeatable demo coverage; it is not runtime telemetry.
SCENARIOS = [
    {
        "day": 1,
        "title": "General Conversation",
        "description": "일반 대화 — 민감정보 없음",
        "prompts": [
            "안녕하세요, 오늘 날씨가 어떤가요?",
            "파이썬에서 리스트 컴프리헨션 사용법을 알려주세요.",
            "서울에서 맛있는 식당 추천해주세요.",
            "오늘 회의 일정을 정리해주세요.",
            "이 코드의 버그를 찾아주세요: for i in range(10) print(i)",
        ],
    },
    {
        "day": 2,
        "title": "Email Drafting with PII",
        "description": "이메일 초안 작성 — 주민등록번호, 전화번호 포함",
        "prompts": [
            "주민등록번호 901212-1234567을 포함한 이메일을 작성해주세요.",
            "연락처 010-1234-5678로 확인 부탁드립니다.",
            "김철수 연구원의 주민등록번호는 850101-1234567입니다.",
            "오늘 날씨가 좋습니다.",  # non-sensitive
            "이메일 주소 test@example.com으로 발송해주세요.",
        ],
    },
    {
        "day": 3,
        "title": "Research Paper Review",
        "description": "논문 리뷰 — 미공개 연구 아이디어 포함",
        "prompts": [
            "Attention 메커니즘을 완전히 대체할 수 있는 새로운 아이디어를 구상 중이다.",
            "Transformer의 병목을 해결할 수 있는 방향으로 접근하려 합니다.",
            "이 논문의 관련 연구 섹션을 검토해주세요.",  # non-sensitive
            "새로운 강화학습 알고리즘의 실험 결과를 분석해주세요.",
            "참고文献 목록을 정리해주세요.",  # non-sensitive
        ],
    },
    {
        "day": 4,
        "title": "Lab Note Organization",
        "description": "실험 노트 정리 — 내부 비즈니스 결정 포함",
        "prompts": [
            "삼성전자 차세대 AP 개발 건으로, TSMC 3nm 공정을 채택하기로 내부적으로 결정했다.",
            "이 실험 결과를 바탕으로 보고서를 작성해주세요.",
            "새로운 칩 설계의 성능 벤치마크 결과를 정리해주세요.",
            "회의실 예약을 해주세요.",  # non-sensitive
            "경쟁사 대비 성능 우위를 확보할 수 있는 아키텍처 아이디어를 검토 중입니다.",
        ],
    },
    {
        "day": 5,
        "title": "Long-horizon Research Task",
        "description": "장기 연구 태스크 — 복잡한 민감 정보 포함",
        "prompts": [
            "새로운 자연어 처리 모델의 학습 전략을 설계해주세요.",
            "이 모델의 하이퍼파라미터 튜닝 결과를 분석해주세요.",
            "GPU 클러스터의 리소스 사용량을 최적화하는 방안을 제안해주세요.",
            "논문 초안의 서론 부분을 작성해주세요.",
            "이 알고리즘의 시간 복잡도를 분석해주세요.",
            "새로운 데이터셋의 전처리 파이프라인을 설계해주세요.",
            "이 모델의 앙상블 전략을 제안해주세요.",
            "실험 환경 설정을 정리해주세요.",
        ],
    },
    {
        "day": 6,
        "title": "Mixed Sensitive Data",
        "description": "혼합 민감 데이터 — PII + 비즈니스 + 연구",
        "prompts": [
            "주민등록번호 901212-1234567과 연락처 010-1234-5678을 기재합니다.",
            "삼성전자 차세대 AP 개발 건으로, TSMC 3nm 공정을 채택하기로 결정했다.",
            "새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘.",
            "이메일을 작성해주세요.",  # non-sensitive
            "주민등록번호 920303-2345678이 맞는지 확인해줘.",  # sensitive query
            "오늘 회의 내용을 정리해주세요.",
            "새로운 강화학습 알고리즘의 성능을 평가해주세요.",
            "이 코드를 리뷰해주세요.",  # non-sensitive
        ],
    },
    {
        "day": 7,
        "title": "Full Pipeline Demo",
        "description": "전체 파이프라인 데모 — 모든 시나리오 통합",
        "prompts": [
            "안녕하세요",  # non-sensitive
            "주민등록번호 901212-1234567을 마스킹해줘",  # sensitive
            "TSMC 3nm 공정을 채택하기로 결정했다",  # business secret
            "새로운 Attention 대체 아이디어를 구상 중이다",  # research secret
            "이메일을 작성해주세요",  # non-sensitive
            "내 주민등록번호가 뭐야?",  # sensitive query
            "이 코드를 리뷰해주세요",  # non-sensitive
            "새로운 강화학습 알고리즘을 설계해주세요",  # research
            "오늘 날씨가 좋습니다",  # non-sensitive
            "이 실험 결과를 분석해주세요",  # non-sensitive
        ],
    },
]


def classify(api_url: str, api_key: str, text: str) -> dict:
    """Call the classify API endpoint."""
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        f"{api_url}/api/v1/classify",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def generate_log(scenario: dict, api_url: str, api_key: str) -> tuple[str, int]:
    """Generate a markdown log and return its classification failure count."""
    day = scenario["day"]
    title = scenario["title"]
    desc = scenario["description"]
    prompts = scenario["prompts"]

    lines = [
        f"# Scripted Demo Classification — Scenario {day}: {title}",
        "",
        "> **Scripted demo classification run.** Fixed prompts below exercise the supplied Privacy Router endpoint.",
        "> This output is not runtime telemetry, organic agent usage, a production-availability measurement, or a model-quality study.",
        "",
        "## Scenario metadata",
        f"- **Scenario index**: {day}",
        f"- **API**: {api_url}/api/v1/classify",
        f"- **Scenario**: {desc}",
        "",
        "---",
        "",
    ]

    total_sensitive = 0
    total_records = 0
    total_masked = 0
    total_local = 0
    total_failed = 0
    results = []

    for i, prompt in enumerate(prompts, 1):
        try:
            result = classify(api_url, api_key, prompt)
            is_sensitive = result.get("is_sensitive", False)
            records = result.get("records", [])
            policy = result.get("policy_action", "unknown")

            if is_sensitive:
                total_sensitive += 1
                total_records += len(records)
                if policy == "selective_mask":
                    total_masked += 1
                elif policy == "block":
                    total_local += 1
        except Exception as e:
            total_failed += 1
            result = {"is_sensitive": False, "records": [], "policy_action": "error", "error": str(e)}
        results.append(result)

        lines.extend(
            [
                f"## Exchange {i}: {prompt[:50]}",
                "",
                "**사용자 입력**:",
                f"> {prompt}",
                "",
                "**Classify API 응답**:",
                "```json",
                json.dumps(result, ensure_ascii=False, indent=2),
                "```",
                "",
                "**분석**:",
                f"- `is_sensitive: {result.get('is_sensitive', False)}`",
                f"- `records: {len(result.get('records', []))}`",
                f"- `policy_action: {result.get('policy_action', 'unknown')}`",
                "",
                "---",
                "",
            ]
        )

    # Summary table
    lines.extend(
        [
            "## 요약",
            "",
            "| Exchange | 입력 | is_sensitive | records | policy_action |",
            "|----------|------|-------------|---------|---------------|",
        ]
    )

    for i, (prompt, result) in enumerate(zip(prompts, results, strict=False), 1):
        if result.get("policy_action") == "error":
            lines.append(f"| {i} | {prompt[:30]} | error | - | - |")
            continue
        lines.append(
            f"| {i} | {prompt[:30]} | {result.get('is_sensitive', False)} | "
            f"{len(result.get('records', []))} | {result.get('policy_action', 'unknown')} |"
        )

    lines.extend(
        [
            "",
            "**통계**:",
            f"- 총 프롬프트: {len(prompts)}",
            f"- 민감 정보 탐지: {total_sensitive}",
            f"- 탐지된 레코드: {total_records}",
            f"- `selective_mask`: {total_masked}",
            f"- `block`: {total_local}",
            f"- classification failures: {total_failed}",
            "",
        ]
    )

    return "\n".join(lines), total_failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate scripted demo artifacts")
    parser.add_argument("--api-url", default="http://localhost:8787", help="Privacy Router API URL")
    parser.add_argument("--api-key", required=True, help="API key for authentication")
    parser.add_argument(
        "--output",
        default="usage-log/generated-demo",
        help="Output directory for scripted demo artifacts",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== Scripted Demo Classification Generator ===")
    print(f"API: {args.api_url}")
    print(f"Output: {output_dir}")
    print()

    total_failed = 0
    for scenario in SCENARIOS:
        day = scenario["day"]
        title = scenario["title"]
        print(f"Scenario {day}: {title}...", end=" ", flush=True)

        log, failure_count = generate_log(scenario, args.api_url, args.api_key)
        total_failed += failure_count
        filename = f"scenario-{day}-{title.lower().replace(' ', '-')}.md"
        (output_dir / filename).write_text(log)
        if failure_count:
            print(f"FAILED ({failure_count} failed classification(s))")
        else:
            print("OK")

    print()
    if total_failed:
        print(f"=== FAILED: {total_failed} classification call(s) failed; generated files are diagnostic only. ===")
        return 1

    print(f"=== Generated {len(SCENARIOS)} scripted demo classification artifacts in {output_dir}/ ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
