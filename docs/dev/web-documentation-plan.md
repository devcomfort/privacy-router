# Web Documentation Plan

## Overview

Privacy Router의 공식 웹 문서를 설계합니다. SvelteKit SSG + Tailwind CSS 기반, i18n 영어/한국어(기본 영어) 지원.

## i18n 변경

| 항목 | 현재 | 변경 |
|------|------|------|
| 기본 로케일 | `ko` | `en` |
| 저장 키 | `localStorage('locale')` → `'ko'` | `localStorage('locale')` → `'en'` |
| en.json | 258줄 | 새 문서 키 추가 |
| ko.json | 258줄 | 새 문서 키 추가 |

### i18n 변경 파일

- `web/src/lib/i18n/index.ts`: 기본값 `'ko'` → `'en'`
- `web/src/lib/i18n/en.json`: 새 키 추가
- `web/src/lib/i18n/ko.json`: 새 키 추가

## 페이지 구조

### 네비게이션

```
┌─────────────────────────────────────────────┐
│ Privacy Router    [Home] [Demo] [Docs] [EN/KO] │
└─────────────────────────────────────────────┘
```

### Documentation 홈 (`/documentation`)

```
┌─────────────────────────────────────────────┐
│ Documentation                                │
│                                              │
│ ┌─────────────┐ ┌─────────────┐             │
│ │ Getting     │ │ Detection   │             │
│ │ Started     │ │             │             │
│ │ 🚀          │ │ 🔍          │             │
│ └─────────────┘ └─────────────┘             │
│ ┌─────────────┐ ┌─────────────┐             │
│ │ Masking     │ │ API Keys    │             │
│ │ 🔒          │ │ 🔑          │             │
│ └─────────────┘ └─────────────┘             │
│ ┌─────────────┐ ┌─────────────┐             │
│ │ MCP         │ │ Model       │             │
│ │ Integration │ │ Registry    │             │
│ │ 🔌          │ │ 🤖          │             │
│ └─────────────┘ └─────────────┘             │
│ ┌─────────────┐ ┌─────────────┐             │
│ │ Architecture│ │ Security    │             │
│ │ 🏗️          │ │ 🛡️          │             │
│ └─────────────┘ └─────────────┘             │
│ ┌─────────────┐ ┌─────────────┐             │
│ │ Cost        │ │ Experiments │             │
│ │ 💰          │ │ 📊          │             │
│ └─────────────┘ └─────────────┘             │
└─────────────────────────────────────────────┘
```

### 페이지별 i18n 키 매핑

#### Getting Started

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.getting_started` | Getting Started | 빠른 시작 |
| `docs.getting_started.title` | Quick Start Guide | 빠른 시작 가이드 |
| `docs.getting_started.desc` | Install and run Privacy Router in 3 steps | 3단계로 Privacy Router 설치 및 실행 |
| `docs.getting_started.prereqs` | Prerequisites | 사전 요구사항 |
| `docs.getting_started.quickstart` | Quick Start | 빠른 시작 |
| `docs.getting_started.hermes` | Hermes Agent Demo | Hermes Agent 데모 |
| `docs.getting_started.profiles` | Docker Compose Profiles | Docker Compose 프로필 |
| `docs.getting_started.access` | Access Points | 접속 주소 |

#### Detection

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.detection` | Detection | 민감도 탐지 |
| `docs.detection.title` | Socratic Sensitivity Detection | Socratic 민감도 탐지 |
| `docs.detection.desc` | How Privacy Router detects sensitive information | Privacy Router가 민감 정보를 탐지하는 방식 |
| `docs.detection.framework` | Sensitivity Classification | Sensitivity Classification |
| `docs.detection.is_essential` | Masking Feasibility | 마스킹 가능 여부 |
| `docs.detection.examples` | Detection Examples | 탐지 예시 |

#### Masking

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.masking` | Masking & Hydration | 마스킹 & 하이드레이션 |
| `docs.masking.title` | How sensitive data is masked and restored | 민감 정보 마스킹 및 복원 방식 |
| `docs.masking.uid` | UID-based Placeholders | UID 기반 플레이스홀더 |
| `docs.masking.contract` | MaskingContract | MaskingContract |
| `docs.masking.hydration` | Hydration | 하이드레이션 |
| `docs.masking.api` | Masking API | 마스킹 API |

#### API Keys

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.api_keys` | API Keys | API 키 |
| `docs.api_keys.title` | API Key Management | API 키 관리 |
| `docs.api_keys.create` | Create a Key | 키 생성 |
| `docs.api_keys.security` | Security | 보안 |
| `docs.api_keys.provider` | Provider Keys | 프로바이더 키 |

