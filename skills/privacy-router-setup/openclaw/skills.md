---
name: openclaw-skills
description: Create and manage OpenClaw skills for Privacy Router integration.
---

# OpenClaw 스킬 설정

OpenClaw에서 Privacy Router 관련 스킬을 생성하고 관리하는 방법을 안내합니다.

**참조:** [OpenClaw Skills 문서](https://docs.openclaw.ai/tools/skills)

## 스킬이란?

스킬은 OpenClaw가 특정 작업을 수행할 때 참조하는 지침 파일입니다. `SKILL.md` 파일에 YAML frontmatter와 마크다운 본문으로 구성됩니다.

## 스킬 디렉토리 구조

```
~/.openclaw/workspace/skills/
├── privacy-router-setup/          ← 이 스킬
│   ├── SKILL.md
│   ├── openclaw/
│   │   ├── provider.md
│   │   ├── channels.md
│   │   └── skills.md
│   ├── hermes/
│   │   └── provider.md
│   └── mcp/
│       └── setup.md
└── privacy-router-classify/       ← 예시: 분류 전용 스킬
    └── SKILL.md
```

**스킬 탐색 순위:**
1. `<workspace>/skills/`
2. `<workspace>/.agents/skills/`
3. `~/.agents/skills/`
4. `~/.openclaw/skills/`
5. 번들 스킬
6. `skills.load.extraDirs`에 지정된 경로

## Privacy Router 스킬 생성 예시

### 분류 전용 스킬

```markdown
---
name: privacy-router-classify
description: Classify text for sensitive information using Privacy Router.
---

# Privacy Router Classify

텍스트에서 민감 정보를 탐지합니다.

## 사용법

MCP `process` 도구를 호출합니다:

\`\`\`
process(text="분석할 텍스트", action="classify")
\`\`\`

## 결과 해석

- `is_sensitive: true` — 민감 정보 포함
- `records[]` — 탐지된 레코드 목록
- `policy_action` — 권장 조치 (allow/mask_and_send/prompt_user)
```

### 마스킹 전용 스킬

```markdown
---
name: privacy-router-mask
description: Mask sensitive information and forward to LLM.
---

# Privacy Router Mask

민감 정보를 마스킹하고 LLM에 전송합니다.

## 사용법

\`\`\`
process(text="주민등록번호 901212-1234567을 포함한 요청", action="generate")
\`\`\`

## 결과

- `action_taken: "generated"` — 마스킹 후 LLM 호출 완료
- `masking_session_id` — 하이드레이션용 세션 ID
- `masking_records[]` — 마스킹된 레코드 상세
```

## 스킬 등록 방법

### 수동 등록

```bash
# 스킬 디렉토리 생성
mkdir -p ~/.openclaw/workspace/skills/my-skill

# SKILL.md 작성
cat > ~/.openclaw/workspace/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: My custom skill description.
---

# My Skill

스킬 내용...
EOF
```

### CLI로 등록

```bash
# 스킬 목록 확인
openclaw skills list

# 스킬 상세 확인
openclaw skills show privacy-router-setup
```

## Privacy Router와 함께 사용하는 스킬 패턴

### 1. 프롬프트 전처리 스킬

에이전트가 사용자 프롬프트를 보내기 전에 Privacy Router로 분류:

```markdown
---
name: prompt-preprocessor
description: Pre-process user prompts through Privacy Router before sending to LLM.
---

# Prompt Preprocessor

사용자 프롬프트를 LLM에 보내기 전에 Privacy Router로 분류합니다.

## 워크플로우

1. 사용자 프롬프트 수신
2. `process(text, action="classify")` 호출
3. `is_sensitive: true`이면 사용자에게 확인
4. 확인 후 `process(text, action="generate")` 호출
```

### 2. 세션 관리 스킬

마스킹 세션을 추적하고 하이드레이션:

```markdown
---
name: session-manager
description: Track masking sessions for multi-turn conversations.
---

# Session Manager

멀티턴 대화에서 마스킹 세션을 관리합니다.

## 워크플로우

1. 첫 요청: `process(text, action="auto", chat_id="user-123")`
2. `masking_session_id` 저장
3. 후속 요청: `process(text, action="auto", chat_id="user-123")`
4. 동일한 chat_id로 이전 마스킹 컨트랙트 재사용
```

**참조:** [OpenClaw Creating Skills](https://docs.openclaw.ai/tools/creating-skills)
