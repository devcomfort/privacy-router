# Model Context Protocol (MCP)

Privacy Router는 [Model Context Protocol](https://modelcontextprotocol.io/) 서버로도 동작합니다. 에이전트가 MCP를 통해 직접 프라이버시 파이프라인에 접근할 수 있습니다.

## MCP란?

MCP는 AI 에이전트와 도구를 연결하는 표준 프로토콜입니다. 에이전트 호스트(Claude Desktop, Hermes Agent 등)가 MCP 서버를 통해 도구를 호출할 수 있습니다.

## Privacy Router MCP 도구

`server/mcp/tools.py`에 정의된 단일 통합 도구:

### `process`

```python
def process(
    text: str,
    action: str = "auto",
    model: str | None = None,
) -> dict
```

| 파라미터 | 설명 |
|---|---|
| `text` | 처리할 프롬프트 텍스트 |
| `action` | `auto` (기본): 전체 파이프라인 자동 결정 / `classify`: 탐지만 / `generate`: 강제 LLM 호출 / `allow`: 프라이버시 검사 건너뜀 |
| `model` | 생성 모델 오버라이드 |

반환값:

```json
{
    "action_taken": "generated",
    "content": "LLM 응답 텍스트",
    "extraction_records": [{"category": "...", "span": "<sensitive-value>", "confidence": 0.95, "is_essential": false}],
    "policy_action": "selective_mask",
    "is_sensitive": true,
    "requires_masking": true,
    "model_used": "openrouter/mistralai/ministral-3b-2512",
    "latency_ms": 1234.5
}
```

## 통합 방법

### Hermes Agent

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  privacy-router:
    command: python
    args: ["-m", "server.mcp"]
    env:
      PRIVACY_ROUTER_URL: "http://localhost:8787"
```

### Claude Desktop

```json
{
  "mcpServers": {
    "privacy-router": {
      "command": "python",
      "args": ["-m", "server.mcp"],
      "env": {
        "OPENROUTER_API_KEY": "<openrouter-api-key>"
      }
    }
  }
}
```

### OpenAI 호환 API (대안)

MCP 대신 OpenAI 호환 엔드포인트를 사용할 수도 있습니다:

```bash
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer pr-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{"model": "...", "messages": [...]}'
```

이 경우 Privacy Router가 프록시로 동작하여 자동으로 파이프라인을 실행합니다.
