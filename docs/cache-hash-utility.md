# 메시지·히스토리 해시 유틸리티 명세

**상태:** 설계 초안 — 사용자 검토 필요

## 1. 이 유틸리티가 해결하는 문제

Long-horizon task에서는 이전 대화 전체를 받아야 Detector가 현재 메시지의 민감성을 올바르게 판단할 수 있습니다. 하지만 매 턴마다 이미 처리한 메시지를 다시 Detector와 Masker에 보내면 비용과 지연이 커집니다.

이 유틸리티는 다음 두 값을 계산합니다.

1. **메시지 hash**: 메시지 하나가 같은지 확인하는 값
2. **누적 히스토리 hash**: 현재 메시지까지의 이전 대화 순서가 같은지 확인하는 값

이 값으로 상위 계층은 이미 Detector가 처리한 메시지를 다시 처리하지 않고, 저장해 둔 탐지 결과의 참조를 찾을 수 있습니다.

이 유틸리티는 데이터베이스, 캐시 서버, Detector, Masker, 사용자 세션을 구현하지 않습니다.

## 2. 용어를 쉽게 정의하면

| 용어 | 의미 |
|---|---|
| 메시지 | `role`, `content` 등을 가진 JSON 객체 하나 |
| 히스토리 | 순서가 있는 메시지 배열 |
| 메시지 hash | 메시지 하나를 정해진 방법으로 해싱한 문자열 |
| 누적 히스토리 hash | 첫 메시지부터 현재 메시지까지의 순서를 반영한 문자열 |
| namespace | 서로 다른 사용자·세션의 캐시를 나누는 이름 |
| 복원 참조 | 원문을 직접 저장하지 않고, 상위 저장소에서 값을 찾기 위한 key와 hash |

## 3. 한 히스토리의 메시지 구조

한 히스토리는 생성할 때 `format`을 선택합니다. `format`은 OpenAI와 Anthropic 메시지를 한 배열에 섞지 않기 위한 구분값입니다.

그러나 같은 `format` 안에서 모든 메시지의 필드가 똑같을 필요는 없습니다. OpenAI Chat Completions에서도 `system`, `user`, `assistant`, `tool`은 서로 다른 선택 필드를 가집니다. A, B, C 메시지의 필드 구성이 일부 달라도 각 메시지가 선택한 format의 유효한 메시지라면 **모든 필드를 보존한 채** 해싱합니다.

정리하면:

- 키 순서가 다른 JSON 객체는 같은 메시지로 봅니다.
- 필드가 추가되거나 값이 달라지면 다른 메시지로 봅니다.
- 배열 순서와 메시지 순서는 보존합니다.
- 알 수 없는 JSON 필드는 삭제하지 않습니다.
- 서로 다른 프로토콜의 메시지를 자동으로 섞어 해석하지 않습니다.
- 유효하지 않은 구조, 중복 키, JSON으로 표현할 수 없는 값은 즉시 거부합니다.

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `format` | `Literal["openai-chat", "anthropic-messages", "litellm", "langchain"]` | 히스토리의 입력 규격 | `"openai-chat"` |
| `schema_version` | `str` | 이 유틸리티가 해석하는 규격 버전 | `"v1"` |
| `messages` | `list[JsonObject]` | 순서를 유지한 JSON 메시지 배열 | `[ {"role": "user", "content": "..."} ]` |
| `namespace` | `str` | 캐시를 나눌 이름. 없으면 `"default"` | `"customer-123"` |

## 4. JSON 읽기와 SDK 자료 변환

이름이 비슷하지만 두 함수의 책임은 다릅니다.

### `read_json_messages()`

**문자열 또는 bytes로 들어온 JSON을 읽는 함수**입니다. LLM의 의미를 해석하지 않고, JSON 문법과 자료 형태만 검사합니다.

```text
JSON 문자열 또는 UTF-8 bytes
  → JSON 값
  → 메시지 객체 배열인지 검사
```

