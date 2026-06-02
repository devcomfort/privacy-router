# Privacy Router 통합 가이드

## 핵심 통합 방식

Privacy Router는 **MCP(Model Context Protocol)**를 지원하므로, MCP를 지원하는 모든 에이전트 도구와 통합 가능합니다.

```
┌─────────────────┐     MCP (stdio/SSE)     ┌──────────────────┐
│  AI Agent Tool  │ ◄──────────────────────► │ Privacy Router   │
│  (pi, opencode, │                          │ MCP Server       │
│   openclaw...)  │                          │                  │
└─────────────────┘                          └──────────────────┘
```

## 탐지 태그

Privacy Router는 SLM이 자유롭게 생성하는 SCREAMING_CASE 형식의 태그로 민감 정보를 탐지합니다.

**태그 생성 규칙:**
- SLM이 텍스트를 분석하고 적절한 태그를 생성
- 반드시 SCREAMING_CASE 형식 (예: `MERGER_DECISION`, `NOVEL_ALGORITHM`)
- 하이드레이션이 가능하도록 고유하고 명확한 이름 사용

**예시 태그:**

| 맥락 | 생성된 태그 | 판단 근거 |
|------|------------|----------|
| "주민등록번호 901212-1234567" | `RESIDENT_REGISTRATION_NUMBER` | 한국 주민등록번호 |
| "TSMC 3nm 공정을 채택하기로 결정" | `FABRICATION_PROCESS_DECISION` | 반도체 공정 결정 |
| "새로운 강화학습 알고리즘 아이디어" | `NOVEL_RL_ALGORITHM_IDEA` | 미공개 연구 개념 |
| "예산 1,200억원" | `PROJECT_BUDGET_AMOUNT` | 재무 정보 |
| "아직 논문에 제출하지 않음" | `UNPUBLISHED_RESEARCH_STATUS` | 출판 전 상태 |

---

## 1. pi (코딩 에이전트)

### 통합 방식: MCP Extension

pi는 MCP를 지원하므로 설정 파일에 Privacy Router를 등록하면 됩니다.

**설정 파일:** `~/.pi/config.json` 또는 프로젝트 `.pi/config.json`

```json
{
  "mcpServers": {
    "privacy-router": {
      "command": "rye",
      "args": ["run", "python", "-m", "packages.mcp_servers.privacy_router_server.server"],
      "cwd": "/mnt/workspace/projects/privacy-router",
      "env": {
        "EXTRACTOR_MODEL": "ollama/ministral-3"
      }
    }
  }
}
```

**사용 예시:**
```
> 이 텍스트에서 개인정보를 찾아줘: "주민번호 901212-1234567"
[pi가 privacy-router의 classify_tool을 자동으로 호출]
```

---

## 2. OpenCode

### 통합 방식: MCP 설정

OpenCode도 MCP를 지원합니다.

**설정 파일:** `~/.opencode/config.json`

```json
{
  "mcp": {
    "servers": {
      "privacy-router": {
        "type": "stdio",
        "command": "rye",
        "args": ["run", "python", "-m", "packages.mcp_servers.privacy_router_server.server"],
        "cwd": "/mnt/workspace/projects/privacy-router"
      }
    }
  }
}
```

---

## 3. OpenClaw

### 통합 방식: Skill + MCP

OpenClaw는 스킬 시스템을 지원합니다. Privacy Router를 스킬로 등록합니다.

**스킬 설정:** `.openclaw/skills/privacy-router.yaml`

```yaml
name: privacy-router
description: 개인정보 보호 라우팅 - PII 탐지, 마스킹, 정책 기반 라우팅
version: 0.1.0

mcp:
  command: rye
  args:
    - run
    - python
    - -m
    - packages.mcp_servers.privacy_router_server.server
  cwd: /mnt/workspace/projects/privacy-router
  env:
    EXTRACTOR_MODEL: ollama/ministral-3

tools:
  - name: classify
    description: 텍스트에서 개인정보 탐지 및 분류
    auto_call: true  # 에이전트가 자동으로 호출

  - name: redact
    description: 민감 정보 마스킹

  - name: route
    description: 적절한 모델 티어 선택
```

