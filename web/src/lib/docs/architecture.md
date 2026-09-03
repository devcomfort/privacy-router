# 아키텍처

## 파이프라인

Privacy Router는 디바이스 위에서 동작하는 **Extractor → Judge → Router** 파이프라인으로, 외부 LLM API에 도달하기 전에 에이전트가 생성한 모든 프롬프트를 가로챕니다.

```
Agent Prompt
    ↓
┌─────────────────────────────────────────────────────────────┐
│  Extractor (facade, precision="default"|"high")             │
│  ├── ExtractorCore: Socratic sensitivity detection          │
│  │   → Free-form SCREAMING_CASE categories                  │
│  │   → Minimal entity spans (exclude particles/adverbs)     │
│  │   → is_essential flag (masking feasibility)               │
│  └── Critic: post-review (precision="high" only)            │
│      → Catches spans Phase 1 missed                         │
│      → Runs even on empty texts                             │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Query aggregation + Judge (rule-based, no LLM calls)       │
│  Canonical policy decision:                                 │
│    → not sensitive:              allow                      │
│    → all spans non-essential:    selective_mask             │
│    → essential span / no safe span: block                   │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
                   ┌───────┴───────┐
                   ↓               ↓
              External API    Local API
              (raw/masked)     (block)
                   ↓
              Hydration for masked responses
```

![Privacy Router 소비자 보호 흐름: 안전한 프롬프트는 원문 그대로 외부 모델로 전달되고, 마스킹 가능한 프롬프트는 플레이스홀더로 나가서 로컬에서 복원되며, 필수적이거나 안전한 스팬이 없는 프롬프트는 로컬에 남습니다.](/diagrams/privacy-router-consumer-flow.svg)

## 런타임 모델 바인딩

파이프라인에는 이름 붙은 컴포넌트마다 하나의 모델이 있는 것이 아니라, 모델에 바인딩된 세 가지 역할이 있습니다.

| 런타임 역할 | 현재 모델 | 신뢰 경계 | 사용처 |
|---|---|---|---|
| Decision Model | Gemma 4 26B (`openai/google/gemma-4-26b-local`) | 로컬 전용 | ExtractorCore와 선택적 고정밀 Critic. 민감도, 스팬, 카테고리, `is_essential`을 반환 |
| Local Model | Gemma 4 26B (동일 엔드포인트) | 로컬 전용 | 필수 민감 원문 프롬프트 생성 |
| External Model | OpenRouter Gemma 4 26B (`openrouter/google/gemma-4-26b-a4b-it`) | 외부 | 비민감 프롬프트 또는 검증된 마스킹 프롬프트 생성 |

`Judge`는 규칙 기반 정책 코드이고 `Router`는 결정론적 실행 코드이므로 둘 다 LLM 바인딩이 없습니다. Extractor, Critic, Judge는 유용한 컴포넌트 이름으로 남지만, 독립적으로 선택 가능한 모델 역할은 아닙니다.


## 컴포넌트 아키텍처

```
Extractor (facade)
  ├── ExtractorCore  — Socratic extraction (always runs)
  │   └── extract.prompt / extract.short.prompt
  └── Critic         — post-review (precision="high" only)
      └── critic.prompt

Judge (rule-based) — injected by Router
  └── classify.prompt (reference only, not used)

Router — policy → execution path mapping
```

## Middle-Man 아키텍처

Middle-Man Agent이 파이프라인을 조율하고 사용자 상호작용을 관리합니다.

```
agents/router/
├── middle_man.py      # Middle-Man Agent (decision logic)
├── cache.py           # SQLite KV cache
├── router.py          # Router (policy → execution path)
└── schemas.py         # Schema definitions
```

### 결정 흐름

```python
def process_with_middle_man(text, metadata):
    # 1. Extract (with cache check)
    extraction = extract_with_cache(text, metadata.cache_strategy)

    # 2. Middle-Man decision
    if not extraction.is_sensitive:
        return auto_process(text, extraction)

    if metadata.auto_mask:
        if all_confident(extraction, metadata.masking_threshold):
            return auto_process(text, extraction)
        else:
            return ask_user(text, extraction)
    else:
        return ask_user(text, extraction)
```