| 항목 | 내용 |
|---|---|
| 입력 | `str` 또는 `bytes` 또는 JSON 값 |
| 출력 | `tuple[JsonObject, ...]` |
| 하는 일 | JSON 파싱, 최상위 배열 확인, 각 항목이 객체인지 확인 |
| 거부하는 것 | 잘못된 JSON, duplicate key, 바이너리, `NaN`, `Infinity`, 객체가 아닌 메시지 |
| 하지 않는 일 | 역할 추론, 요약, 필드 삭제, Detector 실행 |

예시:

```python
read_json_messages(
    '[{"role":"user","content":"안녕하세요"}]'
)
# ({"role": "user", "content": "안녕하세요"},)
```

### `convert_sdk_messages()`

**이미 만들어진 SDK 객체를 JSON-safe 객체로 바꾸는 함수**입니다.

| 입력 자료 | 변환 방법 |
|---|---|
| OpenAI 입력 메시지 | 런타임에서 이미 dict인 경우 그대로 검증 |
| Anthropic 입력 메시지 | 런타임에서 이미 dict인 경우 그대로 검증 |
| LiteLLM 응답 메시지 | `model_dump()` 또는 `to_dict()` 사용 |
| LangChain 메시지 | `messages_to_dict()` 사용 후 결과 검증 |
| 알 수 없는 객체 | 변환 방법이 없으면 거부 |

이 함수는 서로 다른 SDK의 메시지를 하나의 프로토콜로 바꾸지 않습니다. 선택한 `format`의 JSON 표현을 만들 뿐입니다. 이미 JSON 객체 배열로 들어온 값은 불필요하게 다시 바꾸지 않습니다.

## 5. 메시지 단위 hash

메시지 하나의 정규 JSON bytes를 SHA-256으로 해싱합니다.

```text
message_hash = SHA256(RFC8785(message))
```

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `algorithm` | `Literal["sha256"]` | 사용할 hash 알고리즘 | `"sha256"` |
| `canonicalization` | `Literal["rfc8785"]` | JSON을 bytes로 바꾸는 규격 | `"rfc8785"` |
| `message_hash` | `str` | lowercase hexadecimal hash | `"a1b2...9f"` |

다음 두 객체는 키 순서만 다르므로 같은 hash가 나옵니다.

```json
{"role":"user","content":"안녕","metadata":{"a":1,"b":2}}
{"metadata":{"b":2,"a":1},"content":"안녕","role":"user"}
```

반대로 다음은 다른 hash입니다.

```json
{"role":"user","content":"안녕"}
{"role":"user","content":"안녕","metadata":{"tag":"important"}}
```

## 6. 메시지별 누적 히스토리 hash

각 메시지는 자기 `message_hash`와 그 메시지까지의 `history_hash`를 함께 가집니다.

```text
message_1 → message_hash_1
          → history_hash_1 = message_hash_1

message_2 → message_hash_2
          → history_hash_2 = H(history_hash_1, message_hash_2)

message_3 → message_hash_3
          → history_hash_3 = H(history_hash_2, message_hash_3)
```

두 번째 메시지부터는 다음 JSON을 RFC 8785로 정규화한 뒤 SHA-256으로 해싱합니다.

```json
{
  "schema": "history-prefix-v1",
  "parent_history_hash": "history_hash_1",
  "message_hash": "message_hash_2"
}
```

### `HistoryItemHash`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `index` | `int` | 히스토리 안의 0부터 시작하는 위치 | `1` |
| `kind` | `Literal["message", "compaction"]` | 일반 메시지인지 compaction 항목인지 | `"message"` |
| `message_hash` | `str` | 현재 항목 하나의 hash | `"message-hash-2"` |
| `history_hash` | `str` | 현재 항목까지의 누적 hash | `"history-hash-2"` |
| `parent_history_hash` | `str \| None` | 직전 항목의 누적 hash | `"history-hash-1"` |

### `hash_history()`

| 항목 | 내용 |
|---|---|
| 입력 | `HistorySpec` |
| 출력 | `tuple[HistoryItemHash, ...]` |
| 동작 | 전체 입력을 한 번 순서대로 읽고 모든 메시지 hash와 누적 history hash를 생성 |
| 상태 | 내부 캐시·DB·세션을 만들지 않음 |

## 7. namespace와 session ID

