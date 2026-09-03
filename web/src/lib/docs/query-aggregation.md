# 쿼리 집계 명세

Status: **spec-first 대상**. 본 명세는 구현 변경 전에 요구되는 동작을 정의한다. 현재 코드는 여전히 `Judge.classify()` 내부에 이 집계의 일부를 암묵적으로 수행할 수 있다.

## 목적

Privacy Router는 두 가지 관점을 반드시 분리해야 한다:

1. **span 증거** — 마스킹, 하이드레이션, 감사에 필요한 정확한 민감 span.
2. **의사결정 요약** — Judge와 Router에서 사용하는 query 수준 변수.

안내 원칙:

```text
Aggregate for decision. Preserve spans for action.
```

Korean summary: 이 명세는 span-level 증거와 query-level 의사결정을 분리한다. 집계값은 라우팅 판단에만 쓰고, 실제 마스킹/하이드레이션은 원본 `ExtractionRecord`와 `MaskingContract`를 source of truth로 유지해야 한다.

## 파이프라인 위치

대상 파이프라인:

```text
Input query q
  -> Extractor
  -> Span evidence R(q): ExtractionRecord[]
  -> QueryAggregator
  -> QueryDecisionSummary z(q)
  -> Judge
  -> policy_action
  -> Router
  -> allow | selective_mask | block
```

`QueryAggregator`는 `ExtractionRecord[]`를 대체해서는 안 된다. 기록과 추출 상태로부터 간결한 요약을 유도하는 반면, Masker와 Hydrator는 여전히 원본 기록과 마스킹 계약을 사용해야 한다.

## 레이어 1: span 증거

하나의 query `q`에 대해 Extractor는 기록의 집합을 생성한다:

```text
R(q) = {r_1, ..., r_n}
```

각 기록은:

```text
r_i = (span, category, start, end, confidence, is_essential)
```

| 기호 | 필드 | 의미 |
|---|---|---|
| s_i | `span` | 입력 텍스트에서의 정확한 민감 부분 문자열. |
| c_i | `category` | 동적 `SCREAMING_SNAKE_CASE` 카테고리. |
| a_i, b_i | `start`, `end` | 문자 오프셋, 0 기준, end-exclusive. |
| p_i | `confidence` | `[0, 1]` 범위의 탐지 신뢰도. |
| e_i | `is_essential` | span을 마스킹하면 query 의도가 깨질 때 `true`. |

span 규칙:

- `span`은 민감 엔티티 자체만 포함해야 한다. 조사, 부사, 동사 파생을 제외해야 한다.
- `category`는 동적으로 `SCREAMING_SNAKE_CASE`로 생성되어야 한다. 시스템은 폐쇄된 고정 카테고리 목록에 의존해서는 안 된다.
- `is_essential=true`는 원본 값이 사용자 요청의 대상이며 단순 배경 자료가 아니라는 의미이다.
- 마스킹 가능한 span에 대한 플레이스홀더 형식은 `CATEGORY#hash8`이며, 괄호 없이 표현한다.

마스킹 예시:

```json
{
  "category": "PERSONAL_IDENTIFIER",
  "span": "<personal-id>",
  "confidence": 0.98,
  "start": 18,
  "end": 31,
  "detection_type": "pattern",
  "reasoning": "The span directly identifies a person.",
  "is_essential": false
}
```

## 레이어 2: QueryDecisionSummary

`QueryDecisionSummary`는 필요한 query 수준 집계 아티팩트이다.

대상 스키마:

```python
@dataclass(frozen=True)
class QueryDecisionSummary:
    extraction_failed: bool
    extraction_failure_reason: str | None
    is_sensitive: bool
    has_essential: bool
    is_maskable: bool
    record_count: int
    essential_count: int
    category_counts: dict[str, int]
    essential_categories: tuple[str, ...]
    maskable_categories: tuple[str, ...]
    mask_indices: tuple[int, ...]
```

필드 요구 사항:

| 필드 | 요구 사항 |
|---|---|
| `extraction_failed` | 추출기 호출, 구조화된 파싱, 스키마 검증, 오프셋 검증, 또는 신뢰도 게이트 실패 시 `true`여야 한다. |
| `extraction_failure_reason` | `extraction_failed=true`일 때 짧은 기계 판독 가능 이유를 포함해야 한다. |
| `is_sensitive` | 추출이 성공하고 최소 하나의 검증된 기록이 존재할 때만 `true`여야 한다. |
| `has_essential` | 검증된 기록 중 하나라도 `is_essential=true`이면 `true`여야 한다. |
| `is_maskable` | 추출이 성공하고 query가 민감하며 기록 중 essential이 없을 때만 `true`여야 한다. |
| `record_count` | 검증된 기록에 대해 `len(R(q))`와 같아야 한다. |
| `essential_count` | `is_essential=true`인 기록의 수와 같아야 한다. |
| `category_counts` | 검증된 기록에서 카테고리를 세어야 한다. |
| `essential_categories` | 기록이 essential인 카테고리를 포함해야 한다. |
| `maskable_categories` | 기록이 non-essential인 카테고리를 포함해야 한다. |
| `mask_indices` | `selective_mask` 경로에서 마스킹 가능한 기록의 인덱스를 포함해야 한다. |