**SOUL.md에 추가:**
```markdown
## Privacy Router

모든 외부 API 호출 전에 privacy-router를 통해 개인정보를 검사합니다.
- 민감 정보가 감지되면 자동으로 마스킹하거나 로컬에서 처리합니다.
- 사용자 확인이 필요한 경우 명시적으로 질문합니다.
```

---

## 4. Hermes Agent

### 통합 방식: Python SDK 직접 호출

Hermes Agent가 Python 기반이라면 직접 SDK를 호출할 수 있습니다.

```python
from packages.extractor import classify_text
from packages.judge import Judge
from packages.router import PrivacyRouter, mask_text
from packages.types import load_config, find_config_path, ClassificationResult

class PrivacyMiddleware:
    """Hermes Agent용 개인정보 보호 미들웨어."""

    def __init__(self):
        config_path = find_config_path()
        self.config = load_config(config_path)
        self.judge = Judge(self.config)
        self.router = PrivacyRouter()

    def intercept(self, text: str) -> dict:
        """프롬프트를 가로채고 개인정보를 검사합니다."""
        # 1. 탐지
        records = classify_text(text)
        judgment = self.judge.classify(records=records)

        # 2. 분류
        is_sensitive = judgment.sensitivity in ("sensitive", "mixed")

        if not is_sensitive:
            return {"action": "pass", "text": text}

        # 3. 마스킹
        if judgment.policy_action in ("auto_redact", "prompt_user"):
            result = mask_text(text, records)
            return {
                "action": "mask",
                "original": text,
                "masked": result.masked_text,
                "placeholder_map": result.placeholder_map,
            }
        else:  # local_only
            return {
                "action": "local_only",
                "text": text,
                "reason": judgment.rationale,
            }

# 사용 예시
middleware = PrivacyMiddleware()
result = middleware.intercept("주민번호 901212-1234567을 검색해주세요")

if result["action"] == "mask":
    # 마스킹된 텍스트를 외부 API에 전송
    response = call_external_api(result["masked"])
    # 응답에서 원본 값 복원
    final = hydrate_text(response, result["placeholder_map"])
elif result["action"] == "local_only":
    # 로컬 모델에서 처리
    response = call_local_model(result["text"])
```

---

## 5. Telegram / Slack 봇

### 통합 방식: WebSocket API

프론트엔드 API를 활용하여 봇을 구현합니다.

```python
import asyncio
import websockets
import json

async def privacy_bot_handler(websocket):
    """Telegram/Slack 봇 핸들러."""
    async for message in websocket:
        data = json.loads(message)

        # Privacy Router WebSocket에 전달
        async with websockets.connect("ws://localhost:8000/ws/chat") as ws:
            await ws.send(json.dumps({
                "text": data["text"],
                "user_id": data["user_id"]
            }))
            response = await ws.recv()
            result = json.loads(response)

            # 결과를 사용자에게 전송
            await send_to_user(data["user_id"], format_response(result))

def format_response(result: dict) -> str:
    """응답 포맷팅."""
    if result["judgment"]["sensitivity"] == "non_sensitive":
        return result["response"]

    return (
        f"🔒 민감 정보 감지됨\n"
        f"민감도: {result['judgment']['sensitivity']}\n"
        f"정책: {result['judgment']['policy_action']}\n"
        f"\n{result['response']}"
    )
```

---

## 6. LangChain / LlamaIndex

### 통합 방식: Callback / Middleware

