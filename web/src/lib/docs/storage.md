# Storage

Privacy Router가 파일, 데이터베이스, 프로세스 메모리에 저장하는 데이터와 보존 경계를 설명합니다.

## 저장소 경계

| 저장소 | 용도 | 민감 원문 가능 여부 |
|---|---|---|
| 프로세스 메모리 | 현재 요청, 복호화된 계약, 런타임 설정 | 요청 처리 중 가능 |
| SQLite/PostgreSQL | 설정, 인증, 메타데이터, 암호화된 임시 데이터 | Fernet 암호문으로만 허용 |
| `.privacy-router.config.yaml` | DB 초기 시드와 YAML 폴백 | 비밀 저장 금지 |
| 환경변수/외부 비밀 저장소 | 마스터 키와 provider 키 폴백 | 가능; DB 밖에서 관리 |
| `web/build/` | SvelteKit 정적 출력 | 민감 런타임 데이터 없음 |

개발 기본 DB는 `privacy_router.db`입니다. `DATABASE_URL`을 설정하면 같은 SQLModel 스키마를 PostgreSQL에서 사용합니다.

## 데이터베이스 테이블

| 영역 | 테이블 | 저장 내용 |
|---|---|---|
| 설정 | `provider`, `models`, `workspaces`, `profiles`, `profile_agents` | provider·모델·프로필 구성 |
| 인증 | `api_keys` | 클라이언트 키의 SHA-256 해시와 상태 |
| 메타데이터 | `usage_logs` | 이벤트, 민감 여부, 레코드 수, 정책, 모델, 지연, 상태 코드 |
| 응답 | `responses` | Fernet 암호화된 OpenResponses JSON과 24시간 TTL |
| 마스킹 | `masking_sessions`, `masking_records` | 소유권·TTL·무작위 토큰·HMAC 지문·암호화 span |
| 추출 캐시 | `extraction_cache` | Fernet 암호화된 추출 결과와 라벨이 있는 대화 문맥 |

`usage_logs`에는 프롬프트, 응답, 민감 span, 입력 지문을 저장하지 않습니다. 현재 관계는 [Architecture](/docs/architecture)를 참조하세요.

## 설정 로드

SQLite/PostgreSQL이 런타임 설정의 우선 소스입니다. 활성 workspace/profile의 `profile_agents` 행을 먼저 읽고, 필요한 역할이 없을 때 `.privacy-router.config.yaml`을 폴백으로 사용합니다. YAML 파일은 모델 목록과 기본 역할 구성을 시드할 수 있지만 API 키를 포함하면 안 됩니다.

레거시 `agent_configs` 테이블은 사용하지 않으며 시작 마이그레이션에서 삭제합니다.

## 암호화

### 마스터 키 조회

1. `PRIVACY_ROUTER_MASTER_KEY`
2. 레거시 호환용 `MASKING_ENCRYPTION_KEY`
3. 개발용 프로세스 임시 키

프로덕션에서는 안정적인 외부 비밀 저장소가 제공하는 키를 사용해야 합니다. 자동 생성 키는 프로세스 재시작 뒤 이전 암호문을 복호화할 수 없습니다.

### 암호화 대상

| 데이터 | DB 필드 | 보호 방식 |
|---|---|---|
| 추출 결과 | `extraction_cache.extraction` | Fernet authenticated encryption |
| 대화 문맥 | `extraction_cache.context` | Fernet authenticated encryption |
| 마스킹 원문 | `masking_records.span` | Fernet authenticated encryption |
| 저장 응답 | `responses.output_json` | Fernet authenticated encryption |
| Provider API 키 | `provider.encrypted_api_key` | Fernet authenticated encryption |
| 마스킹 값 비교 지문 | `masking_records.value_hash` | 마스터 키를 사용하는 도메인 분리 HMAC-SHA256 |
| 클라이언트 API 키 | `api_keys.key_hash` | 단방향 SHA-256 해시 |

플레이스홀더는 값 해시가 아니라 요청마다 새로 생성한 `CATEGORY#random8` 토큰입니다. `value_hash`는 평문 SHA-256이 아니며 외부 전송용 토큰에도 포함되지 않습니다.

### Provider API 키 조회

1. `provider.encrypted_api_key`
2. provider의 `api_key_env`가 가리키는 환경변수
3. `OPENROUTER_API_KEY`

## 보존 정책

| 데이터 | TTL | 접근 제어 | 물리 삭제 |
|---|---|---|---|
| `extraction_cache` | 마지막 갱신 후 24시간 | 캐시 read/write 시 만료 거부 | 시작 시 및 매시간 |
| `masking_sessions`와 관련 레코드 | 생성 후 24시간 | 계약·REST 조회 시 만료 거부 | 시작 시 및 매시간 |
| `responses` (`store=true`) | 생성 후 24시간 | GET·삭제·연속 응답 조회 시 만료 거부 | 시작 시 및 매시간 |
| `usage_logs` | 자동 TTL 없음 | 원문 없는 메타데이터만 저장 | 관리자 정책 |
| Provider API 키 | 자동 TTL 없음 | 암호화 저장 | 키 삭제 API |

FastAPI lifespan은 `init_db()`와 최초 `purge_expired_data()`가 성공한 뒤에만 요청을 받습니다. 이후 한 시간 간격의 작업이 만료 행을 삭제합니다. 반복 작업의 일시적 실패는 기록하고 다음 주기에 재시도하며, 이미 만료된 데이터는 조회 경로에서 계속 거부됩니다.

## 시작 마이그레이션

경량 마이그레이션은 민감 데이터에 대해 fail-closed로 동작합니다.

- 레거시 평문 응답 행은 암호화된 것으로 간주하지 않고 삭제합니다.
- `responses`에는 `expires_at`, `storage_encrypted`, `owner_id`를 보장합니다.
- 암호화 표시자나 만료 시각이 없는 응답 행을 삭제합니다.
- 레거시 평문 contract와 입력 지문 컬럼은 값을 제거한 뒤 컬럼을 삭제합니다.
- 필수 마이그레이션이 실패하면 API 시작도 실패합니다.

## 주요 환경변수

| 변수 | 설명 |
|---|---|
| `DATABASE_URL` | DB 연결 URL; 없으면 SQLite |
| `PRIVACY_ROUTER_MASTER_KEY` | 암호화와 도메인 분리 HMAC의 루트 키 |
| `MASKING_ENCRYPTION_KEY` | 레거시 마스터 키 폴백 |
| `OPENROUTER_API_KEY` | OpenRouter 키의 최종 환경변수 폴백 |

## Docker

`docker compose up -d`는 API와 PostgreSQL을 포함한 프로젝트 서비스를 시작합니다. 컨테이너 내부 API는 `db:5432`에 연결하고, 호스트에 노출된 PostgreSQL 포트는 compose 설정을 따릅니다.

## 관련 문서

- [Architecture](/docs/architecture) — 시스템 구성과 데이터 흐름
- [Masking & Hydration](/docs/masking) — 계약 생성과 복원
- [Privacy and Security](/docs/security) — 위협 모델과 잔여 위험
