# Privacy Router

**Privacy-First Model Router for LLM Agent Runtime**

> Term Project — Generative AI and Blockchain 2026, GIST (Gwangju Institute of Science and Technology)
> Supervisor: Prof. Heung-No Lee

---

## Team

| Field | Value |
|---|---|
| Team name | DH. Kim & M. Saadati |
| Members | 김동현 (donghyeon@gist.ac.kr), Mohammad Saadati (mohammadsaadati@gm.gist.ac.kr) |
| Repository | https://github.com/devcomfort/privacy-router |

## Project Type

**Primary:** Privacy-Preserving AI Service
**Secondary:** Cost-Efficient AI Stack

---

## Problem Statement & Target User

LLM agents send every user prompt to external cloud APIs. These prompts routinely contain:

- **PII:** 주민등록번호, phone numbers, email addresses, medical records
- **Business secrets:** internal decisions, project codenames, financial figures, M&A plans
- **Research secrets:** unpublished ideas, experimental results, novel architectures

Existing solutions are inadequate:
- **OpenAI Content Filter / Microsoft Presidio:** keyword/regex-based, English-centric — miss Korean RRN (901212-1234567), +82 phone numbers, and contextual secrets
- **On-device models:** lose cloud LLM quality for every query, even safe ones
- **Manual review:** impossible at agent speed (sub-second decisions needed)

**Privacy Router** is a transparent proxy middleware that intercepts agent prompts, classifies sensitivity through contextual reasoning (not keywords), masks sensitive spans, and routes each request — keeping sensitive data local while safe queries get full cloud quality.

```
Agent → [Privacy Router] → External LLM (safe queries, masked)
                ↓
         Local LLM (sensitive queries, full prompt)
```

### Target Users

- Developers building LLM-powered applications with compliance requirements
- Enterprises deploying AI agents that process confidential internal data
- Individual users who want control over what data leaves their device

---

## Installation & Execution

### Quick Start (Docker)

```bash
git clone https://github.com/devcomfort/privacy-router.git
cd privacy-router/code
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY=sk-or-v1-...

docker compose up -d
```

This starts:

| Port | Service |
|------|---------|
| 8787 | Privacy Router API + Admin Dashboard |
| 9119 | Hermes Agent Dashboard |
| 5433 | PostgreSQL |

### Create an API Key

```bash
curl -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app"}'
# Returns: pr-xxxxxxxxxxxx
```

### Configure Your Agent

The proxy is **OpenAI-compatible** — just change `base_url`. No code changes needed.

| Setting | Value |
|---------|-------|
| API Base URL | `http://localhost:8787/v1` |
| API Key | `pr-xxxxxxxxxxxx` |
| Model | `openrouter/mistralai/ministral-3b-2512` (or any supported model) |

### Test

```bash
export API_KEY="pr-xxxxxxxxxxxx"

# Safe prompt — passes through unchanged
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"openrouter/mistralai/ministral-3b-2512",
       "messages":[{"role":"user","content":"What is the capital of France?"}]}'
# → is_sensitive: false, action: route_to_external

# Sensitive prompt — masked and forwarded
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"openrouter/mistralai/ministral-3b-2512",
       "messages":[{"role":"user","content":"주민등록번호 901212-1234567을 포함한 이메일을 작성해줘"}]}'
# → is_sensitive: true, action: mask_and_send
# → extraction: RESIDENT_REGISTRATION_NUMBER "901212-1234567"
```

### Try with Hermes Agent

```bash
docker exec privacy-router-hermes-1 hermes -z "안녕하세요" --accept-hooks
docker exec privacy-router-hermes-1 hermes -z \
  "주민등록번호 901212-1234567을 조회해줘" --accept-hooks
```

---

## How It Works: Extractor → Judge → Router

```
User Prompt
    ↓
┌──────────────────────────────────────────────────────────┐
│  Extractor (SLM: Ministral 3B)                           │
│  Phase 1: Contextual detection via Socratic categories   │
│  Phase 2: Critic review — catches what Phase 1 missed    │
│  → Free-form SCREAMING_CASE tags                         │
└────────────────────────┬─────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────────────────┐
│  Judge (Single-Axis Masking Test)                        │
│  "If I replace every sensitive span with [REDACTED],     │
│   does the user's request still make sense?"             │
│  Verb heuristic: Creation / Consultation / Interrogation │
└────────────────────────┬─────────────────────────────────┘
                         ↓
              ┌──────────┼──────────┐
              ↓          ↓          ↓
         External API  Local API   Block
         (masked)      (full)      (risk)
              ↓
         Hydration: restore values in response
```

| Condition | Action | Description |
|-----------|--------|-------------|
| Not sensitive | `route_to_external` | Pass through unchanged |
| Sensitive, maskable | `mask_and_send` | Mask spans → external → hydrate response |
| Sensitive, essential | `route_to_local` | Process entirely on-device |
| Cannot decide | `ask_to_user` | Ask user to confirm (HTTP 409) |
| High risk | `block` | Block request entirely |