예시:

```json
{
  "extraction_failed": false,
  "extraction_failure_reason": null,
  "is_sensitive": true,
  "has_essential": false,
  "is_maskable": true,
  "record_count": 2,
  "essential_count": 0,
  "category_counts": {
    "PERSONAL_IDENTIFIER": 1,
    "INTERNAL_PROJECT_NAME": 1
  },
  "essential_categories": [],
  "maskable_categories": ["PERSONAL_IDENTIFIER", "INTERNAL_PROJECT_NAME"],
  "mask_indices": [0, 1]
}
```

## 의사결정 변수

불확정성 정의:

```text
U(q) = 1 when extraction failed or output is invalid; otherwise 0.
```

민감도는 추출이 성공한 후에만 안전하게 계산할 수 있다:

```text
S(q) = 1 when extraction succeeded and validated records exist; otherwise 0.
```

필수성:

```text
E(q) = 1 when any validated record is essential; otherwise 0.
```

마스킹 가능성:

```text
M(q) = 1 when the query is sensitive and no record is essential; otherwise 0.
```

카테고리 프로파일:

```text
N_k(q) = count of records whose category is k.
```

필수 카테고리 집합:

```text
K_ess(q) = categories that contain essential records.
```

마스킹 가능 카테고리 집합:

```text
K_mask(q) = categories that contain non-essential records.
```

마스킹 인덱스 집합:

```text
I_mask(q) = indexes of records eligible for masking.
```

중요한 불변:

```text
추출이 성공했을 때만 빈 records가 안전하다.
추출 실패는 '알 수 없음'이지 '비민감'이 아니다.
```

## 라우팅 정책

정규 정책 동작은 다음과 같다:

- `allow`
- `selective_mask`
- `block`

정규 집합 밖의 어떤 동작도 유효하지 않으며 반드시 거부되어야 한다.

규범 정책:

```text
Policy:
- if extraction failed: block; process locally and never send external raw
- else if not sensitive: allow
- else if any record is essential: block
- else: selective_mask
```

작업 테이블:

| 조건 | 정규 `policy_action` | 라우터 엔드포인트 | 외부 raw 허용? |
|---|---|---|---|
| `extraction_failed=true` | `block` | `local_api` | **아니오** |
| `is_sensitive=false` | `allow` | `external_api` | **예** |
| `has_essential=true` | `block` | `local_api` | **아니오** |
| `is_maskable=true` | `selective_mask` | `external_api` with masking | **raw prompt 없음** |

프로젝트 기본값은 보수적이다: 어떤 기록이든 essential이면 전체 query는 로컬로 처리되어야 하고 외부 모델에 전송되어서는 안 된다.

## 실패-폐쇄 불변

구현은 다음 불변을 만족해야 한다:

1. `extraction_failed=true`는 외부 raw 전송으로 해결되어서는 안 된다.
2. `has_essential=true`는 호출자가 강제 생성을 요청하더라도 외부 전송으로 해결되어서는 안 된다.
3. `policy_action=allow`는 `extraction_failed=false` 그리고 `record_count=0`일 때만 유효하다.
4. `policy_action=selective_mask`는 `record_count>0`, `has_essential=false`, 그리고 비어 있지 않은 `mask_indices` 목록을 요구한다.
5. `policy_action=block`는 외부 모델이 이 query로부터 입력을 받지 않는다는 의미이다.
6. `QueryDecisionSummary`는 `ExtractionResult`로부터 유도 가능해야 하지만, 유일한 유지 아티팩트여서는 안 된다.

Korean summary: extractor 실패나 parse 실패는 "민감 정보 없음"이 아니다. 반드시 unknown으로 처리하고 외부 raw 전송을 막아야 한다. 또한 essential span이 하나라도 있으면 강제 generate 모드에서도 외부 전송으로 downgrade하면 안 된다.

## 프라이버시 경계

### 외부 모델 경계

외부 LLM 백엔드는 민감한 원본 입력에 대해 신뢰할 수 없다.

- `allow`에만 원본 텍스트를 받을 수 있다.
- `selective_mask`에만 마스킹된 텍스트를 받을 수 있다.
- `block`, 추출기 실패, essential 기록에는 원본 텍스트를 받을 수 없다.

### callers 쪽 경계

호출자는 이미 원본 prompt를 제공했지만, 응답 메타데이터는 여전히 민감 데이터를 로그나 제3자 시스템에 유출할 수 있다.

