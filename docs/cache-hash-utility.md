# 캐시 해시 유틸리티 명세

**상태:** 설계 초안 — 사용자 검토 필요

## 1. 목적

Long-horizon task에서는 이전 턴을 모두 받아야 프라이버시 맥락을 정확히 해석할 수 있습니다. 그러나 매 요청마다 모든 메시지를 Detector와 Masker로 다시 처리하면 비용과 지연이 커집니다.

이 유틸리티의 목적은 메시지 단위와 히스토리 prefix 단위의 안정적인 식별자를 계산하고, 나중에 상위 계층이 Detector·Masker 복원 계약을 재사용할 수 있도록 하는 것입니다.

이 패키지는 캐시 저장소나 데이터베이스를 구현하지 않습니다. SQLModel, Redis 등 저장 계층은 최종 사용자가 별도로 구성합니다.

## 2. 처리 범위

```text
SDK native history
  → JSON-safe Message[]
  → Message[] 검증·분해
  → 메시지별 message_hash
  → 메시지별 prefix history_hash
  → 상위 계층의 Detector/Masker 계약 조회
```

### 포함

- OpenAI Chat Completions 메시지 형식
- Anthropic Messages 메시지 형식
- LiteLLM OpenAI-compatible 메시지 형식
- LangChain `BaseMessage` 형식의 선택적 어댑터
- JSON 문자열·UTF-8 bytes·이미 파싱된 JSON 객체 처리
- 메시지 hash와 prefix history hash 계산
- 중복 키·바이너리·비JSON 타입의 fail-fast 검증
- 턴별 복원 계약을 암호화할 수 있는 low-level 인터페이스
- compaction checkpoint와 lineage 검증을 위한 데이터 구조

### 제외

- Detector 실행
- Masker 실행
- 캐시 저장·조회·삭제
- SQLModel 또는 Redis 구현
- 세션 생성·만료·권한 관리
- 평문 credential의 영속 저장

## 3. 포맷 경계

각 히스토리는 생성 시 하나의 native 포맷과 스키마 버전을 고정합니다. 한 히스토리 안에서 OpenAI 객체, Anthropic 객체, LangChain 객체를 자동으로 섞지 않습니다.

다만 하나의 포맷 안에서 여러 메시지 타입은 허용합니다. 예를 들어 OpenAI Chat Completions 히스토리는 `system`, `user`, `assistant`, `tool` 메시지를 함께 가질 수 있습니다.

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `format` | `Literal["openai-chat", "anthropic-messages", "litellm", "langchain"]` | 히스토리를 생성한 native 포맷 | `"openai-chat"` |
| `schema_version` | `str` | 해당 포맷의 유틸리티 해석 버전 | `"v1"` |
| `messages` | `list[JsonObject]` | JSON-safe 메시지 배열 | `[ {"role": "user", "content": "..."} ]` |
| `session_id` | `str \| None` | 선택적 캐시 namespace 입력 | `"session-123"` |

`session_id`는 메시지 hash와 history hash의 내용에 포함하지 않고 캐시 namespace로만 사용합니다. 따라서 첫 prefix에서 다음 불변식을 유지합니다.

```text
history_hash_1 == message_hash_1
```

## 4. JSON 검증과 정규화

정규화된 JSON의 canonicalization에는 RFC 8785를 사용합니다.

| 입력 | 처리 규칙 |
|---|---|
| 객체 키 순서 | RFC 8785 규칙으로 정렬 |
| 배열 순서 | 원래 순서 유지 |
| 메시지 순서 | 원래 순서 유지 |
| `metadata`, `additional_kwargs` | JSON 객체라면 재귀적으로 보존·정규화 |
| 중복 키 | JSON 파싱 단계에서 예외 발생 |
| `bytes`, 파일 객체, SDK 미지원 객체 | 예외 발생 |
| `NaN`, `Infinity` | 예외 발생 |
| 필드 누락과 `null` | 서로 다른 입력으로 취급 |
| 알 수 없는 JSON 필드 | 제거하지 않고 보존 |

키를 정렬하는 것은 필드의 순서만 바꾸며 데이터를 삭제하지 않습니다. 단, 표준 JSON 파서가 이미 중복 키를 덮어쓴 뒤에는 원래 입력을 복원할 수 없으므로 중복 키 검출을 파싱 단계에서 수행해야 합니다.

## 5. 해시 스키마

기본 알고리즘은 SHA-256이며 출력은 lowercase hexadecimal 문자열입니다.

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `algorithm` | `Literal["sha256"]` | 메시지·히스토리 hash 알고리즘 | `"sha256"` |
| `canonicalization` | `Literal["rfc8785"]` | hash 입력 직렬화 규격 | `"rfc8785"` |
| `message_hash` | `str` | 단일 정규 메시지의 hash | `"a1b2...9f"` |
| `history_hash` | `str` | 해당 메시지까지의 prefix hash | `"c3d4...8e"` |

### 메시지 hash

```text
message_hash_n = SHA256(RFC8785(message_n))
```

### Prefix history hash

