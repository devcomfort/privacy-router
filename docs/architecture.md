# Architecture

## Pipeline

Privacy Router is an on-device **Extractor → Judge → Router** pipeline that intercepts every agent-generated prompt before it reaches an external LLM API.

```
Agent Prompt
    ↓
┌─────────────────────────────────────────────────────────────┐
│  Extractor (facade, precision="default"|"high")             │
│  ├── ExtractorCore: Socratic sensitivity detection          │
│  │   → Free-form SCREAMING_CASE categories                  │
│  │   → Minimal entity spans (조사/부사 제외)                   │
│  │   → is_essential 플래그 (마스킹 가능 여부)                    │
│  └── Critic: post-review (precision="high"일 때만)            │
│      → Phase 1이 놓친 span 탐지                               │
│      → 비어있는 텍스트에서도 실행                                │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Judge (규칙 기반, LLM 미사용)                                 │
│  is_essential 플래그로 정책 결정:                                │
│    → is_essential > 0: route_to_local / prompt_user           │
│    → all maskable:     mask_and_send                          │
│    → not sensitive:    route_to_external                      │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
              ┌────────────┼────────────┐
              ↓            ↓            ↓
         External API  Local API      Block
         (masked)      (full prompt)  (risk)
              ↓
         Hydration: restore original values in response
```

## Component Architecture

```
Extractor (퍼사드)
  ├── ExtractorCore  — Socratic 추출 (항상 실행)
  │   └── extract.prompt / extract.short.prompt
  └── Critic         — 사후 검증 (precision="high"일 때만)
      └── critic.prompt

Judge (규칙 기반) — Router에서 주입
  └── classify.prompt (참고용, 미사용)

Router — 정책 → 실행 경로 변환
```

## API

```python
# 기본 모드 (빠름, 1회 LLM 호출)
extractor = Extractor()
result = extractor.extract("주민등록번호 901212-1234567")

# 고정밀 모드 (Critic 포함, 2회 LLM 호출)
extractor = Extractor(precision="high")
result = extractor.extract("주민등록번호 901212-1234567")

# 의존성 주입 (테스트용)
extractor = Extractor(core=my_core, critic=my_critic)
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
| `judge.prompt` | `agents/judge/classify.prompt` | 분류/정책 결정 (참고용) |

## Model Selection

```
모델 크기    → 프롬프트 선택
─────────────────────────────
≤ 2B        → extract.short.prompt
3B ~ 4B     → extract.prompt (기본)
> 4B        → extract.prompt 또는 extract.socratic.prompt
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| Extractor | `agents/extractor/extractor.py` | 퍼사드 (precision, DI 지원) |
| ExtractorCore | `agents/extractor/extractor_core.py` | Socratic 추출 로직 |
| Critic | `agents/extractor/critic.py` | 사후 검증 (독립 컴포넌트) |
| Judge | `agents/judge/judge.py` | 규칙 기반 정책 결정 |
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
