<h1 align="center">Privacy Router</h1>

<p align="center">
  <strong>에이전트 프롬프트가 외부 API로 나가기 전에 개인정보를 검사하고 보호하는 프록시 레이어</strong>
</p>

<p align="center">
  <a href="#빠른-시작">빠른 시작</a> ·
  <a href="#파이프라인">파이프라인</a> ·
  <a href="#api">API</a> ·
  <a href="#설정">설정</a> ·
  <a href="#observability">Observability</a> ·
  <a href="#연동">연동</a>
</p>

---
## Executive Summary

**Privacy Router**는 AI 에이전트(Hermes Agent, OpenClaw 등)의 프롬프트가 외부 LLM API로 전송되기 전에 민감 정보를 자동으로 탐지, 마스킹, 라우팅하는 프록시 레이어입니다.

| 기능 | 설명 |
|---|---|
| **민감 정보 탐지** | SLM 기반 맥락적 분석 (Three-harm test). 주민등록번호, 사업비밀, 미공개 연구 등 |
| **마스킹** | UID 기반 플레이스홀더 치환. DB 영속화 + Fernet 암호화 |
| **라우팅** | 3개 정책 — `allow` (안전), `mask_and_send` (마스킹 후 전송), `prompt_user` (사용자 확인) |
| **연동** | OpenAI Compatible API + MCP 서버. 에이전트 코드 수정 없이 `base_url` 변경만으로 적용 |
| **Observability** | 순수 OpenTelemetry. Prometheus + Grafana + Loki |

```bash
# 30초 만에 실행
docker compose up
# → http://localhost:8787 (Chat UI)
# → http://localhost:8787/docs (Swagger)

# Observability 포함 (Grafana, Prometheus, Loki)
COMPOSE_PROFILES=observability docker compose up
# → http://localhost:3000 (Grafana)

# OpenCode Go 중개서버 포함
COMPOSE_PROFILES=opencode-go docker compose up
# → http://localhost:8789 (OpenCode Go Relay)

# 모두 포함
COMPOSE_PROFILES=observability,opencode-go docker compose up
```



## 무엇을 하나요?

AI 에이전트가 사용자를 대신하여 이메일을 작성하거나, 문서를 정리하거나, 양식을 채울 때, 민감한 정보가 외부 API(OpenAI, Anthropic 등)로 전송될 수 있습니다.

**Privacy Router**는 에이전트 프롬프트가 외부로 나가기 전에:

1. **탐지** — SLM이 맥락적으로 개인정보·영업비밀·미공개 연구를 식별합니다
2. **판정** — "마스킹해도 질의 의미가 유지되는가?"를 판단합니다
3. **라우팅** — 정책에 따라 외부 API 전송, 마스킹 후 전송, 로컬 처리 등을 결정합니다

| 단계 | 컴포넌트 | 역할 |
|---|---|---|
| 입력 | 사용자 프롬프트 | 에이전트가 보낸 원본 텍스트 |
| ↓ | | |
| 1단계 | **Extractor (SLM)** | SLM이 맥락적으로 민감 정보 탐지 + load-bearing 판정 |
| ↓ | | |
| 2단계 | **Router (Rule-based)** | `is_load_bearing` 기반 rule-based 정책 결정 |
| ↓ | | |
| 결과 | `allow` | 민감 정보 없음 → 외부 API로 직접 전송 |
| | `prompt_user` | load_bearing 레코드 포함 → 사용자에게 확인 요청 (409) |
| | `mask_and_send` | 비-load-bearing만 → 전체 마스킹 후 외부 API, 응답 재수화 |

---

## 빠른 시작

### 1. 환경 설정

```bash
git clone <repo-url> && cd privacy-router
cp .env.example .env
# .env에서 OPENROUTER_API_KEY=sk-or-v1-... 설정
```

### 2. 실행

```bash
# 최소 모드 (API + DB)
docker compose up

# Observability 포함 (Grafana, Prometheus, Loki)
COMPOSE_PROFILES=observability docker compose up

# 개발 모드 (hot-reload + observability)
cp .env.dev .env && docker compose up
```

#### COMPOSE_PROFILES 설명 ([상세 문서](docs/knowledges/compose-profiles.md))

Docker Compose의 `profiles`는 서비스를 선택적으로 활성화합니다. `profiles`가 없는 서비스(db, api)는 항상 실행되고, `profiles`가 지정된 서비스는 해당 프로파일이 활성화될 때만 포함됩니다.

