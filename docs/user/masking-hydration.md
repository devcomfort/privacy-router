# 마스킹 및 복원 (Masking & Hydration)

민감한 원본 텍스트를 요청 단위의 불투명 플레이스홀더로 치환한 뒤 외부 모델에 전송하고, 외부 모델 응답에서 플레이스홀더를 다시 원래 값으로 안전하게 복원(Hydration)하는 핵심 메커니즘입니다.

---

## 1. 데이터 흐름 개요

```text
원본 프롬프트
"주민번호 901212-1234567로 확인 이메일 양식을 작성해줘"
        │
        ▼ (로컬 추출 및 마스킹)
외부 클라우드 모델 전송 텍스트
"주민번호 SENSITIVE_DATA#7fa3c921로 확인 이메일 양식을 작성해줘"
        │
        ▼ (외부 모델 응답 수신)
"901212-1234567 관련 확인 이메일 양식입니다: ..."
        ▲
        │ (로컬 복원 / Hydration)
외부 모델 수신 원문
"SENSITIVE_DATA#7fa3c921 관련 확인 이메일 양식입니다: ..."
```

외부 클라우드 모델에는 카테고리나 원본 정보가 일체 전달되지 않으며, 오직 무작위 토큰(`SENSITIVE_DATA#<hash8>`)만 전달됩니다.

---

## 2. 마스킹 (Masking)

`masker.Masker`는 추출된 민감 스팬(`ExtractionRecord`)의 위치 오프셋(`start`, `end`)을 기준으로 원본 문자열을 플레이스홀더로 치환합니다.

```python
from masker import Masker

masker = Masker()
result = masker.mask(
    text="김민수(010-1234-5678) 고객의 상담 내역입니다.",
    records=[
        {"category": "PERSON_NAME", "span": "김민수", "start": 0, "end": 3},
        {"category": "PHONE_NUMBER", "span": "010-1234-5678", "start": 4, "end": 17},
    ],
)

print(result.masked_text)
# "SENSITIVE_DATA#a1b2c3d4(SENSITIVE_DATA#e5f6a7b8) 고객의 상담 내역입니다."
```

### 플레이스홀더 규칙
- **형식**: `SENSITIVE_DATA#<hash8>` 또는 `[CATEGORY#1]` 형태 지원.
- **결정론적 매핑**: 단일 요청 내에서 동일한 원본 텍스트가 여러 번 등장할 경우 동일한 플레이스홀더 토큰을 재사용하여 문맥 일관성을 보장합니다.
- **독립성**: 다음 요청 시에는 새로운 토큰이 발급되므로 요청 간 연관 추적이 불가능합니다.

---

## 3. 마스킹 계약 (`MaskingContract`)

마스킹 실행 시 해당 변환 정보를 담은 불변의 `MaskingContract`가 생성됩니다.

```python
result.contract.placeholder_map
# {
#     "SENSITIVE_DATA#a1b2c3d4": "김민수",
#     "SENSITIVE_DATA#e5f6a7b8": "010-1234-5678",
# }
```

- 계약 객체는 프로세스 메모리 내에서 안전하게 유지되며, 복원 단계의 단일 진실 공급원(Source of Truth)으로 사용됩니다.

---

## 4. 하이드레이션 (Hydration: 역치환 복원)

외부 모델이 생성한 응답 텍스트에 포함된 플레이스홀더를 `MaskingContract`에 등록된 원본 값으로 치환합니다.

```python
hydrated = masker.hydrate(
    llm_response="SENSITIVE_DATA#a1b2c3d4 고객님께 전송 완료했습니다.",
    contract=result.contract,
)

print(hydrated.hydrated_text)
# "김민수 고객님께 전송 완료했습니다."
```

### 안전 실패(Fail-Fast) 검증 규칙
- **미등록 토큰 거부**: 계약 맵에 등록되지 않은 임의의 플레이스홀더 패턴이 응답에 포함되어 있을 경우, 임의 추측 복원을 방지하기 위해 `HydrationError`를 발생시킵니다.
- **소실 처리**: 모델이 플레이스홀더를 임의로 삭제하거나 누락한 경우, 억지로 채워넣지 않고 모델 출력을 그대로 수용합니다.

---

## 5. 핵심 클래스 API

```python
from masker import (
    Masker,            # 마스킹 및 복원 엔진
    MaskingContract,   # 플레이스홀더 <-> 원문 매핑 계약 객체
    MaskingResult,     # mask() 실행 결과 (masked_text, contract)
    HydrationResult,   # hydrate() 실행 결과 (hydrated_text, unresolved_placeholders)
    HydrationError,    # 미해결 플레이스홀더 발생 시 예외
)
```