- `span`, `placeholder_map`, 또는 `extraction_records`를 포함하는 API 및 MCP 응답 메타데이터는 민감하게 처리되어야 한다.
- 지속적 로그는 암호화 저장이 명시적으로 요구되지 않는 한 카운트, 카테고리, 동작, 마스킹 플레이스홀더만 저장해야 한다.
- 문서 예시는 `<personal-id>`와 `PERSONAL_IDENTIFIER#7f3a9c2d`와 같은 플레이스홀더를 사용해야 하며, 실제 식별자를 사용해서는 안 된다.

## 마스킹 및 하이드레이션 계약

`QueryDecisionSummary`는 마스킹이 필요한지를 결정한다. 마스킹 자체는 수행하지 않는다.

마스킹 경로:

```text
ExtractionRecord[] + input text
  -> Masker
  -> masked text + MaskingContract
  -> external LLM
  -> Hydrator
  -> caller-facing response
```

요구 사항:

- Masker는 `QueryDecisionSummary`만이 아니라 원본 `ExtractionRecord[]`를 사용해야 한다.
- Hydrator는 복구의 source of truth로 `MaskingContract.placeholder_map`를 사용해야 한다.
- 계약은 `CATEGORY#hash8` 플레이스홀더를 원본 값에 매핑해야 한다.
- 하이드레이션으로 플레이스홀더를 해결할 수 없으면 시스템은 조용히 버리거나 내용을 창조하는 대신 명시적으로 실패해야 한다.

마스킹 예시:

```json
{
  "masked_text": "Summarize the incident for PERSONAL_IDENTIFIER#7f3a9c2d.",
  "placeholder_map": {
    "PERSONAL_IDENTIFIER#7f3a9c2d": "<personal-id>"
  }
}
```

## 수용 테스트

본 명세를 구현하기 전에, LLM 독립적으로 의사결정 레이어를 다루는 테스트를 작성해야 한다.

| 사례 | 입력 상태 | 예상 요약 | 예상 라우트 |
|---|---|---|---|
| 안전 query | 추출 정상, 기록 0개 | `is_sensitive=false` | `allow -> external_api` |
| 비필수 민감 query | 추출 정상, 모든 기록 `is_essential=false` | `is_maskable=true` | `selective_mask -> external_api`, 마스킹만 |
| 필수 민감 query | 추출 정상, 최소 하나의 `is_essential=true` | `has_essential=true` | `block -> local_api`, 외부 raw 없음 |
| 혼합 필수/비필수 기록 | 추출 정상, 최소 하나의 essential | `has_essential=true` | `block -> local_api` (기본) |
| 추출기 호출 실패 | 구조화된 결과 전 예외 | `extraction_failed=true` | 외부 raw 없음 |
| 구조화된 파싱 실패 | 잘못된 JSON 또는 스키마 오류 | `extraction_failed=true` | 외부 raw 없음 |
| 잘못된 오프셋 | 기록 span이 오프셋과 일치하지 않음 | `extraction_failed=true` 또는 명시적 이유로 기록 거부 | 실패-열림 허용 없음 |
| essential 기록과 함께 강제 생성 | `action="generate"`, `has_essential=true` | `has_essential=true` | 외부 raw 없음 |
| 잘못된 정책 동작 | 알 수 없는 동작이 라우터 경계에 도달 | `ValueError`로 거부 | 대체 라우트 없음 |

회귀 테스트 이름 권장:

```text
test_extraction_failure_never_routes_external_raw
```

## 메트릭

평가를 span 수준과 query 수준 메트릭으로 분리한다.

span 수준:

- 정확한 span F1
- 카테고리 정확도
- `is_essential` 정확도
- 오프셋 유효성 비율

query 수준:

- 민감도 정밀도/재현율
- `has_essential` 정확도
- 마스킹 가능성 정확도
- policy action 정확도
- 외부 raw 유출률
- 추출기 실패 실패-폐쇄율

단일 집계 점수는 0이 아닌 외부 raw 유출률을 숨길 수 없다.

## 구현 순서

명세 주도 순서:

1. `QueryDecisionSummary` 스키마와 순수 집계 함수를 추가한다.
2. 위 모든 수용 사례에 대한 mock 기반 단위 테스트를 추가한다.
3. Judge가 요약을 소비하거나 요약 생성을 명시적으로 위임하도록 변경한다.
4. 라우터 해결 전에 추출 실패 시 실패-폐쇄 동작을 강제한다.
5. 라우터 경계에서 알 수 없는 정책 동작을 거부한다.
6. 테스트가 통과한 후 API/MCP 메타데이터를 업데이트한다.
7. 코드 동작이 결정적인 후에 실제 LLM 평가 스위트를 별도로 실행한다.

실패-폐쇄 테스트가 통과하고 문서 예시가 정규 `allow` / `selective_mask` / `block` 레이블을 사용할 때만 구현이 완료된 것으로 본다.
