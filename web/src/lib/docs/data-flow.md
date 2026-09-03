# 데이터 흐름

Privacy Router는 두 개의 서로 다른 데이터 계층을 다룹니다: 작업을 위한 정확한 스팬 증거와 결정을 위한 쿼리 단위 요약입니다.

## 흐름 개요

```text
User or agent prompt
    -> Extractor
    -> ExtractionResult
       - Sensitivity
       - ExtractionRecord[]
    -> Query aggregation
       - QueryDecisionSummary
    -> Judge
       - policy_action: allow | selective_mask | block
    -> Router
       - external_api | local_api
    -> Masker / Hydrator when needed
```

핵심 설계 규칙은 다음과 같습니다:

```text
결정은 집계로, 작업은 스팬 보존으로.
```

규범적 스키마, 수식, fail-closed 수용 검사는 [쿼리 집계 명세](/docs/query-aggregation)를 참고하세요.

## 데이터 형식

### 1. 입력 프롬프트

| 속성 | 설명 |
|---|---|
| 형식 | 자연어 텍스트, 다국어. |
| 출처 | AI 에이전트, 웹 UI, MCP 클라이언트, OpenAI 호환 클라이언트. |
| 저장 | 라우팅 중 프로세스 메모리. |
| 외부 전송 | 최종 정책 action이 `allow`일 때만 원문 허용. |

### 2. 스팬 증거: `ExtractionRecord`

`ExtractionRecord`는 탐지된 하나의 민감 스팬입니다. 마스킹과 하이드레이션의 진실 소스로 유지됩니다.

```python
ExtractionRecord(
    category="PERSONAL_IDENTIFIER",
    span="<personal-id>",
    confidence=0.98,
    start=18,
    end=31,
    detection_type="pattern",
    reasoning="The span directly identifies a person.",
    is_essential=False,
)
```

요구 사항:

- `span`은 정확한 민감 부분 문자열입니다.
- `category`는 `SCREAMING_SNAKE_CASE`로 동적 생성됩니다.
- `start`와 `end`는 0 기준 문자 오프셋입니다.
- `is_essential=false`는 마스킹해도 쿼리 의도가 유지됨을 뜻합니다.
- `is_essential=true`는 마스킹하면 쿼리 의도가 깨지므로 기본으로 외부 모델에 보내면 안 됨을 뜻합니다.

### 3. 쿼리 단위 요약: `QueryDecisionSummary`

요약은 파생된 결정 아티팩트이며 records를 대체하지 않습니다.

```python
QueryDecisionSummary(
    extraction_failed=False,
    extraction_failure_reason=None,
    is_sensitive=True,
    has_essential=False,
    is_maskable=True,
    record_count=2,
    essential_count=0,
    category_counts={"PERSONAL_IDENTIFIER": 1, "INTERNAL_PROJECT_NAME": 1},
    essential_categories=(),
    maskable_categories=("PERSONAL_IDENTIFIER", "INTERNAL_PROJECT_NAME"),
    mask_indices=(0, 1),
)
```

결정 변수:

```text
U(q) = 1 when extraction failed or output is invalid; otherwise 0.
S(q) = 1 when extraction succeeded and validated records exist; otherwise 0.
E(q) = 1 when any validated record is essential; otherwise 0.
M(q) = 1 when the query is sensitive and no record is essential; otherwise 0.
```

중요한 불변 조건:

```text
추출이 성공했을 때만 빈 records가 안전하다.
Extractor 실패는 '알 수 없음'이지 안전함이 아니다.
```

### 4. 정책 판단

Judge는 쿼리 단위 조건을 공식 정책 action에 매핑합니다.

| 조건 | 공식 `policy_action` | 의미 |
|---|---|---|
| `extraction_failed=true` | `block` | fail-closed. 로컬에서 처리하고 원문 프롬프트는 절대 외부로 보내지 않습니다. |
| `is_sensitive=false` | `allow` | 원문 프롬프트를 외부 모델에 보낼 수 있습니다. |
| `has_essential=true` | `block` | 로컬 처리를 사용하고 외부로 원문을 보내지 않습니다. |
| `is_maskable=true` | `selective_mask` | 외부 모델 호출 전에 비필수 records를 마스킹합니다. |

유효한 정책 action은 `allow`, `selective_mask`, `block`뿐이며 런타임은 그 외 action을 거부합니다.

### 5. 라우팅 결과

Router는 정책 action을 실행 경로에 매핑합니다.

