# Getting Started

## Prerequisites

- Python 3.13+
- Docker, Docker Compose, and the NVIDIA Container Toolkit for the default local model
- At least 64 GB of available accelerator or unified memory for Gemma 4 26B
- An OpenRouter key only when deployment may route to OpenRouter

## Quick Start

```bash
git clone https://github.com/devcomfort/privacy-router.git
cd privacy-router
cp .env.example .env
python -m pip install -e .
```

Start the loopback-only, keyless browser demo. The first command downloads and serves Gemma 4 26B; run the second command in another terminal:

```bash
./scripts/start_vllm.sh gemma4
privacy-router dev
```

For deployment, set `PRIVACY_ROUTER_MASTER_KEY`, `PRIVACY_ROUTER_ADMIN_PASSWORD`, and provider environment variables in `.env`, then run `docker compose up -d`.

## Docker Compose Profiles

Compose `profiles` enable optional services:

| Profile | Services | Purpose |
|---|---|---|
| _(none)_ | db, api | Core deployment |
| `hermes` | hermes | Hermes Agent demo |

### Behavior

- Services without a profile always start with `docker compose up`.
- Services with a profile start only when that profile is enabled.
- Profiles can be combined when the selected Compose files define them.

### Usage

```bash
# Core deployment
docker compose up

# Include Hermes Agent
COMPOSE_PROFILES=hermes docker compose up -d

# Persist the profile choice
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

Management APIs and `/admin` exchange `PRIVACY_ROUTER_ADMIN_PASSWORD` for a short-lived secure session. State-changing requests additionally require the session's CSRF token. Provider credentials remain server environment variables and are read-only in the UI.

Docker Compose publishes the API, database, and Hermes ports on `127.0.0.1` by default. It sets `PRIVACY_ROUTER_ALLOW_INSECURE_ADMIN=1` only for this loopback-published HTTP setup so `/admin` works through Docker's bridge. If `PRIVACY_ROUTER_BIND_HOST` is changed from loopback, set the override to `0` and terminate HTTPS before the API.

**API Proxy mode** is best when you want zero-friction privacy protection — every request is automatically classified, masked if needed, and routed. **MCP Tool mode** is best when the agent needs fine-grained control over when and how to apply privacy protection (e.g., classify first, then decide whether to mask).

## Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Landing | http://localhost:8787/ | Portal (EN/KO) |
| Demo Chat | http://localhost:8787/demo | Interactive chat with privacy pipeline |
| Admin | http://localhost:8787/admin | Model, API key, and redacted telemetry management |
| Product Docs | http://localhost:8787/docs | User and developer documentation |
| Hermes Dashboard | http://localhost:9119 | Hermes Agent web UI |
| API Docs | http://localhost:8787/api/docs | OpenAPI Swagger UI |

## Create a Client API Key

Open http://localhost:8787/admin, enter the administrator password, and use **Create Key**. The returned `pr-...` key is shown once. For the cookie-and-CSRF API flow, see [API Key Management](/docs/api-keys).

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
python -m pip install -e .
cp .env.example .env
./scripts/start_vllm.sh gemma4
# In another terminal:
privacy-router dev
# → http://localhost:8787
```

## Stopping

```bash
docker compose down
```
