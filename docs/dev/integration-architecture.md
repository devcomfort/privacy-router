# Privacy Router — Integration Architecture

> **Date**: 2026-06-07  
> **Status**: Research Complete, Implementation Planned  
> **Scope**: Hermes Agent, OpenCode, LiteLLM, ACP, OpenResponses

---

## Executive Summary

The Privacy Router is a server-side pipeline (Extractor → Router → Masker → Hydrator) that exposes an **OpenAI-compatible `/v1/chat/completions` endpoint**. This architecture makes it universally integrable as a transparent proxy — any system that speaks the OpenAI protocol can route through it with a **config-only change**, zero code modifications.

### Integration Strategy Matrix

| Target System | Integration Method | Code Changes | Config Changes | Depth |
|---|---|---|---|---|
| **Hermes Agent** | Custom endpoint (`base_url`) | None | `~/.hermes/config.yaml` | Full pipeline transparent |
| **OpenCode** | Provider `baseURL` override | None | `opencode.json` | Full pipeline transparent |
| **LiteLLM** | Generic Guardrail API | New HTTP endpoint | `config.yaml` | Pre/post-call hooks |
| **ACP** | `providers/set` redirect | None | ACP client-side | Full pipeline transparent |
| **OpenResponses** | New `/v1/responses` endpoint | New route | Client config | Full pipeline + semantic events |

---

## 1. Hermes Agent Integration

**Source**: https://hermes-agent.nousresearch.com/docs/integrations/providers  
**Stars**: N/A (비공개) | **Language**: Python | **Protocol**: OpenAI Chat Completions

### 1.1 Integration Method: Custom Endpoint (Zero Code)

Hermes Agent supports any OpenAI-compatible endpoint via `provider: custom` in `config.yaml`:

```yaml
# ~/.hermes/config.yaml
model:
  provider: custom
  base_url: http://localhost:8787/v1
  api_key: "your-privacy-router-api-key"
  default: "openrouter/google/gemini-3.1-flash-lite"
```

Or interactively:
```bash
hermes model
# → Select "Custom endpoint (self-hosted / VLLM / etc.)"
# → URL: http://localhost:8787/v1
# → API key: <your-key>
# → Model: openrouter/google/gemini-3.1-flash-lite
```

### 1.2 How It Works

```
User → Hermes Agent → POST /v1/chat/completions → Privacy Router
                                                      ↓
                                                Extractor (SLM)
                                                      ↓
                                                Rule-based Router
                                                      ↓
                                                Masker/Hydrator
                                                      ↓
                                                External LLM (via litellm)
                                                      ↓
                                                Response + privacy_router metadata
```

Hermes sends standard OpenAI requests. Privacy Router intercepts, runs the full pipeline, and returns the response with `privacy_router` extension metadata.

### 1.3 MCP Integration (Complementary)

Privacy Router's FastMCP tools can also be registered as MCP servers in Hermes:

```yaml
# ~/.hermes/config.yaml (실제 사용 예)
mcp_servers:
  privacy-router:
    command: python
    args: ["server/mcp/lightweight.py"]
    env:
      PRIVACY_ROUTER_URL: "http://localhost:8787"
      PRIVACY_ROUTER_API_KEY: "your-key"
```
This gives Hermes direct access to the `process` tool for on-demand privacy analysis.

### 1.4 ACP Integration (Advanced)

Hermes supports ACP via `hermes acp`. An ACP client can redirect Hermes's LLM traffic:

```json
{
  "method": "providers/set",
  "params": {
    "id": "main",
    "apiType": "openai",
    "baseUrl": "http://localhost:8787/v1",
    "headers": {"Authorization": "Bearer <token>"}
  }
}
```

### 1.5 Named Custom Providers

For multiple privacy profiles (e.g., strict vs. lenient):

```yaml
# ~/.hermes/config.yaml
model:
  provider: custom:strict
  default: "openrouter/google/gemini-3.1-flash-lite"

providers:
  strict:
    base_url: http://localhost:8787/v1
    api_key: "strict-key"
  lenient:
    base_url: http://localhost:8788/v1
    api_key: "lenient-key"
```

Switch mid-session: `/model custom:lenient:gpt-4o`

---


## 2. OpenCode Integration

**Source**: https://opencode.ai/docs/providers  
**Stars**: N/A (비공개) | **Language**: TypeScript | **Protocol**: OpenAI Chat Completions / Responses