### Key Concepts

- **Socratic Categories:** The SLM generates free-form `SCREAMING_CASE` tags through contextual reasoning — not from a hardcoded list. It detects business secrets, research ideas, and PII without keyword matching.
- **Masking & Hydration:** Sensitive spans become `TAG#hash` placeholders. The cloud LLM never sees originals. Responses are hydrated before returning to the user.
- **`is_essential`:** If masking would destroy the meaning of the request, the system routes to a local LLM instead of cloud.

---

## Differentiation vs Big-Tech Assistants

| Dimension | Big Tech (OpenAI, Google) | Privacy Router |
|-----------|--------------------------|----------------|
| **PII Detection** | None — user responsibility | Automatic extraction + classification via SLM reasoning |
| **Contextual Secrets** | Not detected | Socratic category detection (business secrets, research ideas, internal decisions) |
| **Data Masking** | Not available | Hash-based masking with deterministic session hydration |
| **Routing Control** | All data → cloud | Configurable local/external split based on sensitivity classification |
| **Transparency** | Black box | Full pipeline visibility in admin UI (extraction records, policy decisions, routing) |
| **Korean Data** | Minimal | Built for Korean RRN, +82 phone, Korean-contextual business data |
| **Integration** | Direct API only | OpenAI-compatible proxy — drop-in, zero code changes |
| **Agent Awareness** | No agent context | Sliding-window session memory for multi-turn masking coherence |

**Three concrete advantages:**

1. **Contextual, not keyword-based:** Detects "삼성전자 차세대 AP 개발 건으로 TSMC 3nm 공정을 채택하기로 내부적으로 결정했다" as a business secret — no keyword like "secret" or "confidential" appears.
2. **Cost-preserving privacy:** Two-tier routing sends only sensitive queries to local models. 67% of real agent prompts are sensitive, but only 20% need local processing (the rest are maskable).
3. **Zero-friction integration:** Any OpenAI-compatible agent works by changing one URL. No SDK, no code changes, no vendor lock-in.

---

## 7-Day Usage Log

46 real API calls through Hermes Agent during live demo sessions (2026-06-17).

| Metric | Value |
|--------|-------|
| Total requests | 46 |
| Sensitive requests | 31 (67.4%) |
| Safe requests | 15 (32.6%) |
| Routed to external API (masked) | 22 (47.8%) |
| Routed to local processing | 9 (19.6%) |
| Routed to external API (safe) | 15 (32.6%) |
| Average sensitive records/request | 6.1 |
| Error rate | 0% |

**Key finding:** Two-thirds of agent-generated prompts contain sensitive information that would leak to external APIs without Privacy Router. Of the sensitive prompts, 71% are maskable (safe to send externally after redaction), and 29% require local processing.

Full logs: [`usage-log/USAGE_LOG.md`](usage-log/USAGE_LOG.md) · [`usage-log/db-logs.json`](usage-log/db-logs.json)

---

## Cost Estimate & Local/Cloud Stack

### Monthly Cost Estimate

| Metric | Value |
|--------|------:|
| Monthly cost per user | ~$0.19 |
| Daily requests | 50 |
| Avg prompt | 500 tokens |
| Avg response | 1,000 tokens |
| Sensitive ratio | 67% (measured) |

### Two-Tier Routing Cost Model

- **Non-sensitive queries (33%)** → cloud SLM (Gemini Flash Lite, ~$0.075/1M input tokens)
- **Sensitive + maskable (47%)** → cloud SLM after masking (~$0.075/1M)
- **Sensitive + essential (20%)** → local model (Qwen3-4B on vLLM, zero marginal cost with GPU)

| Component | Where | Model | Cost |
|-----------|-------|-------|------|
| Extractor | Cloud | Ministral 3B (OpenRouter) | ~$0.10/1M tokens |
| Judge | Cloud | Gemma 4 26B (OpenRouter) | ~$0.10/1M tokens |
| Generator (safe) | Cloud | Gemini Flash Lite | ~$0.075/1M tokens |
| Generator (sensitive) | Local | Qwen3-4B (vLLM) | $0 (self-hosted) |

**Net effect:** Users get cloud-quality responses for 80% of queries while keeping sensitive data local. The marginal cost of privacy is ~$0.02/user/month (Extractor + Judge overhead).

### I = M × HBM × R (Technical Rigour)

For the local inference path:

| Parameter | Value |
|-----------|-------|
| M (model size) | Qwen3-4B, ~2.4B active params (INT4) |
| HBM (memory bandwidth) | ~900 GB/s (RTX 4090) |
| R (arithmetic intensity) | ~50 FLOPs/param/token |
| **Throughput** | **~45 tokens/sec** (single user) |