### 캐시 전략

| 전략 | 설명 | DB 작업 |
|----------|-------------|--------------|
| `auto` | 기본값. HIT → 사용, MISS → 실행 후 저장 | SELECT / INSERT |
| `bypass` | 항상 재실행, 저장 없음 | (none) |
| `refresh` | 재실행 후 캐시 덮어쓰기 | UPSERT |
| `delete` | 삭제 후 재실행, 저장 없음 | DELETE |

캐시는 **추출 결과만** 저장합니다(LLM 응답 아님).
캐시 키: 입력 텍스트의 청크 단위 MD5 해시(4KB 청크 → 병렬 해시 → 결합 → 재해시).

## 응답 형식

### 케이스 1: 자동 처리(기본)

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
  "privacy_router": {
    "status": "completed",
    "is_sensitive": true,
    "extraction_records": [...],
    "policy_action": "selective_mask",
    "masking_applied": true,
    "cached": false
  }
}
```

### 케이스 2: 사용자 입력 필요

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": null}, "finish_reason": "requires_action"}],
  "privacy_router": {
    "status": "needs_input",
    "question": "Sensitive data detected. How should it be handled?",
    "extraction_summary": {
      "is_sensitive": true,
      "record_count": 2,
      "essential_count": 1,
      "extraction_records": [
        {"index": 0, "category": "UNPUBLISHED_RESEARCH_CONCEPT", "span": "<research-concept>", "is_essential": true, "confidence": 0.95},
        {"index": 1, "category": "INTERNAL_PROJECT_NAME", "span": "<internal-project-name>", "is_essential": false, "confidence": 0.90}
      ],
      "default_action": "block"
    },
    "options": [
      {"id": "auto", "label": "Auto", "description": "Follow system decision"},
      {"id": "mask_all", "label": "Mask all", "description": "Mask all sensitive data"},
      {"id": "mask_essential", "label": "Mask essential only", "description": "Mask is_essential=true only"},
      {"id": "block", "label": "Local processing", "description": "Use local model instead of external API"},
      {"id": "custom", "label": "Custom", "description": "Per-record selection"}
    ],
    "default_option": "auto"
  }
}
```

### 케이스 3: 사용자 선택 → 재요청

```json
{
  "model": "privacy-router",
  "messages": [
    {"role": "user", "content": "Original text..."},
    {"role": "assistant", "content": null, "privacy_router": {"status": "needs_input", ...}},
    {"role": "user", "content": null, "privacy_router": {
      "selected_option": "custom",
      "overrides": [
        {"record_index": 0, "is_essential": true},
        {"record_index": 2, "remove": true}
      ]
    }}
  ]
}
```

## API 대 MCP

| 측면 | API(OpenAI 호환) | MCP 서버 |
|--------|------------------------|------------|
| 진입점 | `server/api/routes/proxy.py` | `server/mcp/tools.py` |
| 호출자 | 외부 클라이언트 | AI 에이전트 |
| Middle-Man | 파이프라인 내부 자동 실행 | 에이전트가 `review()` / `decide()`를 직접 호출 |
| 사용자 문의 | `status: needs_input` 응답 → 클라이언트가 사용자에게 질문 | 에이전트가 사용자에게 직접 질문 |
| 상태 | 무상태(클라이언트가 컨텍스트 관리) | 무상태(에이전트가 컨텍스트 관리) |
| 캐시 | `cache_strategy` 메타데이터 | `no_cache` 플래그 |

## API

```python
# Default mode (fast, 1 LLM call)
extractor = Extractor()
result = extractor.extract("Please review <personal-id>")

# High-precision mode (with Critic, 2 LLM calls)
extractor = Extractor(precision="high")
result = extractor.extract("Please review <personal-id>")

# Dependency injection (for testing)
extractor = Extractor(core=my_core, critic=my_critic)
```

## 탐지 영역

### 패턴 기반(형태적)
PII, 전화번호, 이메일, 실명 — 패턴으로 탐지 가능.
- 정확도: 83.3% (Gemma4 E4B)