### 2.1 Integration Method: Provider baseURL Override (Zero Code)

OpenCode supports provider baseURL overrides in `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openai": {
      "options": {
        "baseURL": "http://localhost:8787/v1"
      }
    },
    "anthropic": {
      "options": {
        "baseURL": "http://localhost:8787/v1"
      }
    },
    "openrouter": {
      "options": {
        "baseURL": "http://localhost:8787/v1"
      }
    }
  }
}
```

### 2.2 Custom Provider via AI SDK

For full control, register a custom OpenAI-compatible provider:

```json
{
  "provider": {
    "privacy-router": {
      "type": "openai-compatible",
      "options": {
        "baseURL": "http://localhost:8787/v1",
        "apiKey": "your-key"
      },
      "models": {
        "masked-gpt-4o": {
          "name": "GPT-4o (Privacy Masked)",
          "contextWindow": 128000
        }
      }
    }
  }
}
```

### 2.3 OpenCode SDK (Programmatic)

OpenCode's JS SDK (`@opencode-ai/sdk`) can create sessions with custom providers:

```typescript
import { createOpencodeClient } from "@opencode-ai/sdk";

const client = createOpencodeClient({ baseUrl: "http://localhost:4096" });

// Create session with privacy-router model
const session = await client.session.create();
await client.session.prompt({
  sessionID: session.id,
  parts: [{ type: "text", text: "Analyze this code..." }],
  model: { providerID: "privacy-router", modelID: "masked-gpt-4o" }
});
```

### 2.4 ACP Integration

OpenCode is ACP-compatible. An ACP client can redirect its LLM traffic:

```json
{
  "method": "providers/set",
  "params": {
    "id": "main",
    "apiType": "openai",
    "baseUrl": "http://localhost:8787/v1",
    "headers": {"Authorization": "Bearer <token>"}
  }
}
```

---

## 3. LiteLLM Integration

**Source**: https://docs.litellm.ai/docs/proxy/call_hooks  
**Protocol**: OpenAI Chat Completions + Custom Hooks

### 3.1 Integration Strategy

LiteLLM has its own guardrails system. Privacy Router can integrate at three levels:

#### Level 1: Generic Guardrail API (Recommended)

Implement the LiteLLM Generic Guardrail API endpoint:

```python
# server/api/routes/litellm_guardrail.py
from fastapi import APIRouter, Request
from agents.router import PrivacyRouter

router = APIRouter()

@router.post("/api/v1/guardrail")
async def litellm_guardrail(request: Request):
    """LiteLLM Generic Guardrail API endpoint.
    
    Request format:
    {
        "texts": ["extracted text strings"],
        "structured_messages": [...],  # full OpenAI messages
        "input_type": "request" | "response",
        "request_data": {"user_api_key_hash": "..."}
    }
    
    Response format:
    {
        "decision": "NONE" | "BLOCKED" | "GUARDRAIL_INTERVENED",
        "modified_texts": [...]  # only if GUARDRAIL_INTERVENED
    }
    """
    body = await request.json()
    
    if body.get("input_type") == "response":
        return {"decision": "NONE"}  # Don't modify responses
    
    # Extract text from messages
    texts = body.get("texts", [])
    messages = body.get("structured_messages", [])
    
    pr = PrivacyRouter()
    
    for i, text in enumerate(texts):
        pipeline = pr.process(text)
        
        if pipeline.route.endpoint == "blocked":
            return {"decision": "BLOCKED"}
        
        if pipeline.route.requires_masking:
            # Mask the text
            from agents.masker import Masker
            masker = Masker()
            result = masker.mask(text, pipeline.records)
            texts[i] = result.masked_text
    
    if any(t != orig for t, orig in zip(texts, body.get("texts", []))):
        return {
            "decision": "GUARDRAIL_INTERVENED",
            "modified_texts": texts
        }
    
    return {"decision": "NONE"}
```

LiteLLM config:
```yaml
# litellm config.yaml
guardrails:
  - guardrail_name: privacy-router
    litellm_params:
      guardrail: generic_guardrail_api
      mode: pre_call
      api_base: http://localhost:8787/api/v1/guardrail
```

#### Level 2: Pre-Call Hook (Direct Integration)

