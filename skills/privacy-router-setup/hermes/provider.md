---
name: hermes-privacy-router
description: Configure Hermes Agent to use Privacy Router as custom LLM provider and MCP server.
---

# Hermes Agent + Privacy Router 설정

Hermes Agent에서 Privacy Router를 사용하는 방법을 안내합니다.

> **참고:** Hermes Agent는 현재 비공개 상태입니다. 아래 설정은 공개된 패턴과 유사 에이전트의 설정 방식을 기반으로 한 추정입니다.

## 1. Custom Provider 설정

Hermes Agent가 Privacy Router를 LLM 프록시로 사용하도록 설정합니다.

**설정 파일:** `~/.hermes/config.yaml`

```yaml
model:
  provider: custom
  base_url: http://localhost:8787/v1
  api_key: "pr-YOUR-API-KEY"
  default: "openrouter/google/gemini-3.1-flash-lite"
```

## 2. MCP 서버 연결

Hermes Agent에서 MCP 서버를 연결하여 도구를 사용할 수 있습니다.

### MCP 서버 찾기

- [Smithery](https://smithery.ai/) — MCP 서버 레지스트리
- [mcp.run](https://mcp.run/) — 호스팅 MCP 서버
- [GitHub: awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) — 커뮤니티 MCP 서버 목록

### 설정 형식

```yaml
mcp_servers:
  서버이름:
    command: 실행 명령어
    args: ["인자1", "인자2"]
    env:
      KEY: "value"
```

### Privacy Router MCP 연결

Privacy Router를 MCP로 사용하는 방법은 [README.md](../../README.md)의 "MCP 서버" 섹션을 참조하세요.

## 3. Docker Compose로 실행

```bash
# Privacy Router + Hermes Agent 동시 실행
docker compose -f docker-compose.yml -f docker-compose.hermes.yml up -d
```

**Docker Compose 설정:** `docker-compose.hermes.yml`

```yaml
services:
  hermes:
    build:
      context: .
      dockerfile: demo/hermes/Dockerfile
    volumes:
      - ./demo/hermes/config.yaml:/root/.hermes/config.yaml:ro
    environment:
      PRIVACY_ROUTER_URL: http://api:8787
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY}
    depends_on:
      - api
```

## 4. Privacy Router API 키 생성

```bash
curl -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "hermes", "provider_id": "openrouter"}'
```

## 5. 테스트

```bash
# Hermes Agent에서 Privacy Router를 통해 LLM 호출
hermes chat "주민등록번호 901212-1234567을 확인해주세요"
# → Privacy Router가 자동으로 마스킹 후 LLM 호출
```