### 맥락 기반(맥락적)
기업 비밀, 연구 아이디어, 전략, 예산, 내부 URL — 맥락 이해가 필요.
- 정확도: 62.5% (Gemma4 E4B)

## 프롬프트

| 파일 | 위치 | 용도 |
|------|----------|---------|
| `extractor.prompt` | `agents/extractor/extract.prompt` | 기본 추출(소크라테스식, 298줄) |
| `extractor.short.prompt` | `agents/extractor/extract.short.prompt` | 2B 이하 모델(24줄) |
| `extractor.socratic.prompt` | `agents/extractor/extract.socratic.prompt` | 소크라테스식 CoT(131줄) |
| `extractor.fixed.prompt` | `agents/extractor/extract.fixed.prompt` | 고정 카테고리(232줄) |
| `critic.prompt` | `agents/extractor/critic.prompt` | 2차 비평(92줄) |
| `judge.prompt` | `agents/judge/classify.prompt` | 분류/정책(참고 전용) |

## 모델 선택

```
Model size   → Prompt
─────────────────────────────
≤ 2B         → extract.short.prompt
3B ~ 4B      → extract.prompt (default)
> 4B         → extract.prompt or extract.socratic.prompt
```

## 컴포넌트

| 컴포넌트 | 파일 | 설명 |
|-----------|------|-------------|
| Extractor | `agents/extractor/extractor.py` | 파사드(precision, DI 지원) |
| ExtractorCore | `agents/extractor/extractor_core.py` | 소크라테스식 추출 로직 |
| Critic | `agents/extractor/critic.py` | 사후 비평(독립 실행) |
| Judge | `agents/judge/judge.py` | 규칙 기반 정책 결정 |
| Router | `agents/router/router.py` | 파이프라인 오케스트레이션 |
| MiddleMan | `agents/router/middle_man.py` | 사용자 상호작용 오케스트레이터 |
| Masker | `agents/masker/masker.py` | span → 플레이스홀더 치환 |
| Cache | `agents/router/cache.py` | chat_id 기반 상태 관리 |

## 기술 스택

| 계층 | 기술 |
|-------|-----------|
| 백엔드 | FastAPI + SQLModel |
| 데이터베이스 | SQLite(개발) / PostgreSQL(운영) |
| 모델 | 로컬·외부 모델 항목을 담은 SQLite 기반 레지스트리 |
| 프론트엔드 | SvelteKit(SSG) |
| 암호화 | Fernet(AES-128-CBC + HMAC-SHA256) |
| 통합 | OpenAI 호환 API + MCP 서버 |

## 테스트

두 개의 테스트 스위트:

### 단위 테스트(mock 기반)

- **위치**: `tests/core/`, `tests/sanity/`, `server/tests/`
- **목적**: 코드 구조와 로직 검증
- **방식**: `@patch`로 LLM 호출을 mock
- **대상**: 파이프라인 경로, 검증 로직, 마스킹/하이드레이션, 정책 결정, 오류 처리
- **실행**: `python3 -m pytest tests/core/ tests/sanity/ server/tests/ -v`
- **소요 시간**: 약 30초

### 평가 스위트(실제 LLM 호출)

- **위치**: `scripts/eval_runner.py`, `scripts/eval_all.py`
- **목적**: LLM 출력 품질 검증
- **방식**: 실제 LLM 호출로 N≥5 시행
- **대상**: 민감도 탐지율, 정책 결정 정확도, 패턴/맥락 탐지, JSON 출력
- **실행**: `python3 scripts/eval_runner.py --model gemma4-e4b-openrouter --trials 5`
- **소요 시간**: 수 분~수십 분

### 왜 분리하는가?

mock이 없으면 테스트 실패가 "코드 버그"인지 "LLM 변동"인지 구분할 수 없습니다.

## 관련 문서

- [탐지](/docs/detection) — 소크라테스식 민감도 탐지 프레임워크
- [쿼리 집계](/docs/query-aggregation) — 스팬 증거, 쿼리 단위 결정 변수, fail-closed 라우팅 불변 조건
- [보안](/docs/security) — threat model과 암호화
- [마스킹과 하이드레이션](/docs/masking) — 마스킹·하이드레이션 상세
- [API 키](/docs/api-keys) — 키 관리