```python
import litellm
from litellm.proxy.hooks.base import CustomGuardrail

class PrivacyRouterGuardrail(CustomGuardrail):
    async def async_pre_call_hook(self, data, user_api_key_dict, call_type):
        """Mask PII before LLM call."""
        from agents.router import PrivacyRouter
        pr = PrivacyRouter()
        
        for msg in data.get("messages", []):
            if msg.get("role") == "user":
                pipeline = pr.process(msg["content"])
                if pipeline.route.requires_masking:
                    from agents.masker import Masker
                    masker = Masker()
                    result = masker.mask(msg["content"], pipeline.records)
                    msg["content"] = result.masked_text
        
        return data

# Register
litellm.callbacks = [PrivacyRouterGuardrail()]
```

#### Level 3: ASGI Middleware (Low-Level)

```python
from starlette.middleware.base import BaseHTTPMiddleware

class PrivacyRouterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/v1/chat/completions":
            # Intercept, mask, forward
            ...
        return await call_next(request)
```

### 3.2 Recommendation

**Level 1 (Generic Guardrail API)** is recommended because:
- No litellm code changes needed
- Works via HTTP — Privacy Router runs as separate service
- Supports both pre_call and post_call modes
- Easy to test independently

---

## 4. ACP (Agent Client Protocol) Integration

**Source**: https://agentclientprotocol.com/  
**Spec**: v1 (JSON-RPC 2.0 over stdio)  
**Python SDK**: `pip install agent-client-protocol`

### 4.1 ACP Overview

ACP standardizes communication between AI coding agents and client applications. It's to coding agents what LSP is to language servers.

**Key insight**: ACP has a `providers/*` RFD (Request for Dialog) that allows clients to redirect agent LLM traffic to custom endpoints. This is the primary integration point.

### 4.2 Integration Path A: Provider Proxy (Zero Code)

Privacy Router's existing OpenAI-compatible endpoint works as an ACP `providers/set` target:

```json
// ACP client sends:
{
  "method": "providers/set",
  "params": {
    "id": "main",
    "apiType": "openai",
    "baseUrl": "http://localhost:8787/v1",
    "headers": {"Authorization": "Bearer <privacy-router-key>"}
  }
}
```

Any ACP agent (Hermes, OpenCode, OpenClaw, Claude, Copilot) that supports `providers/*` can be redirected.

### 4.3 Integration Path B: ACP Agent (Full Server)

Privacy Router could implement the full ACP agent interface using the Python SDK:

```python
# server/acp/agent.py
from acp.agent import Agent
from acp.schema import SessionPromptRequest, SessionUpdate

class PrivacyRouterAgent(Agent):
    """ACP agent that wraps Privacy Router pipeline."""
    
    async def initialize(self, request):
        return {
            "protocolVersion": 1,
            "agentInfo": {"name": "privacy-router", "version": "0.1.0"},
            "agentCapabilities": {
                "providers": {},
                "sessionCapabilities": {"close": True}
            }
        }
    
    async def session_prompt(self, request: SessionPromptRequest):
        # Extract text from request
        text = self._extract_text(request)
        
        # Run privacy pipeline
        from agents.router import PrivacyRouter
        pr = PrivacyRouter()
        pipeline = pr.process(text)
        
        # Stream back updates
        if pipeline.route.requires_masking:
            yield SessionUpdate(
                type="text",
                content="⚠️ Sensitive information detected and masked.\n\n"
            )
        
        # Forward to actual LLM and stream response
        ...
```

### 4.4 Integration Path C: MCP-over-ACP

Privacy Router's FastMCP tools can be injected into ACP sessions:

```python
# When an ACP session is created, inject privacy tools
async def on_session_new(session_id):
    # Register MCP tools via ACP mcp/connect
    await acp.mcp_connect(session_id, {
        "name": "privacy-router",
        "transport": "stdio",
        "command": ["python", "-m", "server.mcp"]
    })
```

### 4.5 ACP Auth Methods

ACP supports three auth methods:

1. **`env_var`**: Client provides `PRIVACY_ROUTER_API_KEY` when spawning agent
2. **`terminal`**: Agent opens TUI for API key entry
3. **`agent`**: Agent handles its own OAuth (for OAuth-protected Privacy Router instances)

### 4.6 Recommendation

**Path A (Provider Proxy)** is the immediate, zero-code win.  
**Path B (ACP Agent)** provides the richest integration but requires more work.  
**Path C (MCP-over-ACP)** is useful for injecting privacy tools into existing ACP sessions.