This is sufficient for real-time chat latency (<1s TTFT) on the local path.

---

## Privacy & Security Summary

### Threat Model

| Threat | Mitigation |
|--------|-----------|
| PII leakage to cloud LLM | Automatic extraction + hash-based masking before external API call |
| Business secret exposure | Contextual Socratic detection — no keyword dependency |
| Masking reversal by cloud LLM | `TAG#hash` placeholders are session-scoped, non-reversible |
| Man-in-the-middle on API calls | HTTPS for all external connections; local traffic on localhost |
| Database credential exposure | Fernet encryption (AES-128-CBC + HMAC-SHA256) for stored API keys |
| Multi-turn context leakage | Sliding-window session memory keeps masking decisions consistent |

### Data Flow

```
User → Privacy Router (localhost:8787)
         ├─ Extract: SLM identifies sensitive spans
         ├─ Judge: decides mask / local / block
         ├─ Mask: replace spans with TAG#hash
         ├─ Route: external (masked) or local (full)
         └─ Hydrate: restore originals in response → User
```

- **No user prompts are stored** — only usage metadata (timestamp, sensitivity, action, record count)
- **Masking is deterministic** — same input produces same hash within a session, enabling multi-turn coherence
- **Local-first architecture** — sensitive data never leaves the device for essential queries

---

## Smartening: Two-Phase Extraction with Critic

We implemented **two-phase extraction** (Week 11 smartening: self-reflection / critic pattern):

| Metric | Single-pass | Two-phase (with Critic) |
|--------|------------|------------------------|
| Multi-span miss rate | ~15% | ~3% |
| Business secrets detection | 0% | 100% |
| Research secrets detection | 0% | 100% |
| Inference cost overhead | 1x | ~1.3x (same SLM, second pass) |

**Phase 1 (Extract):** The SLM applies contextual reasoning to detect sensitive spans with free-form `SCREAMING_CASE` category tags.

**Phase 2 (Critic):** A second SLM pass reviews Phase 1 output, catches missed spans, and verifies `is_essential` classification. This eliminates single-pass blind spots on multi-span inputs.

Additionally, **hallucination filtering** in the merge step verifies that each detected span actually exists in the original text — spans that don't match verbatim are discarded.

Detailed analysis: [`code/docs/developments/REPORT.md`](code/docs/developments/REPORT.md)

---

## Architecture

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + SQLModel |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Extractor | Ministral 3B via OpenRouter |
| Judge | Gemma 4 26B via OpenRouter |
| Generator (cloud) | Gemini Flash Lite via OpenRouter |
| Generator (local) | Qwen3-4B via vLLM |
| Frontend | SvelteKit (SSG) |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256) |
| Integration | OpenAI-compatible API + MCP Server |

---

## Demo Video

**YouTube:** https://youtu.be/tX8oVv5DlAs (5 minutes)

Demonstrates: real-time PII detection, business secret classification, masking/routing decisions, and admin dashboard visibility through Hermes Agent.

---

## Paper & Slides

| Document | Path |
|----------|------|
| Report (English) | [`paper/report_en.pdf`](paper/report_en.pdf) |
| Report (Korean) | [`paper/report_ko.pdf`](paper/report_ko.pdf) |
| Slides (English) | [`slides/presentation_en.pdf`](slides/presentation_en.pdf) |
| Slides (Korean) | [`slides/presentation_kr.pdf`](slides/presentation_kr.pdf) |
| Architecture diagrams | [`slides/diagrams/`](slides/diagrams/) |

---

## Repository Structure

```
privacy-router/
├── README.md              ← This file
├── code/                  ← Source code
│   ├── agents/            # Extractor, Judge, Router, Masker, Memory
│   ├── server/            # FastAPI server + MCP tools
│   ├── db/                # SQLModel database layer
│   ├── web/               # SvelteKit frontend (SSG)
│   ├── tests/             # Unit + scenario tests
│   ├── docker-compose.yml # Core + Hermes agent
│   └── ...
├── paper/                 # TeX research paper + PDF
├── slides/                # HTML presentations + PDF/PPTX + diagrams
├── usage-log/             # Real usage logs (46 entries)
└── demo-video/            # Demo video placeholder
```

---

## Access Points

| URL | Description |
|-----|-------------|
| http://localhost:8787/ | Landing page (EN/KO) |
| http://localhost:8787/admin | API key management dashboard |
| http://localhost:8787/demo | Interactive chat demo |
| http://localhost:8787/documentation | SvelteKit documentation site |
| http://localhost:8787/docs | OpenAPI Swagger UI |
| http://localhost:9119 | Hermes Agent dashboard |

---

## Contact

- **DH. Kim** — donghyeon@gist.ac.kr
- **M. Saadati** — mohammadsaadati@gm.gist.ac.kr
- **Supervisor:** Prof. Heung-No Lee, GIST
- **Course:** Generative AI and Blockchain 2026