#### MCP Integration

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.mcp` | MCP Integration | MCP 통합 |
| `docs.mcp.title` | MCP Server Integration | MCP 서버 통합 |
| `docs.mcp.desc` | Integrate Privacy Router as an MCP server | MCP 서버로 Privacy Router 통합 |
| `docs.mcp.hermes` | Hermes Agent | Hermes Agent |
| `docs.mcp.tools` | MCP Tools | MCP 도구 |

#### Model Registry

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.models` | Model Registry | 모델 레지스트리 |
| `docs.models.title` | Supported Models | 지원 모델 |
| `docs.models.desc` | OpenRouter models available for the pipeline | 파이프라인에서 사용 가능한 OpenRouter 모델 |
| `docs.models.tiers` | Model Tiers | 모델 티어 |

#### Architecture (dev)

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.architecture` | Architecture | 아키텍처 |
| `docs.architecture.title` | System Architecture | 시스템 아키텍처 |
| `docs.architecture.pipeline` | Pipeline | 파이프라인 |
| `docs.architecture.components` | Components | 컴포넌트 |
| `docs.architecture.api` | API Surface | API 표면 |
| `docs.architecture.testing` | Testing | 테스트 |

#### Security

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.security` | Security | 보안 |
| `docs.security.title` | Privacy and Security | 프라이버시 및 보안 |
| `docs.security.threat` | Threat Model | 위협 모델 |
| `docs.security.encryption` | Encryption | 암호화 |
| `docs.security.retention` | Data Retention | 데이터 보존 |
| `docs.security.auth` | Authentication | 인증 |

#### Cost

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.cost` | Cost | 비용 |
| `docs.cost.title` | Cost Estimate | 비용 추정 |
| `docs.cost.monthly` | Monthly Cost | 월 비용 |
| `docs.cost.two_tier` | Two-Tier Routing | Two-Tier 라우팅 |

#### Experiments

| en.json 키 | en 값 | ko 값 |
|-----------|-------|-------|
| `docs.experiments` | Experiments | 실험 |
| `docs.experiments.title` | Evaluation Results | 평가 결과 |
| `docs.experiments.models` | Model Comparison | 모델 비교 |
| `docs.experiments.tuning` | Optuna Tuning | Optuna 튜닝 |

## 콘텐츠 소스 매핑

| 웹 페이지 | 마크다운 소스 | 렌더링 방식 |
|-----------|-------------|-----------|
| `/documentation/getting-started` | `docs/user/getting-started.md` | 마크다운 렌더링 |
| `/documentation/detection` | `docs/user/detection.md` | 마크다운 렌더링 |
| `/documentation/masking` | `docs/user/masking-hydration.md` | 마크다운 렌더링 |
| `/documentation/api-keys` | `docs/user/api-keys.md` | 마크다운 렌더링 |
| `/documentation/mcp-integration` | `docs/user/mcp-integration.md` | 마크다운 렌더링 |
| `/documentation/model-registry` | `docs/user/model-registry.md` | 마크다운 렌더링 |
| `/documentation/architecture` | `docs/dev/architecture.md` | 마크다운 렌더링 |
| `/documentation/security` | `docs/user/security.md` | 마크다운 렌더링 |
| `/documentation/cost` | `docs/user/cost.md` | 마크다운 렌더링 |
| `/documentation/experiments` | `docs/experiments/eval-report.md` | 마크다운 렌더링 |

## 마크다운 렌더링

### 옵션

| 방식 | 장점 | 단점 |
|------|------|------|
| **빌드 시 HTML 변환** | 빠른 로드, SEO 친화 | 빌드 시 변환 필요 |
| **런타임 JS 렌더링** | 동적 로드 | 초기 로드 느림 |

**권장:** 빌드 시 HTML 변환. SvelteKit SSG와 맞음.

### 구현

```bash
# npm 패키지
npm install marked highlight.js
```

마크다운 파일을 `web/src/lib/docs/`에 복사하고, 빌드 시 `marked`로 HTML 변환.

## 삭제 대상

| 현재 페이지 | 처리 |
|------------|------|
| `/documentation/differentiation` | 삭제 (문서 없음, rubric에서도 제거) |
| `/documentation/evidence` | 삭제 (개별 페이지로 분리) |
| `/documentation/smartening` | 삭제 (문서 없음) |
| `/documentation/logs` | 유지 (usage-log 대시보드) |

## 구현 순서

1. **Phase 1: i18n 변경** — 기본 로케일 영어로, 새 키 추가
2. **Phase 2: 페이지 구조 변경** — 새 페이지 생성, 구 페이지 삭제
3. **Phase 3: 마크다운 렌더링** — marked + highlight.js 연동
4. **Phase 4: 콘텐츠 마이그레이션** — docs/ → web/src/lib/docs/ 복사
5. **Phase 5: 빌드 & 검증** — `npm run build` + SSG 출력 확인
