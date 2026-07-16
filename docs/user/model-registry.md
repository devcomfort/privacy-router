# Model Registry

Privacy Router는 모델에 구애받지 않습니다. `litellm`을 통해 모든 호환 프로바이더를 사용할 수 있습니다.

## 모델 스키마

모델은 두 가지 차원으로 분류됩니다:

| 차원 | 값 | 설명 |
|---|---|---|
| **location** | `local` | 명시적 포트를 가진 loopback OpenAI 호환 엔드포인트 |
| | `external` | 클라우드 API (OpenRouter, OpenAI 등) |
| **tier** | `small` | <8B 파라미터 (SLM, edge 추론) |
| | `middle` | 8-30B 파라미터 (균형) |
| | `large` | >30B 파라미터 (프론티어) |

`local`은 배포 위치의 설명이 아니라 강제되는 신뢰 경계입니다. 사용자 지정
`api_base`는 `localhost`, `127.0.0.1`, 또는 `::1`의 명시적 포트를 사용해야
합니다. `ollama/`와 `ollama_chat/` 모델은 주소를 생략하면 loopback 기본값
`http://127.0.0.1:11434`를 사용합니다. 원격 호스트와 사설망 주소는 로컬
역할에 등록할 수 없습니다.

## 설정 파일

`.privacy-router.config.yaml`의 `models` 섹션에 모델을 등록합니다:

```yaml
models:
  - id: openrouter/mistralai/ministral-3b-2512
    location: external
    tier: small
    cost_per_1m_tokens: 0.10

  - id: openai/Qwen/Qwen3.5-9B
    api_base: http://localhost:8000/v1
    location: local
    tier: middle
    cost_per_1m_tokens: 0.0

  - id: openrouter/google/gemini-3.1-flash-lite
    location: external
    tier: large
    cost_per_1m_tokens: 0.25
```

## 모델 ID 접두사

| 접두사 | 프로바이더 | 예시 |
|---|---|---|
| `openrouter/...` | OpenRouter (다수 프로바이더, 하나의 API 키) | `openrouter/mistralai/ministral-3b-2512` |
| `openai/...` | OpenAI 또는 OpenAI 호환 엔드포인트 | `openai/Qwen/Qwen3.5-9B` |
| `ollama/...` | Ollama API | `api_base` 생략 시 `http://127.0.0.1:11434` 사용 |
| `anthropic/...` | Anthropic 직접 | `anthropic/claude-haiku-4.5` |
| `google/...` | Google Gemini 직접 | `google/gemini-3.1-flash-lite` |

## 런타임 역할별 모델 설정

프로필은 신뢰 경계가 다른 세 런타임 역할을 지정합니다. `decision`과 `local`은
`location: local`, `external`은 `location: external` 모델만 사용할 수 있습니다.
Extractor·Judge·Router는 파이프라인 컴포넌트이며 독립적인 선택 모델 역할이 아닙니다.

```yaml
decision:
  model: openai/LGAI-EXAONE/EXAONE-4.0-1.2B  # 민감도·span 판정
  config:
    temperature: 0.0
    max_tokens: 4096

local:
  model: openai/google/gemma-4-26b-local      # 차단된 raw 요청의 온디바이스 생성
  config:
    temperature: 0.7
    max_tokens: 512

external:
  model: openrouter/google/gemma-4-26b-a4b-it  # 비민감/마스킹 완료 요청의 클라우드 생성
  config:
    temperature: 0.7
    max_tokens: 512
```

## DB를 통한 동적 관리

API를 통해 모델을 동적으로 등록/삭제할 수 있습니다:

```bash
# 공개 추론 모델 ID 목록
curl http://localhost:8787/v1/models

# 전체 관리 레지스트리 조회
curl http://localhost:8787/api/v1/models \
  -H "X-Privacy-Router-Admin-Key: <admin-key>"

# 모델 등록
curl -X POST http://localhost:8787/api/v1/models \
  -H "X-Privacy-Router-Admin-Key: <admin-key>" \
  -H "Content-Type: application/json" \
  -d '{"model_id": "openrouter/new-model", "provider_id": "openrouter", "location": "external", "tier": "middle", "cost_per_1m_tokens": 0.50}'
```

## 환경 변수 오버라이드

`.privacy-router.config.yaml`에서 `${VAR_NAME}` 또는 `${VAR_NAME:default}`로 환경 변수를 참조할 수 있습니다:

```yaml
models:
  - id: openrouter/${DEFAULT_MODEL:mistralai/ministral-3b-2512}
    location: external
    tier: small
```