| 프로파일 | 활성화되는 서비스 | 용도 |
|---|---|---|
| _(없음)_ | db, api | 핵심 기능 — 항상 실행 |
| `observability` | otel-collector, prometheus, loki, promtail, grafana | 메트릭/로그 대시보드 — 프로덕션 모니터링용 |

- **otel-collector**: Privacy Router에서 발생하는 메트릭/트레이스를 수집하는 집계 지점
- **prometheus**: `pii_detected`, `pii_masked`, `pipeline_stage_duration` 같은 커스텀 메트릭 저장/쿼리
- **loki**: 서버 로그 구조화 저장소
- **promtail**: Docker 컨테이너 로그를 자동으로 Loki에 전달하는 에이전트
- **grafana**: Prometheus + Loki를 하나의 대시보드 UI에서 시각화

`.env`에 `COMPOSE_PROFILES=observability`를 설정하면 `docker compose up`만으로 모니터링 스택이 함께 실행됩니다.

### 3. 접속

| 서비스 | URL | 설명 |
|---|---|---|
| **Chat UI** | http://localhost:8787 | 대화형 데모 페이지 |
| **API** | http://localhost:8787/v1/chat/completions | OpenAI 호환 엔드포인트 |
| **Grafana** | http://localhost:3000 | 대시보드 (`admin` / `privacy-router`) |
| **Prometheus** | http://localhost:9090 | 메트릭 쿼리 |

### 4. 테스트

```bash
# 비민감 요청 → 정상 응답
curl http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "openrouter/mistralai/ministral-3b-2512", "messages": [{"role": "user", "content": "오늘 서울 날씨는 맑고 기온은 25도입니다."}]}'

# 민감 요청 → 마스킹 후 전송 또는 확인 필요
curl http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "openrouter/mistralai/ministral-3b-2512", "messages": [{"role": "user", "content": "주민등록번호 901212-1234567을 확인해주세요"}]}'
```

---

## 파이프라인

### Extractor (탐지)

SLM을 사용하여 맥락적으로 민감 정보를 탐지합니다. **Three-harm test** 프레임워크를 적용합니다 ([상세 문서](docs/knowledges/three-harm-test.md)):

- **IDENTITY** — 개인 식별 정보 (주민번호, 전화번호, 이메일, 계좌번호 등)
- **COMPETITIVE** — 영업비밀, 미공개 전략 (공정 결정, 예산, M&A 등)
- **SAFETY** — 미공개 연구, 특허 출원 전 아이디어 등

각 레코드에 `is_load_bearing` 플래그를 판정합니다. 마스킹 시 질의 의미가 유지되면 `false`, 의미가 손상되면 `true`입니다.

```python
from agents.extractor import Extractor

extractor = Extractor()
result = extractor.extract("주민등록번호 901212-1234567을 확인해주세요")

result.sensitivity.is_sensitive       # True
result.records[0].category           # "RESIDENT_REGISTRATION_NUMBER"
result.records[0].span               # "901212-1234567"
result.records[0].is_load_bearing    # False (마스킹해도 의미 유지)
```

**TwoPhaseExtractor**는 1차 탐지 후 Critic 패스를 한 번 더 실행하여 누락된 레코드를 보완합니다.

### Router (정책 결정)

Extractor의 `is_load_bearing` 플래그를 기반으로 rule-based 정책을 결정합니다. 별도의 Judge LLM 호출 없이 동작합니다.

| 조건 | policy_action | 설명 |
|---|---|---|
| 민감 레코드 없음 | `allow` | 외부 API로 직접 전송 |
| 레코드 있지만 전부 load_bearing=false | `mask_and_send` | 전체 마스킹 후 외부 API 전송, 응답 재수화 |
| 레코드 중 하나라도 load_bearing=true | `prompt_user` | 사용자에게 확인 요청 (409 응답) |

### Masker (마스킹 / 하이드레이션) ([상세 문서](docs/knowledges/masking-hydration.md))

민감 정보를 `[CATEGORY#N]` 플레이스홀더로 치환하고, LLM 응답에서 원본으로 복원합니다.

