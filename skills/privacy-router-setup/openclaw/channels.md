---
name: openclaw-channels
description: Configure OpenClaw channels (Slack, Discord, Telegram, Email) with Privacy Router.
---

# OpenClaw 채널 설정

OpenClaw에서 Slack, Discord, Telegram, Email 채널을 Privacy Router와 연동하는 방법을 안내합니다.

**참조:** [OpenClaw Channels 문서](https://docs.openclaw.ai/channels)

## 공통 설정

모든 채널은 `~/.openclaw/openclaw.json`의 `channels` 섹션에서 설정합니다. Privacy Router를 custom provider로 등록하면, 모든 채널의 메시지가 자동으로 프라이버시 파이프라인을 거칩니다.

```json5
{
  // Custom provider (Privacy Router) — 모든 채널에서 공통 사용
  "models": {
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

  // 채널 설정
  "channels": { ... }
}
```

## 1. Slack

**필요 정보:**
- Slack Bot Token (`xoxb-...`)
- Slack App Token (`xapp-...`) — Socket Mode용

**Slack 앱 생성:**
1. [api.slack.com/apps](https://api.slack.com/apps)에서 새 앱 생성
2. Bot Token Scopes: `chat:write`, `channels:history`, `im:history`, `im:write`
3. Socket Mode 활성화 → App Token 생성
4. Event Subscriptions: `message.im`, `message.channels`

**설정:**

```json5
{
  "channels": {
    "slack": {
      "enabled": true,
      "token": "xoxb-YOUR-BOT-TOKEN",
      "appToken": "xapp-YOUR-APP-TOKEN",
      "dmPolicy": "allowlist",
      "allowedUsers": ["U0123456789", "U9876543210"]
    }
  }
}
```

| 필드 | 설명 |
|---|---|
| `token` | Slack Bot User OAuth Token |
| `appToken` | Slack App-Level Token (Socket Mode) |
| `dmPolicy` | `pairing` (1:1 페어링) / `allowlist` (허용 사용자) / `open` (전체) / `disabled` |
| `allowedUsers` | `dmPolicy: "allowlist"`일 때 허용할 Slack User ID 목록 |

**참조:** [OpenClaw Slack 설정](https://docs.openclaw.ai/channels/slack)

## 2. Discord

**필요 정보:**
- Discord Bot Token

**Discord 봇 생성:**
1. [discord.com/developers/applications](https://discord.com/developers/applications)에서 앱 생성
2. Bot 섹션에서 Token 복사
3. Privileged Gateway Intents: `Message Content Intent` 활성화
4. OAuth2 → URL Generator에서 `bot` 스코프 선택 → 초대

**설정:**

```json5
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR-DISCORD-BOT-TOKEN",
      "dmPolicy": "allowlist",
      "allowedUsers": ["discord-user-id-1", "discord-user-id-2"]
    }
  }
}
```

| 필드 | 설명 |
|---|---|
| `token` | Discord Bot Token |
| `dmPolicy` | `pairing` / `allowlist` / `open` / `disabled` |

**참조:** [OpenClaw Discord 설정](https://docs.openclaw.ai/channels/discord)

## 3. Telegram

**필요 정보:**
- Telegram Bot Token (BotFather에서 생성)

**Telegram 봇 생성:**
1. Telegram에서 [@BotFather](https://t.me/BotFather)에게 `/newbot` 전송
2. 봇 이름 설정 → Token 받기
3. `/setprivacy` → `Disable` (그룹 메시지 수신 가능)

**설정:**

```json5
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR-TELEGRAM-BOT-TOKEN",
      "dmPolicy": "allowlist",
      "allowedUsers": [123456789, 987654321]
    }
  }
}
```

| 필드 | 설명 |
|---|---|
| `token` | Telegram Bot Token (BotFather에서 발급) |
| `dmPolicy` | `pairing` / `allowlist` / `open` / `disabled` |
| `allowedUsers` | Telegram User ID (숫자) |

**참조:** [OpenClaw Telegram 설정](https://docs.openclaw.ai/channels/telegram)

## 4. Email

**필요 정보:**
- IMAP 서버 정보 (수신)
- SMTP 서버 정보 (발신)

**설정:**

```json5
{
  "channels": {
    "email": {
      "enabled": true,
      "imap": {
        "host": "imap.gmail.com",
        "port": 993,
        "secure": true,
        "user": "your-email@gmail.com",
        "password": "your-app-password"
      },
      "smtp": {
        "host": "smtp.gmail.com",
        "port": 465,
        "secure": true,
        "user": "your-email@gmail.com",
        "password": "your-app-password"
      },
      "dmPolicy": "allowlist",
      "allowedAddresses": ["user1@example.com", "user2@example.com"]
    }
  }
}
```

| 필드 | 설명 |
|---|---|
| `imap.host` | IMAP 서버 주소 |
| `imap.port` | IMAP 포트 (보통 993) |
| `smtp.host` | SMTP 서버 주소 |
| `smtp.port` | SMTP 포트 (보통 465) |
| `dmPolicy` | `allowlist` / `open` / `disabled` |
| `allowedAddresses` | 허용할 이메일 주소 목록 |

**Gmail 설정:**
1. Google 계정 → 보안 → 2단계 인증 활성화
2. 앱 비밀번호 생성 → `password`에 사용

**참조:** [OpenClaw Email 설정](https://docs.openclaw.ai/channels/email)

## 전체 설정 예시

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
        "env": { "OPENROUTER_API_KEY": "sk-or-v1-..." }
      }
    }
  },
  "channels": {
    "slack": {
      "enabled": true,
      "token": "xoxb-...",
      "appToken": "xapp-...",
      "dmPolicy": "allowlist",
      "allowedUsers": ["U0123456789"]
    },
    "discord": {
      "enabled": true,
      "token": "YOUR-DISCORD-TOKEN",
      "dmPolicy": "allowlist",
      "allowedUsers": ["discord-user-id"]
    },
    "telegram": {
      "enabled": true,
      "token": "YOUR-TELEGRAM-TOKEN",
      "dmPolicy": "allowlist",
      "allowedUsers": [123456789]
    },
    "email": {
      "enabled": true,
      "imap": { "host": "imap.gmail.com", "port": 993, "secure": true, "user": "...", "password": "..." },
      "smtp": { "host": "smtp.gmail.com", "port": 465, "secure": true, "user": "...", "password": "..." },
      "dmPolicy": "allowlist",
      "allowedAddresses": ["user@example.com"]
    }
  }
}
```

## Privacy Router API 키 생성

```bash
curl -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "openclaw", "provider_id": "openrouter"}'
```

응답의 `api_key`를 설정 파일의 `apiKey`에 사용합니다.
