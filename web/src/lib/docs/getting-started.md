# Getting Started

## Prerequisites

- Docker & Docker Compose
- OpenRouter API key (get from https://openrouter.ai)

## Quick Start

```bash
git clone https://github.com/privacy-router/privacy-router.git
cd privacy-router
cp .env.example .env
# Edit .env - set OPENROUTER_API_KEY and PRIVACY_ROUTER_ADMIN_KEY

docker compose up -d
```

This starts two services:
- `db` — PostgreSQL (port 5433)
- `api` — Privacy Router API (port 8787)

## Docker Compose Profiles

Docker Compose의 `profiles`는 서비스를 선택적으로 활성화하는 메커니즘입니다.

| 프로파일 | 포함 서비스 | 용도 |
|---|---|---|
| _(없음)_ | db, api | 핵심 기능 — 항상 실행 |
| `hermes` | hermes | Hermes Agent 데모 |

### 동작 원리

- `profiles`가 없는 서비스 → **항상** `docker compose up`에 포함
- `profiles`가 있는 서비스 → 해당 프로파일이 활성화될 때만 포함
- 여러 프로파일 조합 가능: `COMPOSE_PROFILES=hermes,gpu`

### 사용법

```bash
# 최소 모드 (db + api만)
docker compose up

# Hermes Agent 포함
COMPOSE_PROFILES=hermes docker compose up -d

# .env에 설정
echo "COMPOSE_PROFILES=hermes" >> .env
docker compose up
```

## Hermes Agent Demo Modes

The Hermes Agent container supports three Privacy Router integration modes via `HERMES_CONFIG`:

| Config | Mode | How it works |
|--------|------|-------------|
| `config-api.yaml` | API Proxy | All LLM calls automatically pass through Privacy Router. Transparent — no agent action needed. |
| `config-mcp.yaml` | MCP Tool | LLM calls go directly to the model. Agent calls `privacy-router.process()` explicitly when needed. |
| `config-privacy-router.yaml` | Combined | API proxy + MCP tools available simultaneously (default). |

```bash
# API Proxy mode — automatic protection
HERMES_CONFIG=api docker compose up -d hermes

# MCP Tool mode — explicit protection
HERMES_CONFIG=mcp docker compose up -d hermes

# Combined mode (default)
docker compose up -d hermes
```

Management APIs and the `/admin` UI require the `PRIVACY_ROUTER_ADMIN_KEY` value through the `X-Privacy-Router-Admin-Key` header. The admin key is separate from the generated `pr-...` client key used for inference.

**API Proxy mode** is best when you want zero-friction privacy protection — every request is automatically classified, masked if needed, and routed. **MCP Tool mode** is best when the agent needs fine-grained control over when and how to apply privacy protection (e.g., classify first, then decide whether to mask).

## Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Landing | http://localhost:8787/ | Portal (EN/KO) |
| Demo Chat | http://localhost:8787/demo | Interactive chat with privacy pipeline |
| Admin | http://localhost:8787/admin | API key and settings management |
| Dashboard | http://localhost:8787/usage-dashboard.html | Usage log visualization |
| Hermes Dashboard | http://localhost:9119 | Hermes Agent web UI |
| API Docs | http://localhost:8787/docs | OpenAPI Swagger UI |

## Create an API Key

```bash
# Via Admin UI: http://localhost:8787/admin
# Or via API:
curl -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -H "X-Privacy-Router-Admin-Key: <admin-key>" \
  -d '{"name": "my-key"}'
# → Save the returned api_key (starts with "pr-", shown only once)
```

## Conversation Context

Both OpenAI-compatible endpoints accept either a complete conversation snapshot or a latest-turn delta:

- `POST /v1/chat/completions`
- `POST /v1/responses`

Send the same `X-Chat-ID` header on related requests to retain encrypted context. Complete-snapshot retries are deduplicated; delta turns are appended; current singleton fields such as `instructions` and tool definitions replace prior values. Concurrent requests merge atomically instead of overwriting one another. The cache key is scoped to the authenticated API key, so the same client conversation ID cannot join two tenants. Omit the header for stateless requests. The ID must contain 1–512 UTF-8 bytes.

Responses requests accept function tools. Unsupported tool types return `400` before a provider call. Privacy metadata contains only current-request extraction records and never includes internal extractor reasoning or prior-only values.

### Sensitive Tool-Call Arguments

Function-call arguments keep `SENSITIVE_DATA#<8 hex>` placeholders by default, in both streaming and non-streaming responses. For local-model routes, Privacy Router parses completed argument JSON strictly, rejects duplicate keys and non-finite numbers, and inspects decoded string values immediately before delivery. It masks sensitive plaintext in those values. Permit plaintext sensitive values only when the downstream tool is trusted and the request explicitly opts in:

```json
{
  "tools": [],
  "privacy_router": {
    "allow_sensitive_tool_arguments": true
  }
}
```

This extension applies to both `/v1/chat/completions` and `/v1/responses`. Only the JSON boolean `true` enables plaintext tool arguments; an omitted field or any other type keeps them masked. Opt-in changes release, not inspection: every local tool call is still analyzed before delivery. It releases both hydrated values derived from input placeholders and sensitive values newly generated by the local model, across every function call in the response. The option is request-scoped, not a per-tool allowlist. Default masking preserves the JSON structure. A parse, inspection, or masking failure blocks the response. Because an unrequested tool call can appear after ordinary content, local-model streaming responses hold all generated content until completion and release it only after every argument object passes inspection.


## Local Development

```bash
# Python 3.13+, uv or pip
pip install -e .
cp .env.example .env
python -m server
# → http://localhost:8787
```

## Stopping

```bash
docker compose down
```
