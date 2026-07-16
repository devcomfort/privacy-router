# Privacy Router — 데이터베이스 구조

## 개요

Privacy Router는 SQLModel로 같은 스키마를 SQLite와 PostgreSQL에 사용합니다. 기본 개발 저장소는 `privacy_router.db`이고, `DATABASE_URL`로 PostgreSQL을 선택할 수 있습니다.

현재 스키마는 11개 테이블입니다.

| 영역 | 테이블 |
|---|---|
| 런타임 설정 | `provider`, `models`, `workspaces`, `profiles`, `profile_agents` |
| 인증 | `api_keys` |
| 메타데이터 | `usage_logs` |
| 암호화된 임시 데이터 | `responses`, `extraction_cache`, `masking_sessions`, `masking_records` |

## 관계

| 상위 테이블 | 하위 테이블 | 관계 |
|---|---|---|
| `provider` | `models` | 1:N — `models.provider_id` |
| `workspaces` | `profiles` | 1:N — `profiles.workspace_id` |
| `profiles` | `profile_agents` | 1:N — `profile_agents.profile_id` |
| `models` | `profile_agents` | 1:N — `profile_agents.model_id`가 `models.model_id`를 참조 |
| `masking_sessions` | `masking_records` | 1:N — `masking_records.session_id` |

`owner_id`는 인증된 provider 범위를 기록하지만 별도 외래 키로 선언하지 않습니다. `chat_id`는 대화 단위 캐시 키이며 마스킹 세션과 추출 캐시 사이의 외래 키가 아닙니다.

## 런타임 설정

### `provider`

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str, PK | provider 식별자 |
| `name` | str | 표시 이름 |
| `api_base` | str? | API 기본 URL |
| `api_key_env` | str? | 환경변수 폴백 이름 |
| `encrypted_api_key` | str? | Fernet 암호문 |
| `key_fingerprint` | str? | API 키 조각을 포함하지 않는 16자리 도메인 분리 HMAC 지문 |
| `created_at`, `updated_at` | datetime | 생성·수정 시각 |

### `models`

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str, PK | 내부 UUID |
| `model_id` | str, unique | API에서 사용하는 모델 식별자 |
| `provider_id` | str | provider 참조 |
| `display_name`, `params` | str? | 표시용 메타데이터 |
| `location`, `tier` | str | 실행 위치와 크기 분류 |
| `cost_per_1m_tokens` | float | 토큰 비용 메타데이터 |
| `api_base_override` | str? | 모델별 API URL |
| `is_active` | bool | 사용 가능 여부 |
| `created_at` | datetime | 생성 시각 |

### `workspaces`, `profiles`, `profile_agents`

| 테이블 | 핵심 필드 | 역할 |
|---|---|---|
| `workspaces` | `id`, `name`, `active_profile`, timestamps | 활성 프로필 선택 |
| `profiles` | `id`, `workspace_id`, `name`, `description`, `is_active`, timestamps | 이름 있는 런타임 구성 |
| `profile_agents` | `id`, `profile_id`, `agent_name`, `model_id`, `temperature`, `max_tokens`, timestamps | 프로필별 역할-모델 연결 |

`agent_configs`는 제거된 레거시 테이블입니다. 현재 프로필 설정은 `profile_agents`에 직접 저장합니다.

## 인증과 사용 메타데이터

### `api_keys`

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str, PK | 키 레코드 UUID |
| `name` | str | 표시 이름 |
| `key_hash` | str | 클라이언트 키의 단방향 SHA-256 해시 |
| `prefix` | str | 식별용 접두사 |
| `is_active` | bool | 활성 여부 |
| `last_used_at` | datetime? | 마지막 사용 시각 |
| `created_at` | datetime | 생성 시각 |

### `usage_logs`

`usage_logs`에는 프롬프트, 응답, 입력 해시를 저장하지 않습니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str, PK | 로그 UUID |
| `event` | str | `classify`, `generate` 등 이벤트 |
| `is_sensitive` | bool | 민감 정보 탐지 여부 |
| `records_count` | int | 탐지 레코드 수 |
| `policy_action` | str? | 라우팅 결정 |
| `model_used` | str? | 사용 모델 |
| `latency_ms` | float | 처리 시간 |
| `status_code` | int | 결과 상태 코드 |
| `created_at` | datetime | 생성 시각 |

## 암호화된 임시 데이터

### `responses`

