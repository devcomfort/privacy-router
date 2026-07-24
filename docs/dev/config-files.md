# Privacy Router — 설정 파일 구조

## 1. 설정 우선순위

Privacy Router의 런타임 설정 원본은 SQLite의 `provider`, `models`, `workspaces`, `profiles`, `profile_agents` 테이블이다.

1. `config.load_config()`가 `privacy_router.db`를 읽는다.
2. DB가 비어 있으면 `.privacy-router.config.yaml`로 최초 데이터를 생성한다.
3. 기존 DB에는 YAML에 새로 정의된 모델과 필수 역할만 보충한다. 이미 저장된 역할 선택은 덮어쓰지 않는다.
4. `PRIVACY_ROUTER_PROFILE`이 있으면 workspace의 `active_profile`보다 우선한다.
5. API 키는 DB 암호문 → provider별 환경 변수 → `OPENROUTER_API_KEY` 순서로 해석한다.

YAML은 bootstrap과 누락값 fallback이며, 정상 실행 중 모델 선택의 source of truth는 SQLite다.

## 2. 런타임 모델 역할

모델이 연결되는 역할은 정확히 세 개다. Extractor와 Critic은 별도 모델 역할이 아니라 Decision Model을 실행하는 분석 컴포넌트다. Judge와 Router는 결정론적 코드이므로 모델 설정이 없다.

| 설정 키 | 선택 모델 | 위치 | 책임 |
|---|---|---|---|
| `decision` | `openai/google/gemma-4-26b-local` | local, `:8011/v1` | 민감도, exact span, category, `is_essential`을 structured output으로 생성 |
| `local` | 같은 `openai/google/gemma-4-26b-local` endpoint | local, `:8011/v1` | essential-sensitive 원문 요청 생성. 원문은 기기 밖으로 나가지 않음 |
| `external` | `openrouter/google/gemma-4-26b-a4b-it` | external | 비민감 원문 또는 안전하게 마스킹된 요청 생성 |

신뢰 경계는 schema validation으로 강제된다.

- `decision`과 `local`은 `ModelSpec.location == "local"`이어야 한다.
- `external`은 `ModelSpec.location == "external"`이어야 한다.
- 클라이언트가 local model ID를 `/v1/models`에서 선택하거나 외부 전달 모델로 지정할 수 없다.
- `Judge`: `is_sensitive`와 `is_essential`을 policy action으로 변환하는 rule-based 코드다.
- `Router`: policy action을 local, masked external, block 경로로 변환하는 deterministic 코드다.

## 3. `.privacy-router.config.yaml`

```yaml
models:
  - id: openai/google/gemma-4-26b-local
    api_base: http://127.0.0.1:8011/v1
    location: local
    tier: middle
    cost_per_1m_tokens: 0.0

  - id: openrouter/google/gemma-4-26b-a4b-it
    location: external
    tier: middle
    cost_per_1m_tokens: 0.06

decision:
  model: openai/google/gemma-4-26b-local
  config: {temperature: 0.0, max_tokens: 2048}

local:
  model: openai/google/gemma-4-26b-local
  config: {temperature: 0.7, max_tokens: 512}

external:
  model: openrouter/google/gemma-4-26b-a4b-it
  config: {temperature: 0.7, max_tokens: 512}

profiles:
  default:
    description: Local Gemma privacy analysis and generation; OpenRouter Gemma external generation
    decision: {model: openai/google/gemma-4-26b-local}
    local: {model: openai/google/gemma-4-26b-local}
    external: {model: openrouter/google/gemma-4-26b-a4b-it}
```

## 4. SQLite 관계

```text
Workspace.active_profile
        |
        v
Profile ──< ProfileAgent(agent_name, model_id, temperature, max_tokens)
                         |
                         v
Model(model_id, provider_id, location, api_base_override)
                         |
                         v
Provider(api_base, api_key_env)
```