OpenAI Chat, Anthropic Messages, LiteLLM의 일반 메시지 배열에는 모두가 공통으로 사용하는 session ID 필드가 없습니다. LangChain 계열에서는 `thread_id`가 checkpointer 설정에 들어갈 수 있지만, 메시지 자체의 공통 필드는 아닙니다.

따라서 session ID를 메시지에 억지로 추가하거나 history hash 안에 섞지 않습니다. 호출자가 별도의 `namespace` 또는 `session_id` 인자로 전달합니다.

| 상황 | namespace |
|---|---|
| session ID를 전달하지 않음 | `"default"` |
| session ID를 전달함 | 호출자가 정한 세션 namespace |
| 히스토리 JSON 안에 session 정보가 있음 | 명시적으로 adapter가 읽도록 설정한 경우에만 사용 |
| 세션 namespace 변경 | 같은 hash라도 다른 캐시 영역으로 처리 |

최종 저장 계층에서 사용할 주소는 다음과 같습니다.

```text
(namespace, history_hash_n)
```

`message_hash`와 `history_hash`는 메시지 내용과 순서만으로 계산합니다. namespace를 별도로 두므로 첫 번째 항목의 `history_hash_1 == message_hash_1`을 항상 유지할 수 있습니다.

namespace는 암호화 키가 아닙니다. 캐시 영역을 나누는 이름일 뿐입니다.

## 8. Detector 결과와 복원 참조

이 유틸리티가 재사용하려는 것은 LLM 응답이 아닙니다. Detector가 특정 메시지에서 발견한 민감 값과 Masker가 그 값을 다룰 수 있도록 만든 **참조 정보**입니다.

최신 방향에서는 원문 값을 이 유틸리티나 캐시에 저장하지 않습니다. 상위 애플리케이션이 별도의 안전한 key-value 저장소에서 값을 관리하고, 이 유틸리티는 그 값을 찾기 위한 key와 hash만 다룹니다.

### `DetectedValueReference`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `key` | `str` | 상위 key-value 저장소에서 사용할 논리적 key | `"user.phone"` |
| `value_hash` | `str` | Detector가 찾은 값의 SHA-256 hash | `"9a8b...21"` |
| `category` | `str` | Detector가 붙인 민감 정보 종류 | `"PHONE_NUMBER"` |
| `start` | `int` | 원문 안에서 시작하는 위치 | `10` |
| `end` | `int` | 원문 안에서 끝나는 위치 | `23` |
| `message_hash` | `str` | 이 참조가 나온 메시지 hash | `"message-hash-2"` |
| `detection_scope` | `Literal["message", "history"]` | 메시지만 보는지 이전 맥락도 보는지 | `"history"` |

`value_hash`는 원문 값을 복원하지 않습니다. 상위 계층은 필요할 때 `key`로 값을 조회하고, 조회한 값이 `value_hash`와 일치하는지 확인한 뒤 Masker에 전달합니다.

### 사례 1: 민감 값 하나

```text
입력 메시지: "홍길동에게 <phone-number>로 연락해줘"
Detector 결과: PHONE_NUMBER = <phone-number>
message_hash: message-A
history_hash: history-A
```

참조 정보:

```json
{
  "key": "user.phone",
  "value_hash": "hash(<phone-number>)",
  "category": "PHONE_NUMBER",
  "start": 6,
  "end": 20,
  "message_hash": "message-A",
  "detection_scope": "message"
}
```

캐시에는 `<phone-number>` 원문을 저장하지 않습니다. 상위 key-value 저장소에서 `user.phone`을 조회합니다.

### 사례 2: 한 메시지에 민감 값 두 개

```text
입력 메시지: "홍길동에게 <phone-number>로 연락하고 <email-address>로 안내해줘"
```

참조 목록:

```json
[
  {
    "key": "user.phone",
    "value_hash": "hash(<phone-number>)",
    "category": "PHONE_NUMBER",
    "start": 6,
    "end": 20,
    "message_hash": "message-B",
    "detection_scope": "message"
  },
  {
    "key": "user.email",
    "value_hash": "hash(<email-address>)",
    "category": "EMAIL_ADDRESS",
    "start": 27,
    "end": 42,
    "message_hash": "message-B",
    "detection_scope": "message"
  }
]
```