```text
history_hash_1 = message_hash_1
history_hash_n = SHA256(
    RFC8785({
        "schema": "history-prefix-v1",
        "parent_history_hash": history_hash_(n-1),
        "message_hash": message_hash_n
    })
)
```

`history_hash_n`은 n번째 메시지까지의 맥락을 나타냅니다. 새 메시지가 추가되면 이전 prefix hash와 새 메시지 hash만으로 다음 hash를 계산할 수 있습니다.

## 6. 해시 결과

`hash_history()`는 전체 히스토리를 한 번 처리하고 모든 턴의 hash 쌍을 반환합니다.

### `MessageHash`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `message_index` | `int` | 히스토리 내 0-based 위치 | `2` |
| `message_hash` | `str` | 현재 메시지 hash | `"message-hash-3"` |
| `history_hash` | `str` | 현재 메시지까지의 prefix hash | `"history-hash-3"` |

### 공개 함수

| 함수 | 입력 | 반환 | 역할 |
|---|---|---|---|
| `parse_history()` | JSON 문자열, UTF-8 bytes, JSON 객체 | `HistorySpec` | 입력 파싱·중복 키·타입 검증 |
| `normalize_history()` | native SDK 형식 | `HistorySpec` | 포맷별 JSON-safe 구조 생성 |
| `hash_message()` | `JsonObject` | `str` | 메시지 하나의 hash 계산 |
| `hash_history()` | `HistorySpec` | `tuple[MessageHash, ...]` | 모든 메시지·prefix history hash 반환 |

유틸리티는 내부 상태, 캐시, 세션, 데이터베이스를 보유하지 않습니다.

## 7. 세션 namespace

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `scope` | `Literal["global", "session"]` | 캐시 범위 | `"session"` |
| `namespace_hash` | `str \| None` | session ID를 별도로 해싱한 namespace | `"7f8a...12"` |
| `session_id` | `str \| None` | 호출 시에만 사용되는 원문 식별자 | `"session-123"` |

최종 저장 계층은 다음 형태로 namespace를 적용할 수 있습니다.

```text
(global, history_hash)
(session_namespace_hash, history_hash)
```

메시지 hash는 세션과 무관하므로, 세션이 달라도 메시지 단위 Detector 결과를 재사용할 수 있습니다. 반면 history 기반 결과는 namespace까지 확인해야 합니다.

## 8. Detector·Masker 계약 캐시

캐시 대상은 LLM 응답이 아니라 Detector가 민감 스팬을 탐지하고 Masker가 생성한 복원 계약입니다.

### `RestorationEntry`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `key` | `str` | Masker placeholder | `"SENSITIVE_DATA#a1b2c3d4"` |
| `value` | `str` | 복원해야 하는 원문 span | `"<person-name>"` |

### `TurnContract`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `message_hash` | `str` | 계약이 생성된 메시지 식별자 | `"message-hash-2"` |
| `history_hash` | `str` | 계약이 생성된 prefix 식별자 | `"history-hash-2"` |
| `entries` | `list[RestorationEntry]` | placeholder와 원문 span 목록 | `[ {"key": "...", "value": "..."} ]` |
| `detector_fingerprint` | `str` | Detector 모델·프롬프트·규칙 식별자 | `"detector-v1"` |
| `masker_fingerprint` | `str` | Masker 계약 규칙 식별자 | `"masker-v1"` |

상위 저장 계층의 개념적 매핑은 다음과 같습니다.

```text
cache namespace + history_hash
  → encrypted TurnContract
```

## 9. 턴별 암호화

low-level 유틸리티는 계약 payload를 턴 단위로 암호화할 수 있어야 합니다. 키와 키 수명은 호출자가 관리하며, 유틸리티가 키를 저장하거나 session ID에서 자동 파생하지 않습니다.

### `EncryptedTurnContract`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `algorithm` | `Literal["aes-256-gcm", "chacha20-poly1305", "fernet"]` | 사용한 암호화 방식 | `"aes-256-gcm"` |
| `key_id` | `str` | 호출자 키 저장소의 키 식별자 | `"key-2026-01"` |
| `nonce` | `bytes` 또는 base64 `str` | 턴별 nonce | `"base64..."` |
| `ciphertext` | `bytes` 또는 base64 `str` | 암호화된 계약 | `"base64..."` |
| `associated_data` | `bytes` 또는 base64 `str` | hash·버전 인증 데이터 | `"base64..."` |

암호화 대상은 `RestorationEntry[]`입니다. `message_hash`, `history_hash`, 포맷, 버전, Detector fingerprint는 associated data로 묶어 계약과 함께 검증합니다.

DB에는 평문 계약을 저장하지 않으며, 실제 암호화 키 회전·보관·삭제는 상위 계층의 책임입니다.

### Masker 계약 재사용 주의

현재 Masker의 placeholder는 요청마다 새로 생성될 수 있으므로 `message_hash`가 같다고 기존 계약을 그대로 붙이면 안 됩니다.

| 상황 | 처리 |
|---|---|
| 기존 계약 조회 | 저장된 placeholder와 원문 span 매핑을 함께 복호화 |
| 같은 placeholder를 재사용 | 외부 모델에 보내는 텍스트가 저장된 계약의 key와 일치할 때만 허용 |
| 새 placeholder 생성 | 새 계약을 생성하고 저장된 계약과 섞지 않음 |
| 계약 key 불일치 | hydration 전에 cache miss 또는 fail-fast |