`profile_agents.agent_name`의 유효 런타임 값은 `decision`, `local`, `external`이다. 서버가 기존 DB를 읽을 때 `extractor`, `judge`, `generator` 같은 legacy 역할 행을 제거하고, 누락된 세 역할을 YAML 기본값으로 채운다.

## 5. 환경 변수

| 변수 | 용도 |
|---|---|
| `PRIVACY_ROUTER_PROFILE` | 활성 profile override |
| `PRIVACY_ROUTER_MASTER_KEY` | masking span 암호화와 관리자/데모 세션 토큰 서명의 영속 master key |
| `MASKING_ENCRYPTION_KEY` | legacy master-key fallback |
| `OPENROUTER_API_KEY` | 기본 OpenRouter provider 환경 변수 |
| `PRIVACY_ROUTER_ADMIN_PASSWORD` | `/admin`이 보안 세션으로 교환하는 관리자 비밀번호 |
| `PRIVACY_ROUTER_API_KEY` | Compose에서 SHA-256 hash로 bootstrap할 고정 client key (`pr-`, 24자 이상) |
| `PRIVACY_ROUTER_BIND_HOST` | Compose가 host port를 publish할 주소; 기본값 `127.0.0.1` |
| `PRIVACY_ROUTER_ALLOW_INSECURE_ADMIN` | loopback에만 publish한 Compose에서 HTTP 관리자 로그인을 명시적으로 허용 |
| `PRIVACY_ROUTER_TRUSTED_LOCAL_MODEL_HOSTS` | local model endpoint로 허용하고 cloud credential을 보내지 않을 추가 hostname 목록 |
| `DATABASE_URL` | PostgreSQL 사용 시 DB URL |

master key가 없으면 `dev`가 프로세스 수명의 임시 키를 생성한다. 배포 모드는 유효한 영속 Fernet key 또는 `PRIVACY_ROUTER_ADMIN_PASSWORD`가 없으면 요청을 받기 전에 시작을 중단한다.

## 6. 설정 API

설정 API는 관리자 세션 쿠키를 요구한다. `POST`, `PATCH`, `PUT`, `DELETE` 요청은 같은 세션에서 발급된 `X-Privacy-Router-CSRF-Token`도 검증한다. `serve`는 관리자 비밀번호 또는 master key가 없으면 시작하지 않으며, 잘못된 로그인은 `401`, 잘못된 CSRF token은 `403`으로 실패한다.

| Endpoint | 의미 |
|---|---|
| `GET /api/settings` | 현재 `decision`, `local`, `external` 역할과 profile metadata 조회 |
| `POST /api/settings` | 세 역할의 model/temperature/max_tokens 변경 |
| `GET /api/providers` | provider와 환경 변수 기반 key 상태 조회 |
| `GET /api/profiles` | profile 목록 조회 |
| `POST /api/profiles/activate` | workspace의 활성 profile 변경 |

설정 변경 후 서버의 메모리 singleton을 무효화하므로 다음 요청부터 새 역할 선택이 적용된다.

## 7. Docker 서비스

| Service | 역할 | 기본 포트 |
|---|---|---:|
| `db` | PostgreSQL 16 | 5433 |
| `api` | FastAPI Privacy Router | 8787 |
| `hermes` | Hermes Agent | 7860 |
| `vllm-gemma4` | Optional local decision and generation model | 8011 |

Decision Model과 Local Model은 같은 Gemma 4 26B OpenAI-compatible endpoint `:8011/v1`을 사용한다. Docker API는 `host.docker.internal:8011`을 명시적으로 신뢰한 로컬 모델 호스트로 연결한다.

## Related Documents

- [Architecture](architecture.md) — 실행 pipeline과 신뢰 경계
- [Database ERD](database-erd.md) — 전체 테이블 정의
- [Getting Started](../user/getting-started.md) — 실행과 초기 설정
- [Security](../user/security.md) — 키 관리와 fail-closed 정책