메시지 하나에 여러 참조가 있을 수 있으므로 `entries` 같은 불명확한 이름 대신 `references` 또는 `detected_values`처럼 실제 의미가 드러나는 이름을 사용합니다.

### 사례 3: 같은 메시지, 다른 이전 맥락

```text
메시지: "이 내용을 요약해줘"
message_hash: 동일

이전 대화 A: 공개 문서 설명
history_hash: history-A

이전 대화 B: 내부 프로젝트 설명
history_hash: history-B
```

메시지 hash는 같지만 Detector의 결과가 항상 같다고 보장할 수는 없습니다.

- `detection_scope="message"`인 형식·패턴 탐지 결과는 `message_hash`로 재사용할 수 있습니다.
- `detection_scope="history"`인 문맥 탐지 결과와 필수성 판정은 `history_hash`까지 일치할 때만 재사용합니다.

### 사례 4: 반복되는 동일 값

같은 메시지 또는 여러 메시지에 동일한 값이 반복되면 상위 key-value 저장소의 같은 key를 참조할 수 있습니다. 다만 placeholder 문자열의 생성 규칙과 재사용은 Masker 계층이 책임집니다. hash 유틸리티가 임의의 placeholder를 만들거나 계약을 저장하지 않습니다.

## 9. 암호화가 아닌 hash를 사용하는 이유

이 유틸리티의 목표는 저장된 값을 다시 복호화하는 것이 아닙니다.

| 구분 | hash | 암호화 |
|---|---|---|
| 결과 | 같은 값인지 확인하는 식별자 | 키로 다시 읽을 수 있는 암호문 |
| 원문 복원 | 불가능 | 가능 |
| 현재 용도 | 메시지·히스토리·탐지 값 식별 | 사용하지 않음 |
| 원문 값 보관 | 하지 않음 | 상위 key-value 저장소 책임 |

따라서 `EncryptedTurnContract`, `nonce`, `ciphertext`, `associated_data` 같은 암호화 계약은 이 low-level 유틸리티에 포함하지 않습니다. 상위 저장소가 별도의 보안 저장 방식을 선택할 수 있지만, 그것은 이 유틸리티의 계약이 아닙니다.

주의할 점도 있습니다. 전화번호나 이름처럼 후보가 적은 값에 일반 SHA-256만 적용하면 사전 대입으로 추측할 수 있습니다. hash가 외부에 노출될 수 있는 상위 시스템이라면 HMAC-SHA-256처럼 비밀 키를 사용하는 식별 방식을 별도로 검토해야 합니다. 이는 복호화가 아니라 hash 위조·추측을 어렵게 하는 보호 방식입니다.

## 10. Compaction 처리

외부 서비스에서 compaction을 표현하는 방법은 서로 다릅니다.

| 시스템 | compaction 표현 | 우리 유틸리티의 처리 |
|---|---|---|
| Anthropic Messages | assistant 응답의 `compaction` content block | 전체 block을 보존하고 `kind="compaction"`으로 표시 |
| OpenAI Responses | `type="compaction"`인 opaque output item | 내용을 해석하지 않고 원본 JSON을 그대로 hash |
| LangChain | summary middleware가 오래된 메시지를 summary로 교체 | 명시된 summary 항목을 새 메시지로 처리 |
| Semantic Kernel | history reducer가 절삭·요약 결과를 생성 | reducer가 반환한 항목을 입력으로 처리 |
| LiteLLM | 공통 compaction 항목 없음 | 호출자가 명시한 항목만 compaction으로 표시 |

### `CompactionItem`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `kind` | `Literal["compaction"]` | compaction 항목임을 나타냄 | `"compaction"` |
| `source` | `str` | 어느 SDK의 항목인지 | `"anthropic.content_block"` |
| `payload` | `JsonObject` | 원본 compaction JSON | `{"type":"compaction", ...}` |
| `covered_history_hash` | `str` | 대체된 마지막 누적 hash | `"history-hash-20"` |
| `message_hash` | `str` | compaction 항목 자체의 hash | `"summary-hash-1"` |
| `history_hash` | `str` | compaction 이후 새 누적 hash | `"history-hash-21"` |