hash 유틸리티는 계약을 저장하지 않습니다. 상위 Masker 계층이 캐시된 계약을 사용할지, 새 계약을 만들지 결정해야 합니다.

## 10. 캐시 검증 정책 후보

### A. hash + version + fingerprint

가장 안전한 기본 후보입니다. 메시지와 맥락뿐 아니라 처리 규칙이 동일한지 검증합니다.

| 검증 항목 | 목적 |
|---|---|
| `message_hash` | 메시지 동일성 |
| `history_hash` | prefix 맥락 동일성 |
| `format` | native 메시지 규격 동일성 |
| `schema_version` | 유틸리티 규격 동일성 |
| `detector_fingerprint` | 모델·프롬프트·탐지 규칙 동일성 |
| `masker_fingerprint` | placeholder·계약 규칙 동일성 |
| `key_id` | 복호화 키 회전 상태 확인 |

### B. 두 hash만

구현은 단순하지만 Detector 모델·프롬프트·Masker 규칙이 바뀌어도 이전 계약을 재사용할 수 있습니다. low-level identity primitive로는 가능하지만 안전한 기본값으로는 부족합니다.

### C. 호출자 검증

유틸리티는 hash만 반환하고 상위 애플리케이션이 모든 fingerprint와 버전을 검증합니다. 가장 유연하지만 호출자가 검증을 빠뜨릴 수 있습니다.

## 11. Compaction과 Longer-horizon

Compaction으로 앞부분이 summary 메시지로 대체되면 실제 모델 입력이 달라집니다. 따라서 summary를 자동으로 원문과 의미적으로 동일하다고 간주하지 않습니다.

### `CompactionCheckpoint`

| 필드 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `format` | `str` | 히스토리 native 포맷 | `"openai-chat"` |
| `schema_version` | `str` | checkpoint 규격 버전 | `"v1"` |
| `covered_history_hash` | `str` | summary가 대체한 마지막 prefix | `"history-hash-20"` |
| `summary_message_hash` | `str` | 새 summary 메시지 hash | `"summary-hash-1"` |
| `source_message_count` | `int` | 대체된 원본 메시지 수 | `20` |
| `lineage_mode` | `Literal["new-context", "anchored"]` | compaction 처리 방식 | `"new-context"` |

기본 동작은 다음과 같습니다.

- 이전 메시지의 `message_hash` 기반 Detector/Masker 계약은 재사용 가능
- summary 이후의 context-dependent 판단은 새 `history_hash`로 검증
- `covered_history_hash`는 이전 계약의 출처와 포함 범위를 검증하는 checkpoint
- summary와 원문이 의미적으로 동등하다는 보장이 없으면 기존 history cache를 재사용하지 않음

Blockchain의 hash chain, checkpoint, Merkle proof는 포함 관계와 무결성 검증에 참고할 수 있습니다. 그러나 semantic equivalence를 보장하지는 않으므로, compaction 결과의 의미 판단을 hash만으로 생략해서는 안 됩니다.

## 12. 스파이크 검증 계획

최소 3턴의 동일한 일반 대화를 다음 native 형식으로 준비합니다.

| Fixture | 검증 대상 |
|---|---|
| OpenAI Chat Completions | role, content, tool call, metadata 경계 |
| Anthropic Messages | system 분리, content block, tool 결과 |
| LiteLLM | OpenAI-compatible request와 response `model_dump()` |
| LangChain Core | `BaseMessage` 변형, `messages_to_dict()` 왕복, `additional_kwargs` |

각 fixture에서 다음을 확인합니다.

1. JSON 문자열·bytes·객체 파싱
2. 메시지 단위 분해
3. 객체 키 순서 변경 시 동일 message hash
4. 메시지 순서·content-part 순서 변경 시 다른 history hash
5. 각 prefix의 `(message_hash, history_hash)` 생성
6. metadata·tag·tool call 보존 여부
7. 중복 키·바이너리·비정상 숫자의 fail-fast
8. Detector/Masker 계약 조회에 사용할 수 있는 hash 연결
9. compaction 전후 hash 단절과 checkpoint 검증
10. 정적 interactive hashing demo에서 중간 결과 확인

## Impact Surface

- Code: 신규 low-level hash/parser/encryption 유틸리티의 설계 기준. 아직 구현하지 않음.
- Skills: 변경 없음.
- Docs: 캐시 hash 유틸리티의 현재 설계 문서.
- Decisions: native 포맷별 독립 처리, RFC 8785, SHA-256, 선택적 session namespace, stateless 처리, per-turn 계약 암호화.
- Archive/versioning: 사용자 검토 전 설계 초안이므로 별도 버전 보관 없음.
- Verification: OpenAI·Anthropic·LiteLLM·LangChain 3턴 fixture 및 compaction 스파이크 계획을 명시함.
- No-update rationale: SQLModel과 DB 저장 구조는 low-level 목표에서 제외함.