```python
from agents.masker import Masker

masker = Masker()

# 마스킹
result = masker.mask(
    text="주민번호 901212-1234567 전화 010-9876-5432",
    records=[...],
)
result.masked_text  # "주민번호 [RESIDENT_REGISTRATION_NUMBER#1] 전화 [MOBILE_PHONE_NUMBER#1]"

# LLM 호출 후 하이드레이션
hydrated = masker.hydrate(llm_response, result.contract)
"901212-1234567" in hydrated.hydrated_text  # True
```

**MaskingContract**는 마스킹 단계에서 생성되어 하이드레이션 단계에서 소비되는 불변 객체입니다. 플레이스홀더 매핑과 유효성 검증을 담당합니다.

### Evaluator (선택적)

개별 레코드의 load-bearing 여부를 독립적으로 재평가하는 모듈입니다. 현재 메인 파이프라인에 연결되어 있지 않으며, 향후 정밀한 per-record 판정이 필요할 때 플러그인으로 사용합니다.

```python
from agents.evaluator import PerRecordEvaluator

evaluator = PerRecordEvaluator()
evaluation = evaluator.evaluate(text, records)
evaluation.any_load_bearing       # True/False
evaluation.recommended_action     # "selective_mask" / "process_locally"
```

---

## API

### OpenAI 호환 엔드포인트

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| `POST` | `/v1/chat/completions` | ✅ | Chat Completions 프록시 + 프라이버시 파이프라인 |
| `POST` | `/v1/responses` | ✅ | OpenResponses 호환 엔드포인트 |
| `GET` | `/v1/responses/{id}` | ✅ | 응답 조회 (stub) |
| `GET` | `/v1/models` | — | 사용 가능한 모델 목록 (공개) |

### 관리 API

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| `POST` | `/api/v1/classify` | ✅ | 프롬프트 분류 (Extractor + Router, LLM 호출 없음) |
| `POST` | `/api/v1/generate` | ✅ | 파이프라인 실행 후 LLM 생성 |
| `POST` | `/api/v1/guardrail` | ✅ | Guardrail 엔드포인트 |
| `GET/POST` | `/api/v1/providers` | ✅ | LLM 프로바이더 관리 |
| `GET/POST` | `/api/v1/keys` | ✅ | API 키 관리 (SHA-256 해시 저장) |
| `POST` | `/api/v1/keys/{id}/rotate` | ✅ | 키 로테이션 (기존 비활성화 + 새 키 생성) |
| `DELETE` | `/api/v1/keys/{id}` | ✅ | API 키 비활성화 |
| `GET/POST` | `/api/v1/models` | ✅ | 모델 등록/조회 |
| `DELETE` | `/api/v1/models/{id}` | ✅ | 모델 비활성화 |
| `POST` | `/api/v1/models/probe` | ✅ | 업스트림 모델 가용성 확인 |
| `GET/PUT` | `/api/v1/agent-configs` | ✅ | 에이전트별 모델 설정 |
| `GET` | `/api/v1/masking/{session_id}` | ✅ | 마스킹 세션 상세 조회 |
| `POST` | `/api/v1/masking/{session_id}/hydrate` | ✅ | 하이드레이션 (암호화된 컨트랙트로 원본 복원) |
| `GET/POST` | `/api/settings` | — | 데모 UI 설정 (공개) |

### 인증 ([상세 문서](docs/knowledges/api-keys.md))

API 키는 `pr-{token_urlsafe(32)}` 형식으로 생성되며, SHA-256 해시만 데이터베이스에 저장됩니다.

```bash
# API 키로 요청
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer pr-xxxxxxxx..." \
  -H "Content-Type: application/json" \
  -d '{"model": "...", "messages": [...]}'
```

