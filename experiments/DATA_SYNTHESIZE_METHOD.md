# DATA_SYNTHESIZE_METHOD.md — Privacy Router 벤치마크 데이터셋 v2 생성 방법론

> **Version**: 2.0.0<br>
> **Created**: 2026-06-24<br>
> **Generator**: `experiments/generate_dataset.py`<br>
> **Output**: `experiments/datasets/benchmark_v2.json`<br>
> **Cases**: 120 (all ≥250 chars, bilingual KO+EN)

---

## 1. 개요

Privacy Router의 Extractor→Judge 파이프라인 평가를 위한 합성 테스트 데이터셋.<br>
기존 25케이스(`local_benchmark.py`의 `CASES`)에서 **120케이스**로 확장하고,<br>
4단계 민감도 × 3맥락 × 2검출타입 × 2언어 = **48셀 매트릭스**를 완전 커버.

### 기존 데이터셋과의 관계

| 데이터셋 | 경로 | 케이스 수 | 용도 |
|---|---|---|---|
| ground-truth v1.1.0 | `docs/experiments/ground-truth.json` | 27 | Optuna 파라미터 튜닝 (fewshot_v2 프롬프트) |
| local_benchmark CASES | `experiments/local_benchmark.py` | 25 | 로컬 모델 벤치마크 (Extractor→Judge) |
| **benchmark_v2** | `experiments/datasets/benchmark_v2.json` | **120** | 종합 평가 (전 매트릭스 커버) |

---

## 2. 설계 매트릭스

### 2.1 축 정의

| 축 | 값 | 설명 |
|---|---|---|
| **Sensitivity Level** | L1, L2, L3, L4 | 민감도 4단계 (아래 §2.2) |
| **Context** | personal, corporate, research | 정보 주체 영역 |
| **Detection Type** | morphological, contextual, none | 검출 방법론 |
| **Language** | KO, EN | 이중언어 |

### 2.2 민감도 4단계 (Sensitivity Levels)

| Level | 이름 | 설명 | 예시 |
|---|---|---|---|
| **L1** | Obviously Sensitive | 명백히 민감. 누구나 민감하다고 인식 | 주민등록번호, 카드번호, DB 비밀번호, M&A 정보 |
| **L2** | Insider-Sensitive | 도메인 지식 필요. 내부자만 민감 인식 | 환자번호, 연구비 카드, IRB 번호, 인력 구조조정 |
| **L3** | Ambiguous | 경계선. 맥락에 따라 민감/비민감 판단 가능 | 차량번호, 수면 패턴, 출장 보고서, 실험 설계 |
| **L4** | Not Sensitive | 민감 정보 없음. 안전하게 외부 전송 가능 | 날씨, 레시피, 프로그래밍 질문 |

**핵심 구분**: Level은 "얼마나 민감한가"가 아니라 "누가 민감하다고 인식하는가"의 기준.

### 2.3 Action Policy

`sensitivity_level`과 `detection_type`에 따른 예상 action:

| | Morphological | Contextual | None |
|---|---|---|---|
| **L1** | selective_mask / block | block | — |
| **L2** | selective_mask | selective_mask / block | — |
| **L3** | selective_mask | selective_mask / allow | — |
| **L4** | — | — | allow |

**선택 기준**:
- `is_essential=True` 레코드가 하나라도 있으면 → `block` (로컬 라우팅)
- `is_essential=False`만 있으면 → `selective_mask` (마스킹 후 외부 전송)
- 레코드 없음 → `allow` (외부 전송)

### 2.4 셀 커버리지

```
L1-L3: 3레벨 × 3맥락 × 2검출타입 × 2언어 = 36셀 × 3케이스 = 108케이스
L4:     1레벨 × 3맥락 × 2언어           =  6셀 × 2케이스 =  12케이스
합계: 120케이스
```

L4는 `detection_type=none`만 사용 (민감 정보가 없으므로 morph/ctx 구분 불필요).

---

## 3. 생성 방법론

### 3.1 템플릿 기반 슬롯 필링