---

## 5. OpenResponses Integration

**Source**: https://www.openresponses.org/specification  
**Spec**: OpenResponses v1  
**Python SDK**: `pip install openresponses-types`

### 5.1 Overview

OpenResponses is a new response format that uses `POST /v1/responses` instead of `/v1/chat/completions`. Key differences:

| Aspect | OpenAI Chat Completions | OpenResponses |
|---|---|---|
| Endpoint | `/v1/chat/completions` | `/v1/responses` |
| Output | `choices[].message` | `output[]` Items |
| Content | Flat string | Typed content parts (`output_text`, `refusal`) |
| Streaming | `chat.completion.chunk` deltas | Semantic events (`response.output_text.delta`) |
| IDs | `chatcmpl-{uuid}` | `resp_{hex}` |
| Conversation | Client resends full history | `previous_response_id` |

### 5.2 Implementation: New `/v1/responses` Endpoint

```python
# server/api/routes/responses.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from agents.router import PrivacyRouter
from agents.masker import Masker
import json, uuid, time

router = APIRouter()

@router.post("/v1/responses")
async def create_response(request: Request):
    """OpenResponses-compatible endpoint with privacy pipeline."""
    body = await request.json()
    
    # Extract input text
    input_items = body.get("input", [])
    if isinstance(input_items, str):
        input_items = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": input_items}]}]
    
    # Run privacy pipeline on user messages
    pr = PrivacyRouter()
    masker = Masker()
    masked_items = []
    all_records = []
    contracts = []
    
    for item in input_items:
        if item.get("type") == "message" and item.get("role") == "user":
            for part in item.get("content", []):
                if part.get("type") == "input_text":
                    text = part["text"]
                    pipeline = pr.process(text)
                    
                    if pipeline.route.endpoint == "blocked":
                        return _error_response(403, "Content blocked by privacy policy")
                    
                    if pipeline.route.requires_masking:
                        result = masker.mask(text, pipeline.records)
                        part["text"] = result.masked_text
                        contracts.append(result.contract)
                        all_records.extend(pipeline.records)
            
        masked_items.append(item)
    
    # Forward to actual LLM (via adapter)
    # ... (similar to existing proxy.py logic)
    
    # Build OpenResponses response
    response_id = f"resp_{uuid.uuid4().hex}"
    
    return JSONResponse({
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "completed_at": int(time.time()),
        "status": "completed",
        "model": body.get("model", "unknown"),
        "input": masked_items,
        "output": [
            {
                "id": f"item_{uuid.uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "..."}],
                "status": "completed"
            }
        ],
        "metadata": {
            "privacy_router": {
                "is_sensitive": len(all_records) > 0,
                "records": [{"category": r.category, "span": r.span} for r in all_records],
                "policy_action": "masked" if contracts else "allow"
            }
        },
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
    })
```

### 5.3 Streaming (Semantic Events)

```python
async def _stream_response(body, pr, masker):
    """Stream OpenResponses semantic events."""
    response_id = f"resp_{uuid.uuid4().hex}"
    
    # response.created
    yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': response_id, 'status': 'in_progress'}})}\n\n"
    
    # response.output_item.added
    yield f"data: {json.dumps({'type': 'response.output_item.added', 'item': {'id': f'item_{uuid.uuid4().hex}', 'type': 'message', 'role': 'assistant', 'status': 'in_progress'}})}\n\n"
    
    # response.output_text.delta (stream from LLM)
    async for chunk in _stream_from_llm(body):
        yield f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': chunk})}\n\n"
    
    # response.completed
    yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': response_id, 'status': 'completed'}})}\n\n"
    
    yield "data: [DONE]\n\n"
```

---

## 6. Universal Integration Architecture

### 6.1 Architecture Diagram

**Privacy Router Server 내부 구성:**

| 계층 | 컴포넌트 | 엔드포인트/역할 |
|---|---|---|
| **진입점** | FastAPI | `/v1/chat/completions`, `/v1/responses` |
| | FastMCP | `process` (MCP 프로토콜) |
| | ACP Agent | Agent Client Protocol (선택적) |
| | LiteLLM Guardrail | `/api/v1/guardrail` |
| ↓ | | |
| **파이프라인** | Privacy Pipeline | Extractor → Router → Masker/Hydrator |
| ↓ | | |
| **어댑터** | LiteLLM Adapters | OpenRouter, OpenAI, Anthropic 등 |