`POST /v1/responses`에서 `store=true`인 경우에만 OpenResponses 리소스를 저장합니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str, PK | 응답 ID |
| `model` | str | 요청 모델 |
| `owner_id` | str?, index | 조회 소유자 |
| `output_json` | str | 전체 응답 JSON의 Fernet 암호문 |
| `status` | str | 응답 상태 |
| `created_at` | datetime | 생성 시각 |
| `expires_at` | datetime?, index | 24시간 만료 시각 |
| `storage_encrypted` | bool | 암호화 저장 형식 표시자 |

평문 `output_text` 컬럼은 없습니다. 조회와 `previous_response_id` 연결은 소유자, 암호화 표시자, 만료 시각을 모두 확인한 뒤 복호화합니다.

### `extraction_cache`

| 필드 | 타입 | 설명 |
|---|---|---|
| `chat_id` | str, PK | 대화 단위 키 |
| `extraction` | str | 추출 결과 JSON의 Fernet 암호문 |
| `context` | str? | 라벨이 있는 대화 문맥의 Fernet 암호문 |
| `created_at` | datetime | 생성 시각 |
| `updated_at` | datetime, index | 마지막 갱신 시각과 비활성 TTL 기준 |

입력에서 계산한 `text_hash`나 평문 masking contract는 저장하지 않습니다.

### `masking_sessions`

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str, PK | 세션 UUID |
| `chat_id` | str?, index | 대화 식별자 |
| `owner_id` | str?, index | REST 소유자 |
| `record_count` | int | 마스킹 레코드 수 |
| `policy_action` | str | 라우팅 결정 |
| `is_active` | bool | 계약 활성 여부 |
| `created_at` | datetime | 생성 시각 |
| `expires_at` | datetime?, index | 24시간 만료 시각 |

### `masking_records`

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str, PK | 레코드 UUID |
| `session_id` | str, FK, index | 마스킹 세션 참조 |
| `uid` | str, index | 레코드마다 새로 생성한 무작위 토큰 |
| `category` | str | 동적으로 도출한 SCREAMING_SNAKE_CASE 분류 |
| `placeholder` | str | `CATEGORY#random8` 형식 토큰 |
| `value_hash` | str | 마스터 키를 사용하는 도메인 분리 HMAC-SHA256 지문 |
| `span` | str | 원문 span의 Fernet 암호문 |
| `confidence` | float | 탐지 신뢰도 |
| `is_essential` | bool | 요청 의도 유지에 필수인지 여부 |
| `created_at` | datetime | 생성 시각 |

`uid`와 플레이스홀더는 원문에서 결정적으로 계산하지 않습니다. `value_hash`는 평문 SHA-256이 아니며 DB 단독 탈취에 대한 사전 대입 위험을 줄이는 키 기반 지문입니다.

## 보존 정책

| 데이터 | 접근 만료 | 물리 삭제 |
|---|---|---|
| `extraction_cache` | `updated_at` 이후 24시간 | 시작 시 및 매시간 |
| `masking_sessions` | `expires_at` 도달 즉시 | 세션과 관련 레코드를 시작 시 및 매시간 |
| `responses` | `expires_at` 도달 즉시 | 시작 시 및 매시간 |
| `usage_logs` | 자동 만료 없음 | 관리자 정책에 따름 |

API 시작 시 `init_db()` 마이그레이션과 최초 정리가 성공해야 서버가 요청을 받습니다. 실행 중 보존 작업은 한 시간마다 반복되며, 한 번의 정리 실패는 기록하고 다음 주기에 다시 시도합니다.

## 마이그레이션 안전 규칙

`db/session.py`의 경량 마이그레이션은 다음 원칙을 적용합니다.

- 레거시 평문 응답은 암호화 형식으로 추정 변환하지 않고 삭제합니다.
- `responses`에 `expires_at`과 `storage_encrypted`가 없으면 추가하고, 암호화·만료 조건을 만족하지 않는 행은 삭제합니다.
- 레거시 `extraction_cache.contract`, `text_hash`, `usage_logs.input_hash`, `masking_sessions.input_hash`를 내용 제거 후 삭제합니다.
- 레거시 `agent_configs` 테이블을 삭제합니다.
- 민감 컬럼 마이그레이션이 실패하면 시작을 중단합니다. 일부만 적용된 상태로 서비스하지 않습니다.

## 관련 문서

- [Storage](storage.md) — 파일, DB, 키 경계
- [Masking & Hydration](../user/masking-hydration.md) — 계약 생성과 복원
- [Privacy and Security](../user/security.md) — 위협 모델과 잔여 위험