### Chat Completions 응답

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "안녕하세요, 김동현님..."
    }
  }],
  "privacy_router": {
    "is_sensitive": true,
    "records": [
      {
        "category": "RESIDENT_REGISTRATION_NUMBER",
        "span": "901212-1234567",
        "confidence": 0.95,
        "is_load_bearing": false,
        "detection_type": "pattern"
      }
    ],
    "policy_action": "mask_and_send",
    "requires_masking": true,
    "masked_text": "... [RESIDENT_REGISTRATION_NUMBER#1] ...",
    "original_text": "주민등록번호 901212-1234567을 확인해주세요",
    "description": "PII detected, masked for external API"
  }
}
```

**409 Conflict** — `prompt_user` 정책일 때 반환됩니다. 사용자가 `X-Privacy-Router-Confirm: true` 헤더와 함께 재요청하면 원본 데이터로 전송됩니다.

---

## 설정

### 모델 설정 ([상세 문서](docs/knowledges/model-registry.md))

Privacy Router는 **모델에 구애받지 않습니다**. `litellm`을 통해 OpenRouter, OpenAI, Anthropic, Google, 로컬 vLLM 등 모든 호환 프로바이더를 사용할 수 있습니다.

`.privacy-router.config.yaml`에서 모델 레지스트리와 에이전트별 모델을 설정합니다:

```yaml
models:
  - id: openrouter/mistralai/ministral-3b-2512
    location: external
    tier: small
    cost_per_1m_tokens: 0.10
  - id: openrouter/google/gemini-3.1-flash-lite
    location: external
    tier: large
    cost_per_1m_tokens: 0.25
  - id: openai/Qwen/Qwen3-4B
    api_base: http://localhost:8000/v1
    location: local
    tier: small
    cost_per_1m_tokens: 0.0

agents:
  extractor:
    model: openrouter/mistralai/ministral-3b-2512
    config:
      temperature: 0.0
      max_tokens: 4096
  judge:
    model: openrouter/google/gemini-3.1-flash-lite
    config:
      temperature: 0.0
  generator:
    model: openrouter/mistralai/ministral-3b-2512
  local:
    model: openrouter/mistralai/ministral-3b-2512
```

에이전트별로 다른 모델을 지정할 수 있습니다. 예를 들어 Extractor는 저렴한 소형 모델, Judge는 정밀한 모델을 사용하는 것이 효율적입니다.

### 프롬프트 파일

각 에이전트의 프롬프트는 `agents/<agent>/` 디렉토리의 `.prompt` 파일에 정의됩니다. `dotpromptz` 형식으로 YAML 프론트매터에 모델과 파라미터를 지정합니다:

```
agents/
├── extractor/
│   ├── extract.prompt     # 1차 탐지 프롬프트
│   └── critic.prompt      # 2차 Critic 프롬프트
├── judge/
│   └── classify.prompt    # 정책 판별 프롬프트
└── evaluator/
    └── evaluate.prompt    # Per-record 평가 프롬프트
```

### 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `COMPOSE_PROFILES` | (비어있음) | Docker Compose 프로필 (`observability`) |
| `DOCKERFILE` | `Dockerfile` | 빌드할 Dockerfile (`Dockerfile.dev` for hot-reload) |
| `API_PORT` | `8787` | API 서버 포트 |
| `OPENROUTER_API_KEY` | — | OpenRouter API 키 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTel Collector 주소 |
| `POSTGRES_USER` | `privacy_router` | PostgreSQL 사용자 |
| `POSTGRES_PASSWORD` | `privacy_router` | PostgreSQL 비밀번호 |
| `POSTGRES_DB` | `privacy_router` | PostgreSQL 데이터베이스 |
| `LLM_MODEL` | — | 기본 LLM 모델 (프롬프트 파일의 모델 설정을 오버라이드) |

---

## MCP 도구 ([상세 문서](docs/knowledges/mcp.md))

Privacy Router는 [Model Context Protocol](https://modelcontextprotocol.io/) 서버로도 동작합니다. stdio 기반으로 에이전트 호스트에 통합됩니다.
### `process` 도구 ([상세 문서](docs/knowledges/mcp.md))

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `text` | `str` | 처리할 프롬프트 텍스트 |
| `action` | `str` | `auto`(기본): 전체 파이프라인 / `classify`: 탐지만 / `generate`: 강제 LLM 호출 / `allow`: 검사 건너뜀 |
| `model` | `str?` | 생성 모델 오버라이드 |
| `chat_id` | `str?` | 채팅/대화 ID. 마스킹 세션을 DB에 영속화하고 `masking_session_id` 반환 |
---

## Observability ([상세 문서](docs/knowledges/observability.md))

**클라우드 의존성 없는 순수 OpenTelemetry 기반 관측 스택.**

```bash
COMPOSE_PROFILES=observability docker compose up
```

### 아키텍처

| 컴포넌트 | 포트 | 역할 | 연결 |
|---|---|---|---|
| **Privacy Router** (FastAPI + OTel SDK) | 8787 | 메트릭/트레이스 생성 | → OTel Collector (OTLP gRPC :4317) |
| **OTel Collector** | 4317, 4318 | 수집 지점. 데이터를 Prometheus/Loki로 분배 | → Prometheus, Loki, stdout |
| **Prometheus** | 9090 | 메트릭 시계열 저장소 | ← Collector |
| **Loki** | 3100 | 로그 저장소 | ← Promtail |
| **Promtail** | — | Docker 컨테이너 로그 → Loki 전달 | → Loki |
| **Grafana** | 3000 | 대시보드 UI (메트릭 + 로그 시각화) | ← Prometheus, Loki |

### 측정 메트릭

| 메트릭 | 타입 | 정의 | 단위 |
|---|---|---|---|
| `pipeline_stage_duration` | Histogram | 파이프라인 단계별 시간 | 초 |
| `llm_ttft` | Histogram | 요청 → 첫 토큰 수신 (Time to First Token) | 초 |
| `llm_tpot` | Histogram | 토큰당 평균 생성 시간 | 초 |
| `llm_itl` | Histogram | 연속 토큰 간 시간 (Inter-Token Latency) | 초 |
| `llm_throughput` | Histogram | 초당 출력 토큰 수 | tokens/s |
| `pii_detected` | Counter | 탐지된 PII 레코드 수 | 건 |
| `pii_masked` | Counter | 마스킹된 PII 레코드 수 | 건 |

### 코드에서 사용

```python
from server.observability import timed_span, pii_detected, pii_masked