**연동 에이전트:**

| 에이전트 | 연동 방식 | 설정 |
|---|---|---|
| **Hermes Agent** | `base_url` 변경 | `base_url: http://localhost:8787/v1` |
| **OpenClaw** | `baseUrl` 변경 | `baseUrl: http://localhost:8787/v1` |
| **OpenCode** | `baseURL` 변경 | `baseURL: http://localhost:8787/v1` |
| **LiteLLM** | Guardrail API | `/api/v1/guardrail` 엔드포인트 |
| **ACP Client** | `providers/set` | ACP 프로토콜을 통한 등록 |

### 6.2 Integration Priority

| Priority | Integration | Effort | Impact |
|---|---|---|---|
| P0 | Hermes custom endpoint | Zero code, config only | Immediate — 186k users |
| P0 | OpenClaw custom provider | Zero code, config only | Immediate — 377k users |
| P0 | OpenCode baseURL override | Zero code, config only | Immediate — 171k users |
| P1 | LiteLLM Generic Guardrail API | New HTTP endpoint | Broad — litellm ecosystem |
| P1 | ACP `providers/set` support | Zero code (already works) | Universal — all ACP agents |
| P2 | OpenResponses `/v1/responses` | New route + streaming | Future-proofing |
| P2 | ACP Agent (full server) | Python SDK integration | Richest UX |
| P3 | MCP-over-ACP bridge | ACP SDK integration | Tool injection |

### 6.3 OAuth / API Key Strategy

| Method | Use Case | Implementation |
|---|---|---|
| **API Key** | Direct HTTP clients | Existing Bearer token auth |
| **OAuth 2.1** | ACP agents with `agent` auth | Add OAuth provider to FastAPI |
| **Env Var** | ACP `env_var` auth method | Client passes `PRIVACY_ROUTER_API_KEY` |
| **LiteLLM Proxy** | Behind litellm proxy | Use litellm's key management |

---

## 7. Implementation Roadmap

### Phase 1: Zero-Config Integrations (Week 1)

1. **Document** config examples for Hermes, OpenClaw, OpenCode
2. **Test** end-to-end with each agent system
3. **Add** `/v1/models` endpoint improvements (model aliases, descriptions)

### Phase 2: LiteLLM Guardrail API (Week 2)

1. **Implement** `POST /api/v1/guardrail` endpoint
2. **Support** `pre_call` and `post_call` modes
3. **Handle** streaming responses in `post_call` mode
4. **Test** with litellm proxy

### Phase 3: OpenResponses (Week 3)

1. **Implement** `POST /v1/responses` endpoint
2. **Implement** streaming with semantic events
3. **Map** privacy metadata to `metadata` field
4. **Test** with OpenResponses clients

### Phase 4: ACP Agent (Week 4)

1. **Install** `agent-client-protocol` Python SDK
2. **Implement** ACP agent with `providers` capability
3. **Support** `providers/set` for dynamic LLM routing
4. **Test** with Zed, VS Code ACP extension

---

## 8. Key URLs

| Resource | URL |
|---|---|
| Hermes Agent Docs | https://hermes-agent.nousresearch.com/docs/ |
| Hermes Providers | https://hermes-agent.nousresearch.com/docs/integrations/providers |
| OpenClaw Docs | https://docs.openclaw.ai |
| OpenClaw Model Providers | https://docs.openclaw.ai/concepts/model-providers |
| OpenCode Docs | https://opencode.ai/docs |
| OpenCode Providers | https://opencode.ai/docs/providers |
| ACP Website | https://agentclientprotocol.com/ |
| ACP Spec | https://agentclientprotocol.com/protocol/v1/overview |
| ACP Providers RFD | https://agentclientprotocol.com/rfds/custom-llm-endpoint |
| ACP Python SDK | https://github.com/agentclientprotocol/python-sdk |
| OpenResponses Spec | https://www.openresponses.org/specification |
| OpenResponses Python SDK | https://github.com/mozilla-ai/openresponses-python |
| LiteLLM Guardrails | https://docs.litellm.ai/docs/proxy/guardrails |
| LiteLLM Hooks | https://docs.litellm.ai/docs/proxy/call_hooks |

---

*Last updated: 2026-06-07*
