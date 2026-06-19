# Architecture

## Pipeline

Privacy Router is an on-device **Extractor → Judge → Router** pipeline that intercepts every agent-generated prompt before it reaches an external LLM API.

```
Agent Prompt
    ↓
┌─────────────────────────────────────────────────────────────┐
│  Extractor (SLM: 1.2B ~ 4B)                                │
│  Phase 1: Socratic sensitivity detection                    │
│    → Free-form SCREAMING_CASE categories                    │
│    → Minimal entity spans (조사/부사 제외)                    │
│    → is_essential 플래그 (마스킹 가능 여부)                     │
│  Phase 2: Critic review (선택적)                              │
│    → 놓친 span 탐지                                          │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Judge (Rule-based)                                         │
│  Single-Axis Masking Test:                                  │
│    "이 span을 [MASKED]로 치환하면 질의 의미가 유지되는가?"       │
│  → is_essential=true:  route_to_local / prompt_user          │
│  → is_essential=false: mask_and_send                         │
│  → not sensitive:      route_to_external                     │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
              ┌────────────┼────────────┐
              ↓            ↓            ↓
         External API  Local API      Block
         (masked)      (full prompt)  (risk)
              ↓
         Hydration: restore original values in response
```

## Detection Surfaces

### 형태적 기밀사항 (Pattern-Based)
PII, 전화번호, 이메일, 실명 등 — 패턴으로 감지 가능
- 정확도: 83.3% (Gemma4 E4B 기준)

### 맥락적 기밀사항 (Context-Based)
사업비밀, 연구아이디어, 전략, 예산, 내부URL 등 — 맥락 이해 필요
- 정확도: 62.5% (Gemma4 E4B 기준)

## Prompts

| 파일 | 위치 | 용도 |
|------|------|------|
| `extractor.prompt` | `agents/extractor/extract.prompt` | 기본 추출 (Socratic, 298 lines) |
| `extractor.short.prompt` | `agents/extractor/extract.short.prompt` | ≤2B 모델용 (24 lines) |
| `extractor.socratic.prompt` | `agents/extractor/extract.socratic.prompt` | Socratic CoT (131 lines) |
| `extractor.fixed.prompt` | `agents/extractor/extract.fixed.prompt` | 고정 카테고리 (232 lines) |
| `critic.prompt` | `agents/extractor/critic.prompt` | 2단계 비판 (92 lines) |
| `judge.prompt` | `agents/judge/classify.prompt` | 분류/정책 결정 (108 lines) |

백업: `agents/prompts/` 및 `eval/prompts/`

## Model Selection

```
모델 크기    → 프롬프트 선택
─────────────────────────────
≤ 2B        → extractor.short.prompt
3B ~ 4B     → extractor.prompt (기본)
> 4B        → extractor.prompt 또는 extractor.socratic.prompt
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| Extractor | `agents/extractor/extractor.py` | SLM 기반 민감 정보 추출 |
| Two-Phase | `agents/extractor/two_phase.py` | Phase 1 + Critic |
| Judge | `agents/judge/judge.py` | 마스킹 테스트 기반 정책 결정 |
| Router | `agents/router/router.py` | 파이프라인 오케스트레이션 |
| Masker | `agents/masker/masker.py` | span → placeholder 치환 |
| Cache | `agents/router/cache.py` | chat_id 기반 상태 관리 |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLModel |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Models | Ministral 3B, Gemma4 E4B, EXAONE 1.2B |
| Frontend | SvelteKit (SSG) |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256) |
| Integration | OpenAI Compatible API + MCP Server |