모든 케이스는 **수작업 작성된 템플릿** + **슬롯 값 치환**으로 생성.

```python
# 템플릿 구조
add(pid, action, dtype, lang, sens, ctx, records_spec, text_template)

# 예시
add("l1_per_m", "block", "morphological", "KO", "L1", "personal",
    [("CREDIT_CARD_NUMBER", "card", True)],          # records_spec
    "신용카드 번호 {s[card]}로 온라인 결제를...")       # text_template
```

**`records_spec`**: `(category, slot_key, is_essential)` 튜플 목록<br>
- `category`: SCREAMING_SNAKE_CASE (ExtractRecord.category에 매핑)
- `slot_key`: 슬롯 사전의 키 (텍스트에 삽입될 실제 값)
- `is_essential`: Judge가 action을 결정하는 핵심 플래그

### 3.2 슬롯 사전 (Slot Dictionary)

합성 데이터의 다양성을 위해 **반복 가능한 가상 값**을 슬롯으로 관리:

| 슬롯 키 | 값 예시 | 비고 |
|---|---|---|
| `ssn_ko` | 901212-1234567, 880515-2345678 | 한국 주민등록번호 패턴 |
| `ssn_en` | 123-45-6789, 234-56-7890 | 미국 SSN 패턴 |
| `card` | 4532-1234-5678-9012 | 신용카드 번호 패턴 |
| `api_key` | sk-proj-abc123def456ghi789 | OpenAI/GCP 스타일 |
| `passwd` | Str0ng!Pass#2024 | 합성 비밀번호 |
| `ip` | 192.168.1.100 | 사설 IP |
| `patent` | KR-10-2024-0123456 | 한국/미국 특허번호 패턴 |

**슬롯 치환 방식**: 케이스 인덱스 `idx % len(slot_list)` 로 순환 선택.

### 3.3 길이 패딩 (Text Padding)

한국어 텍스트는 정보 밀도가 높아 템플릿만으로 250자를 달성하기 어려움.<br>
→ `pad_text()` 함수로 맥락 적합한 문장을 자동 추가:

```python
PAD_KO = [
    " 추가로 관련 배경 정보와 함께 상세한 설명을 부탁드리며...",
    " 이 작업과 관련된 세부 사항들도 함께 포함해주시면...",
    " 전체적인 흐름과 맥락을 고려하여 종합적으로 분석해주시고...",
]
PAD_EN = [
    " Additionally, please include relevant background information...",
    " Please ensure all relevant contextual details are included...",
    " Take into account the full context and provide a thorough analysis...",
]
```

**패딩 규칙**: 텍스트 길이 < 250자일 때까지 해당 언어의 패딩 문장을 순환 추가.

---

## 4. 검증 체크리스트

생성 후 자동 검증 수행 항목 (10 checks):

| # | 검증 항목 | 기준 | 결과 |
|---|---|---|---|
| 1 | ID 중복 없음 | 120 unique IDs | ✅ |
| 2 | 텍스트 길이 ≥250자 | min=250, avg=317 | ✅ |
| 3 | Span 유효성 | 모든 record.span이 text에 존재 | ✅ (fix 후) |
| 4 | Action-민감도 일관성 | L1/L2≠allow, L4=allow | ✅ |
| 5 | Essential+allow 불일치 없음 | essential=True → allow 불가 | ✅ |
| 6 | 민감 케이스에 records 존재 | is_sensitive=True → records≥1 | ✅ |
| 7 | 비민감 케이스에 records 없음 | is_sensitive=False → records=[] | ✅ |
| 8 | 매트릭스 완전 커버 | 48셀 빠짐없이 | ✅ |
| 9 | Category 다양성 | 42개 고유 카테고리 | ✅ |
| 10 | 언어 균형 | KO=60, EN=60 | ✅ |

### 발견 및 수정된 이슈

- **Span mismatch** (l2_res_m_EN_065): 영어 템플릿이 "Card ending 8901"으로 하드코딩 → `{s[card_mask]}`로 수정

