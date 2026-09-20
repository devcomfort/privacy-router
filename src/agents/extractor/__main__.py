"""Extractor demo."""

from __future__ import annotations

from agents.annotator import IntentAnalyzer
from agents.extractor import Extractor

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
    """Analyze intent, then demonstrate single-pass privacy extraction."""
    print("=" * 70)
    print("Privacy Router - Extractor Demo")
    print("=" * 70)
    print()

    annotator = IntentAnalyzer()

    extractor = Extractor()

    for i, sample in enumerate(SAMPLE_INPUTS, 1):
        print("-" * 70)
        print(f"예시 {i}: {sample['name']}")
        print("-" * 70)
        print()

        print("[입력]")
        print(f"  {sample['text']}")
        print()

        try:
            intent = annotator.annotate(sample["text"])
            result = extractor.extract(sample["text"], intent=intent)
        except Exception as e:
            print(f"ERROR: {e}")
            print()
            continue

        print(f"[의도] {intent.action} · 채널: {intent.channel or '미정'}")
        print("[추출된 정보]")
        if not result.records:
            print("  (없음)")
        else:
            for j, record in enumerate(result.records, 1):
                print(f'  [{j}] {record.category}: "{record.span}"')
                print(f"      confidence: {record.confidence:.2f}")
                for label, judgment in (
                    ("confidentiality", record.confidentiality),
                    ("necessity", record.necessity),
                ):
                    print(f"      {label}: {judgment.value or 'unassessed'} ({judgment.status})")
                    print(f"        reason: {judgment.reason or '(not retained)'}")
        print()

    print("=" * 70)
    print("완료")
    print("=" * 70)


if __name__ == "__main__":
    main()
