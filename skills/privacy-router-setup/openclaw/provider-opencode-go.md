---
name: openclaw-opencode-go
description: Configure OpenClaw to use OpenCode Go subscription as a model provider.
---

# OpenClaw + OpenCode Go 설정

OpenClaw에서 OpenCode Go 구독을 모델 프로바이더로 사용하는 방법을 안내합니다.

## OpenCode Go란?

OpenCode Go는 OpenCode의 Go 구독 요금제입니다. 오픈소스 코딩 모델에 대한 넉넉한 한도와 안정적인 액세스를 제공합니다.

- **가격:** 첫 달 $5, 이후 $10/월
- **필요:** `OPENCODE_API_KEY`
- **페이지:** https://opencode.ai/ko/go

**포함 모델:** GLM-5.1, Kimi K2.5/K2.6, MiMo-V2.5-Pro, Qwen3.7 Max, MiniMax M2.7/M3, DeepSeek V4 Pro/Flash

## 방법 1: Privacy Router 경유 (프라이버시 파이프라인 포함)

모든 요청이 Privacy Router를 통과하여 민감 정보 자동 탐지/마스킹을 수행합니다.

```json5
{
  "providers": {
    "privacy-router": {
      "baseUrl": "http://localhost:8787/v1",
      "apiKey": "pr-YOUR-API-KEY",
      "api": "openai-completions",
      "models": [
        {
          "id": "opencode-go/kimi-k2.6",
          "name": "Privacy Router (Kimi K2.6 via OpenCode Go)",
          "contextWindow": 131072,
          "maxTokens": 4096
        }
      ]
    }
  }
}
```

## 방법 2: 직접 연결 (프라이버시 파이프라인 없음)

```bash
openclaw onboard --auth-choice opencode-go
openclaw config set agents.defaults.model.primary "opencode-go/kimi-k2.6"
openclaw models list --provider opencode-go
```

**설정 파일:** `~/.openclaw/openclaw.json`

```json5
{
  "env": { "OPENCODE_API_KEY": "YOUR_API_KEY" },
  "agents": {
    "defaults": {
      "model": { "primary": "opencode-go/kimi-k2.6" }
    }
  }
}
```

## 포함 모델 목록

| 모델 참조 | 이름 |
|---|---|
| `opencode-go/glm-5` | GLM-5 |
| `opencode-go/glm-5.1` | GLM-5.1 |
| `opencode-go/kimi-k2.5` | Kimi K2.5 |
| `opencode-go/kimi-k2.6` | Kimi K2.6 (3x 한도) |
| `opencode-go/deepseek-v4-pro` | DeepSeek V4 Pro |
| `opencode-go/deepseek-v4-flash` | DeepSeek V4 Flash |
| `opencode-go/mimo-v2-pro` | MiMo V2 Pro |
| `opencode-go/minimax-m2.7` | MiniMax M2.7 |
| `opencode-go/qwen3.6-plus` | Qwen3.6 Plus |

## 주의사항

- `OPENCODE_API_KEY`는 Zen과 Go 카탈로그에서 공유됩니다
- 런타임 참조는 `opencode-go/...`로 명시해야 Go 카탈로그로 라우팅됩니다
- Privacy Router 경유 시 `OPENCODE_API_KEY`는 Privacy Router 서버의 `.env`에 설정해야 합니다

**참조:** [OpenClaw OpenCode Go 문서](https://docs.openclaw.ai/providers/opencode-go)