# 파이프라인 자동 타이밍 + PII 카운터 (proxy.py에서 자동 실행)
with timed_span("pipeline", {"model": backend_model}) as span:
    pipeline = PrivacyRouter().process(user_text)
    n_records = len(pipeline.records)
    if n_records:
        pii_detected.add(n_records)
    if pipeline.route.requires_masking:
        pii_masked.add(n_records)
    span.set_attribute("policy_action", pipeline.route.endpoint)
```

---

## 연동

Privacy Router는 OpenAI 호환 API를 제공하므로 `base_url`만 변경하면 기존 도구에 바로 연결됩니다.

### Hermes Agent / OpenClaw / OpenCode

```yaml
# config에서 base_url만 변경
base_url: http://localhost:8787/v1
api_key: pr-xxxxxxxx...
```

### LiteLLM

```yaml
# litellm_config.yaml
model_list:
  - model_name: privacy-router-model
    litellm_params:
      model: openai/privacy-router-model
      api_base: http://localhost:8787/v1
      api_key: pr-xxxxxxxx...
```

### ACP (Agent Client Protocol)

ACP의 `providers/set`에서 privacy-router 엔드포인트를 등록하면 Hermes, OpenClaw, OpenCode가 자동으로 사용합니다.

---

## 아키텍처

### 프로젝트 구조

```
privacy-router/
├── agents/                     # 프라이버시 파이프라인
│   ├── extractor/              #   SLM 기반 민감 정보 탐지 (TwoPhaseExtractor)
│   ├── judge/                  #   정책 판별 (선택적, 현재 rule-based 대체)
│   ├── evaluator/              #   Per-record load-bearing 평가 (선택적)
│   ├── masker/                 #   마스킹 / 하이드레이션
│   ├── router/                 #   오케스트레이션 + 라우팅 결정
│   ├── memory/                 #   세션 메모리 (미연결)
│   └── llm.py                  #   LLM 호출 유틸리티 (litellm + instructor)
│
├── server/                     # API 서버
│   ├── api/                    #   FastAPI 라우트
│   │   ├── routes/             #     엔드포인트 (7개 모듈)
│   │   ├── auth.py             #     인증 (Bearer 토큰, SHA-256)
│   │   ├── streaming.py        #     스트리밍 하이드레이션
│   │   └── adapter.py          #     LLM 어댑터 해석
│   ├── adapters/               #   LLM 프로바이더 어댑터
│   │   ├── base.py             #     LiteLLMAdapter (기본)
│   │   └── openrouter.py       #     OpenRouterAdapter
│   ├── mcp/                    #   MCP 서버 (stdio)
│   ├── observability.py        #   OTel 설정 + 메트릭
│   └── config.py               #   서버 설정 싱글턴
│
├── config/                     # YAML 설정 시스템
│   ├── schemas.py              #   Pydantic 모델 (ModelSpec, AgentConfig 등)
│   └── loader.py               #   YAML 로더 (환경변수 보간)
│
├── db/                         # 데이터베이스 (SQLModel + PostgreSQL)
│   ├── models.py               #   Provider, ApiKey, Model, AgentConfig, UsageLog
│   └── session.py              #   엔진 + 세션 팩토리
│
├── web/                        # Chat UI (정적 HTML)
├── observability/              # OTel/Prometheus/Loki/Grafana 설정
│
├── docker-compose.yml          # 통합 Compose (profiles 기반)
├── Dockerfile                  # 프로덕션 이미지
├── Dockerfile.dev              # 개발 이미지 (hot-reload)
├── .privacy-router.config.yaml # 모델 레지스트리 + 에이전트 설정
├── .env.example                # 환경 변수 템플릿
└── .env.dev                    # 개발 환경 변수
```

### 의존성 흐름

| 계층 | 컴포넌트 | 역할 |
|---|---|---|
| **진입점** | `server/mcp` (MCP tools) | MCP 프로토콜을 통한 에이전트 통합 |
| | `server/api/routes` (FastAPI) | HTTP 엔드포인트 (OpenAI 호환 + 관리 API) |
| ↓ | | |
| **오케스트레이션** | `agents/router` (PrivacyRouter) | 파이프라인 조율: Extract → Route → Mask → LLM |
| ↓ | | |
| **구현체** | `agents/extractor` | SLM 기반 민감 정보 탐지 |
| | `agents/masker` | 마스킹 / 하이드레이션 |
| | `agents/llm.py` | LLM 호출 유틸리티 |
| ↓ | | |
| **설정/외부** | `config/` (YAML) | 모델 레지스트리, 에이전트 설정 |
| | `litellm` + `instructor` | LLM 프로바이더 통합, 구조화 출력 |

### 데이터베이스 모델

| 테이블 | 설명 |
|---|---|
| `providers` | LLM 프로바이더 (openrouter, openai, custom) |
| `api_keys` | API 키 (SHA-256 해시, `pr-` 접두사) |
| `models` | 등록된 모델 (tier, cost, soft-delete) |
| `agent_configs` | 에이전트별 모델 매핑 |
| `usage_logs` | 사용 로그 |
| `masking_sessions` | 마스킹 세션 (chat_id, input_hash, policy_action) |
| `masking_records` | 마스킹 레코드 (uid, category, placeholder, value_hash) |

---

## 테스트

```bash
# 전체 테스트
rye run pytest agents/ -v

