# Privacy Router

**Privacy-first Model Router for Universal Agent Runtime.**

An on-device middleware that intercepts agent-generated prompts before they reach external LLM APIs, detects sensitive information through contextual reasoning, and routes each request based on information sensitivity — not model complexity.

> *Term Project for **Generative AI and Blockchain 2026** at **GIST** (Gwangju Institute of Science and Technology), supervised by **Professor Heung-No Lee**.*
>
> **Team:** DH. Kim & M. Saadati · **Type:** Privacy-Preserving AI Service

---

## Why Privacy Router?

AI agents send everything to the cloud. Your prompts contain PII, unpublished research, business decisions — but the agent doesn't know what's sensitive. Existing solutions (OpenAI Privacy Filter) focus on English/US data. They miss Korean RRN, +82 phone numbers, and contextual secrets.

Privacy Router sits between your agent and the LLM API. It detects, masks, and routes — so sensitive data stays local while safe queries get full cloud quality.

```
Agent → [Privacy Router] → External LLM (safe queries only)
                ↓
         Local LLM (sensitive queries)
```

---

## Quick Start

### 1. Start the Server

```bash
git clone https://github.com/privacy-router/privacy-router.git
cd privacy-router
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY=sk-or-v1-...

docker compose up -d
```

This starts:
- **API** on `http://localhost:8787`
- **PostgreSQL** on port 5433
- **Hermes Agent** on port 7860
- **Hermes Dashboard** on `http://localhost:9119`

### 2. Create an API Key

Open the **Admin Dashboard**: http://localhost:8787/admin

1. Click **"Create Key"**
2. Enter a name (e.g., `my-app`)
3. Copy the generated key (starts with `pr-`, shown only once)

Or via API:

```bash
curl -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app"}'
```

### 3. Configure Your Agent

Set these values in your agent's LLM configuration:

| Setting | Value |
|---------|-------|
| **API Base URL** | `http://localhost:8787/v1` |
| **API Key** | `pr-xxxxxxxxxxxx` (your key from step 2) |
| **Model** | `openrouter/mistralai/ministral-3b-2512` (or any supported model) |

The proxy is **OpenAI-compatible** — just change `base_url`. No code changes needed.

### 4. Test It

```bash
export API_KEY="pr-xxxxxxxxxxxx"

# Safe prompt → passes through unchanged
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter/mistralai/ministral-3b-2512",
    "messages": [{"role": "user", "content": "What is the capital of France?"}]
  }'
# → privacy_router.is_sensitive: false

# Sensitive prompt → masked and forwarded
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter/mistralai/ministral-3b-2512",
    "messages": [{"role": "user", "content": "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘"}]
  }'
# → privacy_router.is_sensitive: true
# → policy_action: mask_and_send
# → extraction_records: [{category: "RESIDENT_REGISTRATION_NUMBER", span: "901212-1234567"}]
```

### 5. Try with Hermes Agent

```bash
# Run a task through Hermes (routes through Privacy Router automatically)
docker exec privacy-router-hermes-1 hermes -z "안녕하세요" --accept-hooks

# Sensitive prompt — Privacy Router will mask PII
docker exec privacy-router-hermes-1 hermes -z \
  "주민등록번호 901212-1234567을 조회해줘" --accept-hooks
```

---

## How It Works

### Pipeline: Extractor → Judge → Router

```
User Prompt
    ↓
┌─────────────────────────────────────────────────────────────┐
│  Extractor (facade, precision="default"|"high")             │
│  ├── ExtractorCore: Socratic sensitivity detection          │
│  └── Critic: post-review (precision="high"일 때만)            │
│  → Free-form SCREAMING_CASE tags                            │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Judge (rule-based, no LLM call)                            │
│  is_essential 플래그로 정책 결정                                │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
              ┌────────────┼────────────┐
              ↓            ↓            ↓
         External API  Local API      Block
         (masked)      (full prompt)  (risk)
              ↓
         Hydration: restore original values in response
```

### Policy Decisions

