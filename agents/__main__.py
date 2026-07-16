"""Privacy Router demo - runs extractor and judge on sample inputs."""

from __future__ import annotations

import os

from agents.extractor import Extractor
from agents.judge import Judge

SAMPLE_INPUTS = [
    {"name": "개인정보 - 단순 포함", "text": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."},
    {"name": "개인정보 - 직접 질의", "text": "내 주민등록번호가 뭐야?"},
    {"name": "사업비밀 - 의사결정 포함", "text": "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘."},
    {"name": "연구비밀 - 아이디어 포함", "text": "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘."},
    {"name": "연구비밀 - 아이디어 자체 질의", "text": "새로운 Attention 대체 아이디어가 뭐야? 자세히 설명해줘."},
    {"name": "연구비밀 - 실험결과 포함", "text": "이 실험 결과를 바탕으로 논문 초안을 작성해줘."},
    {"name": "민감 정보 없음", "text": "오늘 서울 날씨는 맑고 기온은 25도입니다."},
]


def main():
    print("=" * 70)
    print("Privacy Router Demo")
    print("=" * 70)
    print()

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.")
        print("Set the environment variable or add it to .env file.")
        return

    extractor = Extractor()
    judge = Judge()

    for i, sample in enumerate(SAMPLE_INPUTS, 1):
        print("-" * 70)
        print(f"예시 {i}: {sample['name']}")
        print("-" * 70)
        print()

        print("[입력]")
        print(f"  {sample['text']}")
        print()

        try:
            result = extractor.extract(sample["text"])
            records = result.records
            sensitivity = result.sensitivity
        except Exception as e:
            print(f"ERROR: {e}")
            print()
            continue

        print("[민감도 평가]")
        print(f"  민감 정보: {'Yes' if sensitivity.is_sensitive else 'No'}")
        print(f"  근거: {sensitivity.rationale}")
        print()

        print("[추출된 정보]")
        if not records:
            print("  (없음)")
        else:
            for j, record in enumerate(records, 1):
                print(f'  [{j}] {record.category}: "{record.span}"')
                print(f"      confidence: {record.confidence:.2f}")
        print()

        records_dict = [r.model_dump() for r in records]
        judgment = judge.classify(
            sensitivity=sensitivity.model_dump(),
            records=records_dict,
            text=sample["text"],
        )

        print("[판정 결과]")
        mam = judgment.meaningful_after_masking
        print(f"  마스킹 후 유의미: {'Yes' if mam.is_meaningful_after_masking else 'No'}")
        print(f"  근거: {mam.rationale}")
        print(f"  정책: {judgment.policy_action}")
        print()

        print("[추천 전략]")
        print(f"  {judgment.strategy}")
        print()

        print("[판단 근거]")
        print(f"  {judgment.rationale}")
        print()

    print("=" * 70)
    print("완료")
    print("=" * 70)


if __name__ == "__main__":
    main()