| `policy_action` | 엔드포인트 | 마스킹 필요 | 외부 원문 프롬프트? |
|---|---|---|---|
| `allow` | `external_api` | 아니오 | 예 |
| `selective_mask` | `external_api` | 예 | 아니오 |
| `block` | `local_api` | 아니오 | 아니오 |

### 6. 마스킹 계약

Masker는 요약이 아니라 `ExtractionRecord[]`를 사용해 스팬을 결정적 플레이스홀더로 치환합니다.

```python
MaskingContract(
    placeholder_map={
        "PERSONAL_IDENTIFIER#7f3a9c2d": "<personal-id>",
        "INTERNAL_PROJECT_NAME#b81e2a10": "<internal-project-name>",
    },
    count=2,
)
```

플레이스홀더 규칙:

- 형식: `CATEGORY#hash8`.
- 대괄호 사용 금지.
- 해시는 원본 값에서 파생되어 같은 값은 일관되게 매핑됩니다.
- 하이드레이션의 진실 소스는 계약(contract)입니다.

### 7. 파이프라인 결과

마스킹된 외부 경로가 성공하면 하이드레이션된 모델 출력을 반환합니다.

```python
PipelineResult(
    sensitivity=Sensitivity(is_sensitive=True, rationale="Sensitive spans detected."),
    judgment=Judgment(
        policy_action="selective_mask",
        strategy="Mask non-essential records before external model call.",
        rationale="All detected spans are non-essential."
    ),
    route=RouteResult(endpoint="external_api", requires_masking=True),
    records=[ExtractionRecord(...)],
    mask_indices=[0, 1],
    response="Final hydrated response...",
)
```

## 개인정보 보호 경계

### 외부 LLM 경계

외부 LLM은 원문 민감 데이터에 대해 신뢰할 수 없는 존재입니다.

- `allow`: 외부 모델이 원문 프롬프트를 받습니다.
- `selective_mask`: 외부 모델이 마스킹된 텍스트만 받습니다.
- `block`: 외부 모델은 이 쿼리에서 아무것도 받지 않습니다.

### 호출자 측 경계

호출자 측 API/MCP 메타데이터에는 호출자가 원문 프롬프트를 제공했으므로 민감 스팬 세부 정보가 포함될 수 있지만, 여전히 민감한 운영 데이터로 취급해야 합니다.

- 암호화되고 명시적으로 필요한 경우가 아니라면 원문 스팬을 영구 로그에 남기지 마세요.
- 로그에는 개수, 카테고리, 정책 action, 플레이스홀더를 우선 사용하세요.
- 문서 예시에는 구체적 식별자 대신 `<personal-id>` 같은 플레이스홀더를 사용해야 합니다.

## 데이터 보존

| 데이터 | 저장 위치 | 보존 기간 |
|---|---|---|
| 원문 입력 프롬프트 | 프로세스 메모리 | 호출자가 관리하지 않으면 요청 수명 동안만. |
| 추출 records | 메모리/캐시, 영구 저장 시 민감 | 세션/캐시 수명. |
| QueryDecisionSummary | 스팬 제외 시 메모리/로그 안전 | 개수/action 형태로 로그 가능. |
| 플레이스홀더 맵 | 마스킹 계약 저장소 | 세션 TTL, 영구 저장 시 암호화. |
| 마스킹 records | 활성화 시 DB | 저장 시 암호화. |
| 정책 결정 | 사용 로그 | 원문 스팬 없이 영구 저장. |
| 프로바이더 API 키 | 서버 환경 변수 | 프로세스 수명, 절대 영구 저장·반환 금지. |

## 수용 요구 사항

데이터 흐름의 정확성은 구현 완료로 간주하기 전에 다음 검사를 요구합니다:

1. 추출 성공 + records 0개인 안전 쿼리는 `allow`로 라우팅된다.
2. 비필수 민감 쿼리는 `selective_mask`로 라우팅되고 외부 백엔드는 마스킹된 텍스트만 받는다.
3. 필수 record가 하나라도 있으면 `block`으로 라우팅되고 원문 외부 전송은 절대 금지된다.
4. Extractor 호출/파싱/스키마 실패는 fail-closed로 라우팅되고 절대 `allow`가 되지 않는다.
5. 하이드레이션은 쿼리 요약이 아니라 `MaskingContract.placeholder_map`을 사용한다.
6. 알 수 없는 정책 action은 정규화되지 않고 거부된다.