| Condition | Action | Description |
|-----------|--------|-------------|
| Not sensitive | `route_to_external` | Pass through unchanged |
| Sensitive, maskable | `mask_and_send` | Mask spans, send externally, hydrate response |
| Sensitive, essential | `route_to_local` | Process entirely on-device |
| Cannot decide | `ask_to_user` | Ask user to confirm (HTTP 409) |
| High risk | `block` | Block request entirely |

### Key Concepts

- **Socratic Categories:** The SLM generates free-form `SCREAMING_CASE` tags through contextual reasoning — not from a hardcoded list.
- **Masking & Hydration:** Sensitive spans become `TAG#hash` placeholders. The cloud LLM never sees originals. Responses are hydrated before returning.
- **`is_essential`:** If masking would destroy the meaning of the request, the system routes to a local LLM instead.

---

## Detection Examples

### Contextual Detection (Our Strength)

The Extractor doesn't rely on keywords. It understands *meaning*:

**Input:** "삼성전자 차세대 AP 개발 건으로, TSMC 3nm 공정을 채택하기로 내부적으로 결정했다."

```json
[
  {"category": "COMPANY_PROJECT_NAME", "span": "삼성전자 차세대 AP 개발 건", "confidence": 0.91},
  {"category": "FABRICATION_PROCESS_DECISION", "span": "TSMC 3nm 공정을 채택하기로", "confidence": 0.94},
  {"category": "INTERNAL_BUSINESS_DECISION", "span": "내부적으로 결정", "confidence": 0.92}
]
```

No keyword like "secret" or "confidential" appears — but the system understands this is a business secret.

### PII Detection

**Input:** "주민등록번호 901212-1234567과 연락처 010-1234-5678을 기재합니다."

```json
[
  {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "901212-1234567", "confidence": 0.98, "is_essential": false},
  {"category": "MOBILE_PHONE_NUMBER", "span": "010-1234-5678", "confidence": 0.95, "is_essential": false}
]
```

### Research Secrets

**Input:** "Attention 메커니즘을 완전히 대체할 수 있는 새로운 아이디어를 구상 중이다."

```json
[
  {"category": "NOVEL_ATTENTION_ALTERNATIVE", "span": "Attention 메커니즘을 완전히 대체할 수 있는 새로운 아이디어", "confidence": 0.91}
]
```

---

## Access Points

| URL | Description |
|-----|-------------|
| http://localhost:8787/ | Landing page (EN/KO) |
| http://localhost:8787/admin | API key management |
| http://localhost:8787/demo | Interactive chat demo |
| http://localhost:8787/documentation | SvelteKit documentation |
| http://localhost:8787/usage-dashboard.html | Usage log visualization |
| http://localhost:9119 | Hermes Agent dashboard |
| http://localhost:8787/docs | OpenAPI Swagger UI |

---

## 7-Day Usage Log

46 real API calls through Hermes Agent. 67.4% contained sensitive information.

| Date | Total | Sensitive | Safe | Local | Masked |
|------|------:|----------:|-----:|------:|-------:|
| 2026-06-17 | 46 | 31 | 15 | 9 | 22 |

**Key finding:** Two-thirds of agent-generated prompts contain sensitive information that would leak to external APIs without Privacy Router.

Full logs: [`usage-log/USAGE_LOG.md`](usage-log/USAGE_LOG.md) · [`usage-log/db-logs.json`](usage-log/db-logs.json)

---

## Architecture

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + SQLModel |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Models | Ministral 3B / Gemma4 E4B (Extractor), Rule-based (Judge) |
| Frontend | SvelteKit (SSG) |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256) |
| Integration | OpenAI Compatible API + MCP Server |

Detailed architecture: [`docs/architecture.md`](docs/architecture.md)

---

## Cost

| Metric | Value |
|--------|------:|
| Monthly cost | ~$0.075/user |
| Daily requests | 50 |
| Avg prompt | 500 tokens |
| Avg response | 1,000 tokens |

