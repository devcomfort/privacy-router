# Masking & Hydration

민감한 원문을 요청 범위의 불투명 플레이스홀더로 치환한 뒤 외부 모델에 보내고, 응답에서 등록된 플레이스홀더만 로컬에서 복원하는 과정입니다.

## 실제 데이터 흐름

```
원문
"주민번호 <personal-id>로 양식을 작성해줘"
        │  로컬 추출·정책 판단
        ▼
외부 모델에 전송되는 값
"주민번호 SENSITIVE_DATA#7fa3c921로 양식을 작성해줘"
        │  외부 모델 응답
        ▼
로컬 복원
"<personal-id>로 작성한 양식입니다"
```

민감 정보의 category와 원문↔플레이스홀더 매핑은 로컬에 남습니다. 외부 모델에는 고정 라벨 `SENSITIVE_DATA`와 무작위 토큰만 보입니다.

## 마스킹

`agents/masker/masker.py`의 `Masker`가 추출 레코드의 `start`, `end`, `span`을 이용해 원문을 치환합니다.

### 플레이스홀더 형식

```text
SENSITIVE_DATA#<random8>
```

- `random8`은 `secrets.token_hex(4)`로 만든 8자리 16진수입니다.
- 토큰은 원문이나 category의 해시가 아닙니다.
- 한 요청에서 같은 원문 span이 여러 메시지·도구 필드에 반복되면 하나의 공유 레지스트리로 같은 토큰을 재사용합니다.
- 다음 요청에서는 새 토큰을 만들므로 요청 간 값을 연결하기 어렵습니다.
- 32비트 토큰 자체는 접근 제어 수단이 아닙니다. 실제 경계는 로컬 계약, REST 소유자 검사, 세션 ID입니다.

### 무엇을 마스킹하는가

OpenAI 호환 채팅 경로는 텍스트를 담을 수 있는 다음 위치를 원래 JSON 구조를 유지한 채 복사하여 마스킹합니다.

- `messages`의 문자열 content와 다중 content part
- tool call arguments와 tool output
- `tools` 정의 및 `tool_choice`
- Responses API의 `input`과 `instructions`

추출 레코드가 없으면 원문을 바꾸지 않습니다. 하나라도 `is_essential=true`이면 정책은 `block`을 선택하고 외부 모델로 보내지 않습니다. 모든 탐지 레코드가 비본질적일 때만 `selective_mask` 후 외부 모델을 사용합니다.

### MaskingContract

마스킹 호출은 요청 범위의 불변 계약을 만듭니다.

```python
result.contract.placeholder_map
# {
#     "SENSITIVE_DATA#7fa3c921": "<personal-id>",
#     "SENSITIVE_DATA#c04e81ab": "<phone-number>",
# }
```

이 매핑은 복원을 위해 프로세스 메모리에서는 평문을 보유합니다. 세션을 저장하면 원문 span은 DB의 `masking_records.span`에 Fernet 암호문으로 저장됩니다.

## 외부 모델 경계

외부 요청에는 마스킹된 메시지·도구 데이터만 전달됩니다. 다음 값은 공급자 요청에 포함되지 않습니다.

- 원문 span
- 추출 category, confidence, `is_essential`
- `MaskingContract`
- 암호화 키와 DB 세션 ID

단, 추출기가 민감한 span을 놓치면 그 값은 마스킹되지 않습니다. 마스킹은 탐지 결과보다 강할 수 없습니다.

## 하이드레이션

`Masker.hydrate()`는 응답을 먼저 검증한 뒤 계약에 등록된 값만 정확히 치환합니다.

```python
from agents.masker import Masker

hydrated = Masker().hydrate(
    "번호 SENSITIVE_DATA#7fa3c921은 유효합니다",
    result.contract,
)
hydrated.hydrated_text
# "번호 <personal-id>은 유효합니다"
```

- `SENSITIVE_DATA#token`과 `[SENSITIVE_DATA#token]`을 모두 인식합니다.
- 계약에 없는 플레이스홀더가 나타나면 `HydrationError`로 실패하며 추측해서 복원하지 않습니다.
- 모델이 플레이스홀더를 삭제하면 복원할 대상이 없어 그대로 끝납니다.
- 모델이 토큰을 변형하면 기본 동작은 실패입니다. 선택형 repair 경로를 켠 경우에도 등록된 토큰으로만 교정할 수 있습니다.

### 스트리밍과 도구 호출

`server/api/streaming.py`의 `StreamingHydrator`는 청크 끝의 불완전한 플레이스홀더를 버퍼링합니다. 완전한 토큰만 계약과 대조한 뒤 복원하므로 토큰 일부가 먼저 사용자에게 노출되지 않습니다.

