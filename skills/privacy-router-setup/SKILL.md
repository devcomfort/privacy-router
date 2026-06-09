---
name: privacy-router-setup
description: Configure AI agents (OpenClaw, Hermes Agent) to use Privacy Router as their LLM proxy. Covers custom provider setup, MCP server connection, channel integration, and skill creation.
---

# Privacy Router Setup Skill

Privacy Router를 AI 에이전트의 LLM 프록시로 설정하는 가이드입니다.

## Executive Summary

Privacy Router는 에이전트와 외부 LLM 사이의 프록시 레이어입니다. 에이전트가 Privacy Router를 사용하도록 설정하면, 모든 LLM 요청이 자동으로 민감 정보 탐지 → 마스킹 → 라우팅을 거칩니다.

**설정 방식 3가지:**
1. **Custom Provider** — 에이전트의 LLM 요청을 Privacy Router로 라우팅
2. **MCP Server** — Privacy Router의 `process` 도구를 직접 호출
3. **Channel Integration** — Slack/Discord/etc.에서 Privacy Router 통합

## 지원 에이전트

| 에이전트 | 상태 | 문서 |
|---|---|---|
| **OpenClaw** | ✅ 완전 지원 | [docs.openclaw.ai](https://docs.openclaw.ai) |
| **Hermes Agent** | ⚠️ 비공개 (설정 추정) | 비공개 레포 |


## 스킬 목록

| 스킬 | 파일 | 설명 |
|---|---|---|
| OpenClaw Provider | [openclaw/provider.md](openclaw/provider.md) | Custom Provider + MCP 연결 |
| OpenClaw Channels | [openclaw/channels.md](openclaw/channels.md) | Slack, Discord, Telegram, Email 채널 설정 |
| OpenClaw Skills | [openclaw/skills.md](openclaw/skills.md) | 스킬 생성 및 관리 |
| Hermes Provider | [hermes/provider.md](hermes/provider.md) | Custom Provider + MCP 연결 |
| Hermes Channels | [hermes/channels.md](hermes/channels.md) | Slack, Discord, Telegram, Email 채널 설정 |
| Hermes Skills | [hermes/skills.md](hermes/skills.md) | 스킬 생성 및 관리 |

## 빠른 시작

```bash
# 1. Privacy Router 실행
docker compose up -d

# 2. OpenClaw에 Custom Provider 연결 (openclaw/provider.md 참조)
# ~/.openclaw/openclaw.json에 provider 추가

# 3. 채널 연동 (openclaw/channels.md 참조)
# Slack, Discord, Telegram, Email 설정
```

## Privacy Router MCP

Privacy Router를 MCP 서버로 사용하는 방법은 [README.md](../../README.md)를 참조하세요.

## 참조

- [Privacy Router README](../../README.md)
- [OpenClaw 설정 문서](https://docs.openclaw.ai/gateway/configuration)
- [OpenClaw Custom Providers](https://docs.openclaw.ai/gateway/config-tools)
- [OpenClaw Channels](https://docs.openclaw.ai/channels)
- [OpenClaw Skills](https://docs.openclaw.ai/tools/skills)
- [OpenClaw Skills](https://docs.openclaw.ai/tools/skills)