```python
from langchain.callbacks.base import BaseCallbackHandler
from packages.extractor import classify_text
from packages.router import mask_text, hydrate_text

class PrivacyCallbackHandler(BaseCallbackHandler):
    """LangChain용 개인정보 보호 콜백."""

    def __init__(self):
        self.placeholder_map = {}

    def on_llm_start(self, serialized, prompts, **kwargs):
        """LLM 호출 전 프롬프트 검사."""
        for i, prompt in enumerate(prompts):
            records = classify_text(prompt)
            if records:
                result = mask_text(prompt, records)
                prompts[i] = result.masked_text
                self.placeholder_map.update(result.placeholder_map)

    def on_llm_end(self, response, **kwargs):
        """LLM 응답 후 하이드레이션."""
        for i, generation in enumerate(response.generations):
            for j, gen in enumerate(generation):
                if self.placeholder_map:
                    hydrated = hydrate_text(gen.text, self.placeholder_map)
                    generation[j].text = hydrated.hydrated_text

# 사용
handler = PrivacyCallbackHandler()
llm = ChatOpenAI(callbacks=[handler])
response = llm.invoke("주민번호 901212-1234567 분석해줘")
```

---

## 7. LiteLLM Proxy

### 통합 방식: Pre-call Hook

```python
import litellm
from packages.extractor import classify_text
from packages.router import mask_text, hydrate_text

@litellm.pre_call_fn
def privacy_hook(request):
    """LiteLLM 프록시용 개인정보 보호 훅."""
    messages = request.get("messages", [])

    for msg in messages:
        if msg["role"] == "user":
            records = classify_text(msg["content"])
            if records:
                result = mask_text(msg["content"], records)
                msg["content"] = result.masked_text
                request["privacy_placeholders"] = result.placeholder_map

@litellm.post_call_fn
def hydration_hook(response, request):
    """응답 하이드레이션."""
    placeholders = request.get("privacy_placeholders", {})
    if placeholders:
        for choice in response.choices:
            hydrated = hydrate_text(choice.message.content, placeholders)
            choice.message.content = hydrated.hydrated_text
```

---

## 통합 가능성 요약

| 도구 | 통합 방식 | 가능성 | 난이도 |
|---|---|---|---|
| **pi** | MCP 설정 | ✅ 즉시 가능 | 쉬움 |
| **OpenCode** | MCP 설정 | ✅ 즉시 가능 | 쉬움 |
| **OpenClaw** | Skill + MCP | ✅ 즉시 가능 | 쉬움 |
| **Hermes Agent** | Python SDK | ✅ 가능 | 보통 |
| **Telegram/Slack** | WebSocket API | ✅ 가능 | 보통 |
| **LangChain** | Callback | ✅ 가능 | 보통 |
| **LlamaIndex** | Callback | ✅ 가능 | 보통 |
| **LiteLLM** | Pre-call Hook | ✅ 가능 | 보통 |
| **Claude Code** | MCP 설정 | ✅ 즉시 가능 | 쉬움 |
| **Cursor** | MCP 설정 | ✅ 즉시 가능 | 쉬움 |

---

## 빠른 시작

### MCP 지원 도구 (pi, OpenCode, OpenClaw, Claude Code, Cursor)

1. Privacy Router 서버 시작:
   ```bash
   ./demo.sh
   ```

2. 도구 설정에 MCP 서버 등록 (위 설정 파일 참조)

3. 에이전트가 자동으로 Privacy Router를 호출

### Python 기반 도구 (Hermes, LangChain 등)

```python
from packages.extractor import classify_text
from packages.router import mask_text, hydrate_text

# 직접 사용
records = classify_text("주민번호 901212-1234567")
result = mask_text("주민번호 901212-1234567", records)
```

---

## 주의사항

1. **MCP 서버 실행 필요**: MCP 기반 통합 시 서버가 실행 중이어야 합니다
2. **환경변수 설정**: `.env` 파일에 API 키 설정 필요
3. **모델 다운로드**: Ollama 사용 시 모델 미리 다운로드 필요
4. **네트워크**: 원격 서버 사용 시 포트 열기 필요