---

## 5. 통계

```
Total cases: 120
By sensitivity: L1=36, L2=36, L3=36, L4=12
By context: personal=40, corporate=40, research=40
By language: KO=60, EN=60
By detection_type: morphological=54, contextual=54, none=12
By action: selective_mask=66, block=28, allow=26
Avg text length: 317 chars
Min text length: 250 chars
Unique record categories: 42
```

---

## 6. JSON 스키마

```json
{
  "version": "2.0.0",
  "created": "2026-06-24T22:34:46",
  "total_cases": 120,
  "statistics": { ... },
  "cases": [
    {
      "id": "l1_per_m_KO_000",
      "text": "주민등록번호 901212-1234567을 사용하여...",
      "expected_action": "selective_mask",
      "detection_type": "morphological",
      "language": "KO",
      "sensitivity_level": "L1",
      "context": "personal",
      "is_sensitive": true,
      "records": [
        {
          "category": "PERSONAL_IDENTIFIER_NUMBER",
          "span": "901212-1234567",
          "is_essential": true
        }
      ],
      "text_length": 264
    }
  ]
}
```

---

## 7. local_benchmark 통합 방법

기존 `experiments/local_benchmark.py`의 `CASES` 리스트를 benchmark_v2로 교체:

```python
# local_benchmark.py 상단에 추가
import json
from pathlib import Path

_BENCH_V2 = json.loads(
    (Path(__file__).resolve().parent / "datasets" / "benchmark_v2.json").read_text()
)

CASES = [
    {
        "name": f"{c['language']}: {c['id']}",
        "text": c["text"],
        "action": c["expected_action"],
        "detection_type": c["detection_type"],
    }
    for c in _BENCH_V2["cases"]
]
```

**주의**: 기존 25케이스 결과와 새 120케이스 결과는 직접 비교 불가.<br>
케이스 구성이 다름 (기존: mixed/safe 케이스 포함, 새: 체계적 매트릭스).

---

## 8. 한계 및 향후 개선

### 현재 한계

1. **합성 데이터 특성**: 실제 사용자 입력이 아닌 패턴 기반 생성 → 실제 서비스 분포와 차이 가능
2. **L3 액션 불확실성**: L3 케이스의 `expected_action`은 설계자의 판단. 실제 LLM이 동의하지 않을 수 있음
3. **패딩 문장의 자연스러움**: 길이 맞춤용 패딩이 테스트 시나리오의 맥락을 희석할 수 있음
4. **한국어-영어 비대칭**: 같은 시나리오의 KO/EN 버전이 완전히 동일하지 않음 (템플릿 독립 작성)

### 향후 개선 방향

1. **실제 사용자 로그 기반**: DB의 46개 실제 usage_log에서 패턴 추출 → 합성에 반영
2. **엣지 케이스 추가**: 다중 레코드 혼합 (PII+사업비밀), 부분 마스킹 시나리오
3. **난이도 조절**: 같은 셀 안에서 easy/medium/hard 난이도 분산
4. **LLM 기반 생성 검증**: 대형 모델로 생성된 텍스트의 자연스러움 점수화

---

## 9. 파일 구조

```
experiments/
├── generate_dataset.py          # 생성 스크립트 (실행 가능)
├── datasets/
│   └── benchmark_v2.json        # 생성된 데이터셋 (120 cases)
├── local_benchmark.py           # 벤치마크 실행 스크립트
└── results/
    ├── local_benchmark.json     # 벤치마크 결과 (summary)
    └── local_benchmark_details.json  # 상세 결과
```

---

## 10. 생성 재현

```bash
cd ~/privacy-router
python3 experiments/generate_dataset.py
# → experiments/datasets/benchmark_v2.json 생성

# 검증
python3 -c "
import json
with open('experiments/datasets/benchmark_v2.json') as f:
    d = json.load(f)
print(f'Total: {d[\"total_cases\"]} cases')
print(f'Min text: {min(c[\"text_length\"] for c in d[\"cases\"])} chars')
"
```