도구 호출 arguments는 엄격한 JSON으로 파싱하며 중복 key, `NaN`, 무한대를 거부합니다. 입력에서 유래한 플레이스홀더는 기본적으로 등록 여부만 검증하고 유지합니다. 로컬 모델이 새로 만든 arguments는 JSON 구조를 보존하는 정규화본과 디코딩한 문자열 값의 경로별 검사 문서를 만든 뒤, 클라이언트에 보내기 직전에 검사합니다. 문자열 값에서 탐지한 민감 원문은 `SENSITIVE_DATA#<8자리 16진수>`로 치환합니다. 요청에 도구가 없어도 모델이 일반 출력 뒤에 예기치 않은 tool call을 만들 수 있으므로, 로컬 스트리밍 응답은 완료 시점까지 일반 출력과 arguments를 모두 보류하고 모든 도구 호출의 검사를 마친 뒤 내보냅니다. 민감 값이 객체 key나 숫자 위치에 있어 구조를 보존하며 치환할 수 없거나 파싱·검사·마스킹이 실패하면 응답을 차단합니다. `privacy_router.allow_sensitive_tool_arguments: true`를 JSON boolean으로 명시해도 검사는 생략하지 않습니다. 이 설정은 입력 플레이스홀더에서 복원한 값과 로컬 모델이 새로 생성한 민감 값 모두를 평문으로 전달합니다. 플래그는 요청 단위이고 도구별 허용 목록이 없으므로 해당 응답의 모든 function call에 적용됩니다.

## ContractStore

`agents/masker/contract_store.py`가 복원 계약을 SQLModel DB에 저장합니다.

| 테이블 | 주요 컬럼 | 저장 내용 |
|---|---|---|
| `masking_sessions` | id, chat_id, owner_id, policy_action, is_active, expires_at | 계약의 수명과 REST 소유자 |
| `masking_records` | session_id, uid, category, placeholder, value_hash, span, confidence, is_essential | 무작위 플레이스홀더, HMAC 지문, Fernet 암호문 |

저장 순서:

1. `create_session()`이 UUID 세션 ID와 기본 24시간 `expires_at`을 만듭니다.
2. `save_records()`가 플레이스홀더 토큰, 로컬 category, HMAC-SHA256 `value_hash`, Fernet 암호화 `span`을 저장합니다.
3. `load_contract()`가 활성 상태, 만료 시각, 선택적 `owner_id`를 확인한 뒤 span을 복호화해 계약을 재구성합니다.
4. 만료 또는 비활성 세션은 즉시 조회할 수 없습니다. 시작 시와 매시간 실행되는 보존 작업이 만료된 세션과 레코드를 물리적으로 삭제합니다.

`value_hash`는 원문 SHA-256이 아니라 마스터 키를 사용하는 도메인 분리 HMAC입니다. DB만 탈취한 공격자의 사전 대입을 어렵게 하지만, 마스터 키까지 유출되면 보호되지 않습니다.

## REST API

| 메서드 | 경로 | 동작 |
|---|---|---|
| `GET` | `/api/v1/masking/{session_id}` | 소유자 확인 후 category·placeholder 등 메타데이터 반환; 원문은 반환하지 않음 |
| `POST` | `/api/v1/masking/{session_id}/hydrate` | 소유자 확인 후 요청 content를 저장된 계약으로 복원 |

```bash
curl -X POST http://localhost:8787/api/v1/masking/{session_id}/hydrate \
  -H "Authorization: Bearer $PRIVACY_ROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content":"번호 SENSITIVE_DATA#7fa3c921은 유효합니다"}'
```

REST 경로는 인증된 provider ID를 계약의 `owner_id`와 비교합니다. 같은 provider에 속한 여러 API 키는 동일한 소유자 범위를 공유합니다.

## MCP

로컬 MCP `process` 도구는 `action="hydrate"`와 `chat_id=<masking_session_id>`로 계약을 다시 불러옵니다. MCP 경로는 REST provider 소유자 검사를 사용하지 않으므로 신뢰된 로컬 프로세스 경계 안에서만 사용해야 합니다.

## 암호화 키

- 알고리즘: Fernet authenticated encryption (AES-128-CBC + HMAC-SHA256)
- 키 조회 순서: `PRIVACY_ROUTER_MASTER_KEY` → 기존 `MASKING_ENCRYPTION_KEY` → 개발용 임시 키
- 프로덕션: DB 밖의 안정적인 비밀 저장소에서 키를 주입해야 합니다.
- 개발용 임시 키: 프로세스 재시작 후 기존 암호문을 복호화할 수 없습니다.

## 보존과 한계

- 24시간 TTL이 지나면 계약 접근은 즉시 거부됩니다.
- 시작 시 정리와 시간별 보존 작업이 만료된 `masking_sessions` 및 관련 `masking_records`를 물리적으로 삭제합니다.
- 프로세스 메모리에는 활성 요청의 평문 계약이 존재합니다.
- 호스트 프로세스나 마스터 키가 침해되면 DB 암호화는 원문을 보호하지 못합니다.
- 모델이 플레이스홀더를 누락·중복하면 결과 의미가 달라질 수 있습니다.

## Related Documents

- [Detection](/docs/detection) — how sensitive data is detected before masking
- [Architecture](/docs/architecture) — pipeline and trust boundaries
- [Security](/docs/security) — threat model, trust boundaries, and residual risk
