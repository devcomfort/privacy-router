# 에이전트 도구별 SDK 통합 가능성 분석

## 요약

| 도구 | 프록시 가능 | SDK 지원 | 통합 방식 | 가능성 |
|---|---|---|---|---|
| **pi** | ✅ | ✅ TypeScript SDK | Extension API | **즉시 가능** |
| **opencode** | ⚠️ | ⚠️ 제한적 | LOCAL_ENDPOINT | **가능 (우회)** |
| **Hermes Agent** | ❓ | ❓ 확인 필요 | - | **불확실** |
| **OpenClaw** | ❓ | ❓ 확인 필요 | - | **불확실** |

---

## 1. pi (코딩 에이전트)

### 지원 방식: Extension API

pi는 **TypeScript SDK**를 제공하며, **Extension API**를 통해 에이전트 이벤트를 가로채고 커스텀 도구를 등록할 수 있습니다.

### 핵심 기능

```typescript
// pi Extension API
export default function (pi: ExtensionAPI) {
  // 에이전트 시작 전 프롬프트 가로채기
  pi.on("agent_start", async () => {
    console.log("[Privacy Router] Checking prompt...");
  });

  // 도구 호출 가로채기 (차단 가능)
  pi.on("tool_call", async (event) => {
    if (event.toolName === "bash") {
      // 개인정보 검사
      const decision = privacyRouter.intercept(event.args.command);
      if (decision.action === "block") {
        return { block: true, reason: "민감 정보 포함" };
      }
    }
    return undefined;
  });

  // 커스텀 도구 등록
  pi.registerTool({
    name: "privacy_check",
    description: "개인정보 검사",
    parameters: Type.Object({ text: Type.String() }),
    execute: async (id, params) => {
      const result = privacyRouter.intercept(params.text);
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    }
  });
}
```

### 통합 방법

**파일:** `~/.pi/agent/extensions/privacy-router.ts`

```typescript
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("agent_start", async (event) => {
    // 사용자 프롬프트에서 개인정보 검사
    const prompt = event.prompt;
    const decision = await checkPrivacy(prompt);

    if (decision.shouldMask) {
      // 프롬프트를 마스킹된 버전으로 교체
      event.prompt = decision.maskedText;
      event.metadata = { placeholderMap: decision.placeholderMap };
    }
  });

  pi.on("agent_end", async (event) => {
    // 응답에서 원본 값 복원
    if (event.metadata?.placeholderMap) {
      event.messages = hydrateMessages(event.messages, event.metadata.placeholderMap);
    }
  });
}
```

### 가능성: ✅ 즉시 가능

pi는 Extension API를 통해 프롬프트를 가로채고 수정할 수 있습니다.

---

## 2. opencode

### 지원 방식: LOCAL_ENDPOINT (프록시)

opencode는 직접적인 미들웨어/훅을 제공하지 않지만, **LOCAL_ENDPOINT**를 통해 커스텀 엔드포인트를 지정할 수 있습니다.

### 핵심 기능

```bash
# opencode 설정
LOCAL_ENDPOINT=http://localhost:9000/v1
```

### 통합 방법

**Privacy Proxy 서버 실행:**
```bash
# Privacy Router 프록시 시작
python -m packages.gateway.proxy --port 9000 --target https://api.openai.com

# opencode에서 프록시 사용
export LOCAL_ENDPOINT=http://localhost:9000/v1
opencode
```

**또는 설정 파일:**
```json
{
  "providers": {
    "custom": {
      "endpoint": "http://localhost:9000/v1",
      "apiKey": "sk-..."
    }
  }
}
```

### 가능성: ⚠️ 우회 방식

opencode는 프록시를 통해 간접적으로 개인정보를 검사할 수 있지만, 직접적인 미들웨어 지원은 제한적입니다.

---

## 3. Hermes Agent

### 확인 필요

Hermes Agent의 공개된 SDK나 설정 방법에 대한 정보가 제한적입니다.

### 가능성: ❓ 확인 필요

---

## 4. OpenClaw

### 확인 필요

OpenClaw의 공개된 SDK나 설정 방법에 대한 정보가 제한적입니다.

### 가능성: ❓ 확인 필요

---

## 권장 통합 방안

### pi (최우선)

가장 완벽한 통합이 가능합니다. Extension API를 사용하여:
1. 프롬프트 가로채기
2. 도구 호출 차단
3. 응답 하이드레이션

### opencode (차선)

LOCAL_ENDPOINT를 통한 프록시 방식으로:
1. Privacy Proxy 서버 실행
2. opencode 설정 변경
3. 모든 API 호출이 프록시를 거침

### 기타 도구

MCP 서버를 통한 통합 시도:
```json
{
  "mcpServers": {
    "privacy-router": {
      "command": "rye",
      "args": ["run", "python", "-m", "packages.mcp_servers.privacy_router_server.server"]
    }
  }
}
```

---

## 구현 우선순위

1. **pi Extension** — 가장 완벽한 통합
2. **opencode Proxy** — 우회 방식이지만 효과적
3. **MCP 서버** — 표준 프로토콜, 대부분의 도구 지원
4. **Python SDK** — 커스텀 에이전트용

---

## 참고 자료

- pi SDK 문서: `~/.pi/agent/docs/sdk.md`
- pi Extension 예시: `~/.pi/agent/examples/sdk/06-extensions.ts`
- opencode 설정: `~/.opencode/oh-my-openagent.jsonc`
- Privacy Router MCP: `packages/mcp_servers/privacy_router_server/`
- Privacy Proxy: `packages/gateway/proxy.py`