# 특정 패키지
rye run pytest agents/extractor/ -v   # 탐지 검증 로직
rye run pytest agents/judge/ -v       # 정책 판별
rye run pytest agents/masker/ -v      # 마스킹/하이드레이션 라운드트립
rye run pytest server/tests/ -v       # API 통합 테스트
```

---

## 참고

### 프로젝트 문서

- [AGENTS.md](AGENTS.md) — 프로젝트 컨벤션
- [docs/architectures/ARCHITECTURE.md](docs/architectures/ARCHITECTURE.md) — 시스템 아키텍처 다이어그램 (Mermaid)
- [docs/architectures/INTEGRATION_ARCHITECTURE.md](docs/architectures/INTEGRATION_ARCHITECTURE.md) — 연동 아키텍처 상세
- [TODO.md](TODO.md) — 향후 작업
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 트러블슈팅 가이드

### 개념 상세 문서

- [docs/knowledges/three-harm-test.md](docs/knowledges/three-harm-test.md) — Three-harm test 프레임워크 (IDENTITY/COMPETITIVE/SAFETY)
- [docs/knowledges/masking-hydration.md](docs/knowledges/masking-hydration.md) — 마스킹/하이드레이션 동작 원리
- [docs/knowledges/model-registry.md](docs/knowledges/model-registry.md) — 모델 레지스트리 설정 및 에이전트별 모델 지정
- [docs/knowledges/mcp.md](docs/knowledges/mcp.md) — MCP 서버 통합 방법
- [docs/knowledges/observability.md](docs/knowledges/observability.md) — Observability 스택 구성
- [docs/knowledges/api-keys.md](docs/knowledges/api-keys.md) — API 키 관리
- [docs/knowledges/compose-profiles.md](docs/knowledges/compose-profiles.md) — Docker Compose Profiles 사용법