compaction 항목을 텍스트 내용만 보고 추측하지 않습니다. provider 표식이나 호출자의 명시적 표시가 없으면 일반 `kind="message"`로 처리합니다.

Compaction 이후에는 다음을 구분합니다.

- 이전 메시지의 `message_hash`로 Detector 탐지 참조를 재사용할 수 있음
- compaction 이후의 문맥 판단은 새 `history_hash`로 확인함
- `covered_history_hash`는 summary가 어떤 이전 범위를 대신하는지 나타냄
- summary가 원문과 의미적으로 같다고 자동으로 가정하지 않음

## 11. 캐시 검증 선택지

### 선택지 A: hash와 처리 규칙을 함께 확인

| 확인값 | 의미 |
|---|---|
| `message_hash` | 메시지 내용이 같은지 |
| `history_hash` | 이전 대화 순서가 같은지 |
| `format` | 같은 SDK 메시지 규격인지 |
| `schema_version` | 같은 데이터 규격인지 |
| `detector_fingerprint` | 같은 모델·prompt·탐지 규칙인지 |
| `masker_fingerprint` | 같은 참조·placeholder 규칙인지 |

가장 안전하지만 저장할 정보가 많습니다.

### 선택지 B: 두 hash만 확인

`message_hash`와 `history_hash`만 비교합니다. 구현은 단순하지만 Detector 모델·prompt·Masker 규칙이 바뀐 뒤 이전 결과를 잘못 사용할 수 있습니다.

### 선택지 C: 호출자가 처리 규칙 확인

low-level 유틸리티는 hash만 제공하고, 상위 애플리케이션이 모델·prompt·규칙 버전을 확인합니다. 유연하지만 호출자 실수에 취약합니다.

현재 초안의 권장 방향은 **선택지 A를 상위 캐시 계층의 기본 검증으로 사용하고, hash 함수 자체는 규칙 fingerprint를 알지 않는 것**입니다. hash 유틸리티는 stateless primitive로 남기고, 상위 Detector/Masker 저장 계층이 처리 규칙을 함께 검증합니다.

## 12. 확인된 스파이크와 후속 검증

확인한 native 입력:

| 입력 | 확인 결과 |
|---|---|
| OpenAI SDK | 입력 MessageParam은 JSON dict 형태로 사용 가능 |
| Anthropic SDK | 입력 MessageParam은 dict, 응답은 `model_dump()` 가능 |
| LiteLLM | OpenAI-compatible dict와 `Message.model_dump()` 확인 |
| LangChain Core | `messages_to_dict()`와 `messages_from_dict()` 왕복 확인 |

후속 스파이크에서 확인할 것:

1. 각 포맷별 3턴 fixture에서 JSON 읽기
2. system, tool call, tool result, content part 보존
3. 객체 키 순서만 바꾼 경우 같은 message hash
4. 메시지 순서를 바꾼 경우 이후 history hash 변경
5. duplicate key·바이너리·비정상 숫자의 fail-fast
6. 메시지별 Detector 참조와 `message_hash` 연결
7. 동일 메시지·다른 맥락에서 `message_hash`와 `history_hash` 분리
8. provider-native compaction 항목의 `kind` 판별
9. compaction 전후 `covered_history_hash` 검증
10. 정적 interactive hash demo에서 각 중간 결과 표시

## Impact Surface

- Code: 아직 구현하지 않은 stateless JSON 검증·메시지 hash·누적 history hash 유틸리티의 기준.
- Skills: 변경 없음.
- Docs: 이전의 모호한 `TurnContract`·암호화 계약 설명을 제거하고, hash와 Detector 복원 참조를 분리해 전면 재작성.
- Decisions: native 포맷별 독립 처리, JSON 필드 보존, RFC 8785, SHA-256, 선택적 namespace, prefix hash, 원문 미저장.
- Archive/versioning: 현재 문서가 설계 초안이므로 별도 버전 파일을 만들지 않음.
- Verification: OpenAI·Anthropic·LiteLLM·LangChain 실제 메시지 변환 및 compaction 동작을 문서화함.
- No-update rationale: SQLModel·Redis·암호화 저장소와 실제 Detector/Masker 연계 구현은 사용자 검토 이후 별도 구현 계획에서 다룸.
