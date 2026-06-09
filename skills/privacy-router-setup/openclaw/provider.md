---
name: openclaw-privacy-router
description: Configure OpenClaw to use Privacy Router as custom LLM provider and MCP server.
---

# OpenClaw + Privacy Router 설정

OpenClaw에서 Privacy Router를 사용하는 방법을 안내합니다.

## 1. Custom Provider 설정

OpenClaw가 Privacy Router를 LLM 프록시로 사용하도록 설정합니다.

**설정 파일:** `~/.openclaw/openclaw.json`

```json5
{
  "models": {
    "mode": "merge",
    "providers": {
      "privacy-router": {
        "baseUrl": "http://localhost:8787/v1",
        "apiKey": "pr-YOUR-API-KEY",
        "api": "openai-completions",
        "models": [
          {
            "id": "openrouter/google/gemini-3.1-flash-lite",
            "name": "Privacy Router (Gemini Flash Lite)",
            "reasoning": false,
            "input": ["text"],
            "contextWindow": 1048576,
            "maxTokens": 32000
          },
          {
            "id": "openrouter/mistralai/ministral-3b-2512",
            "name": "Privacy Router (Ministral 3B)",
            "reasoning": false,
            "input": ["text"],
            "contextWindow": 32768,
            "maxTokens": 4096
          }
        ]
      }
    }
  }
}
```

**참조:** [OpenClaw Custom Providers 문서](https://docs.openclaw.ai/gateway/config-tools)

## 2. MCP 서버 연결

OpenClaw에서 MCP 서버를 연결하여 도구를 사용할 수 있습니다. Privacy Router 외에도 다양한 MCP 서버를 연결할 수 있습니다.

### MCP 서버 찾기

- [Smithery](https://smithery.ai/) — MCP 서버 레지스트리
- [mcp.run](https://mcp.run/) — 호스팅 MCP 서버
- [GitHub: awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) — 커뮤니티 MCP 서버 목록

### stdio 방식 (로컬 실행)

```json5
{
  "mcp": {
    "servers": {
      "서버이름": {
        "command": "실행 명령어",
        "args": ["인자1", "인자2"],
        "env": { "KEY": "value" }
      }
    }
  }
}
```

### HTTP 방식 (원격 서버)

```json5
{
  "mcp": {
    "servers": {
      "서버이름": {
        "url": "http://localhost:3000/mcp",
        "transport": "streamable-http",
        "headers": { "Authorization": "Bearer ..." }
      }
    }
  }
}
```

### CLI로 등록

```bash
# 등록
openclaw mcp set 서버이름 \
  --command python \
  --args '["-m", "server.mcp"]'

# 확인
openclaw mcp list
openclaw mcp show 서버이름

# 제거
openclaw mcp unset 서버이름
```

### Privacy Router MCP 연결

Privacy Router를 MCP로 사용하는 방법은 [README.md](../../README.md)의 "MCP 서버" 섹션을 참조하세요.

**참조:** [OpenClaw MCP 설정](https://docs.openclaw.ai/gateway/configuration-reference)

## 3. Channel 연동

OpenClaw는 다양한 채널을 지원합니다. Privacy Router를 사용하면 모든 채널의 메시지가 자동으로 프라이버시 파이프라인을 거칩니다.

**지원 채널:**
- WhatsApp, Telegram, Discord, Slack, Signal
- iMessage, Google Chat, Microsoft Teams
- IRC, Matrix, WebChat, Feishu, LINE
- Mattermost, Nostr, Twitch, WeChat, QQ

**설정 예시 (Slack):**
```json5
{
  "channels": {
    "slack": {
      "enabled": true,
      "dmPolicy": "allowlist",
      "allowedUsers": ["user-id-1", "user-id-2"]
    }
  }
}
```

**참조:** [OpenClaw Channels 문서](https://docs.openclaw.ai/channels)

## 4. Privacy Router API 키 생성

```bash
curl -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "openclaw", "provider_id": "openrouter"}'
```

응답에서 `api_key`를 복사하여 OpenClaw 설정에 사용합니다.

## 5. 테스트

```bash
# OpenClaw에서 Privacy Router를 통해 LLM 호출
openclaw chat "주민등록번호 901212-1234567을 확인해주세요"
# → Privacy Router가 자동으로 마스킹 후 LLM 호출
```

## 전체 설정 파일 예시

```json5
{
  "models": {
    "mode": "merge",
    "providers": {
      "privacy-router": {
        "baseUrl": "http://localhost:8787/v1",
        "apiKey": "pr-YOUR-API-KEY",
        "api": "openai-completions",
        "models": [
          {
            "id": "openrouter/google/gemini-3.1-flash-lite",
            "name": "Privacy Router (Gemini Flash Lite)",
            "reasoning": false,
            "input": ["text"],
            "contextWindow": 1048576,
            "maxTokens": 32000
          }
        ]
      }
    }
  },
  "mcp": {
    "servers": {
      "privacy-router": {
        "command": "python",
        "args": ["-m", "server.mcp"],
        "env": {
          "OPENROUTER_API_KEY": "sk-or-v1-..."
        }
      }
    }
  },
  "channels": {
    "slack": {
      "enabled": true,
      "dmPolicy": "allowlist"
    }
  }
}
```