**Two-tier routing:** Non-sensitive queries → cloud (cheap SLM). Sensitive queries → local. No quality trade-off for privacy.

---

## Docs

| Document | Description |
|----------|-------------|
| [`docs/getting-started.md`](docs/getting-started.md) | Installation, configuration, first API call |
| [`docs/architecture.md`](docs/architecture.md) | Pipeline, components, tech stack |
| [`docs/detection.md`](docs/detection.md) | Detection examples with real API responses |


---

## Testing

이 프로젝트는 **2개의 test suite**로 구성됩니다. 각각 다른 목적으로 설계되었습니다.

### Suite 1: Unit Tests (`agents/*/tests/`)

**목적**: 코드 구조와 로직 검증 (mock 기반)

```bash
python3 -m pytest agents/extractor/tests/ agents/judge/tests/ agents/router/tests/ -v
```

| 검증 대상 | 방식 | 예시 |
|-----------|------|------|
| 파이프라인 구조 | mock | Extractor → Judge → Router 경로 |
| 검증 로직 | deterministic | SCREAMING_CASE, confidence ≥ 0.5 |
| 마스킹/수화 | mock LLM 호출 | span → placeholder → 복원 |
| 정책 결정 | deterministic | is_essential → policy_action |
| 에러 처리 | mock exception | LLM 실패 시 fallback |

- **실행 시점**: 매 commit, CI
- **소요 시간**: ~30초
- **결정론적**: ✅ (같은 결과 보장)

### Suite 2: Eval Suite (`scripts/eval_runner.py`)

**목적**: LLM 출력 품질 검증 (실제 LLM 호출)

```bash
# 단일 모델, 5 trials
python3 scripts/eval_runner.py --model gemma4-e4b-vllm --trials 5

# 전체 보고서
python3 scripts/eval_runner.py --report
```

| 검증 대상 | 방식 | 지표 |
|-----------|------|------|
| 민감도 탐지 | N≥5 trials | Sensitivity Accuracy |
| 정책 결정 | N≥5 trials | Action Accuracy |
| 형태적 기밀사항 | 패턴 기반 케이스 | PII, 전화번호, 이메일 |
| 맥락적 기밀사항 | 맥락 기반 케이스 | 사업비밀, 연구아이디어 |
| JSON 출력 | N≥5 trials | JSON Validity |
| 통계적 유의성 | paired t-test | p < 0.05 |

- **실행 시점**: 모델 변경, 튜닝, 프롬프트 수정 시
- **소요 시간**: 수 분 ~ 수십 분
- **비결정론적**: ⚠️ (LLM에 따라 변동)

### 왜 분리되어 있는가?

```
Unit tests (mock)           Eval suite (real LLM)
  → "코드가 맞는가?"           → "LLM이 맞는가?"
  → 빠르고 안정적              → 느리지만 현실적
  → 매 commit 실행             → 모델/튜닝 변경 시 실행
  → 코드 버그 탐지             → LLM 품질 측정
```

mock 없이 LLM에 의존하면 테스트 실패 시 "코드 버그 vs LLM 변동"을 구분할 수 없습니다.
---

## Repository Structure

```
privacy-router/
├── agents/                  # Extractor, Judge, Router, Masker
├── server/                  # FastAPI server + MCP tools
├── db/                      # SQLModel database layer
├── web/                     # SvelteKit frontend (SSG)
├── slides/                  # HTML presentations + PDF/PPTX
├── paper/                   # TeX research paper
├── usage-log/               # Real usage logs (46 entries)
├── docs/                    # Documentation
├── hermes-agent/            # Hermes demo configs (API / MCP / combined)
├── docker-compose.yml       # Core + Hermes agent
├── .env.example             # Environment template
└── README.md                # This file
```

---

## Contact

- **DH. Kim** — dearkimdh@gm.gist.ac.kr
- **M. Saadati** — mohammadsaadati@gm.gist.ac.kr
- **Supervisor:** Prof. Heung-No Lee, GIST
- **Course:** Generative AI and Blockchain 2026

---

## License

MIT
