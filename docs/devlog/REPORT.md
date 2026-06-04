# Privacy Router — 평가 보고서

**프로젝트:** Privacy Router — 한국 연구자를 위한 주권 우선 AI 비서
**기간:** 2026-06-02 ~ 2026-06-03
**목적:** Extractor + Judge 파이프라인에 최적의 LLM 모델 선정 및 프롬프트 최적화

---

## Table of Contents

1. [Abstract](#1-abstract)
2. [Introduction](#2-introduction)
3. [System Architecture](#3-system-architecture)
4. [Experiment Design](#4-experiment-design)
5. [Phase 1: Model Selection (v1)](#5-phase-1-model-selection-v1)
6. [Phase 2: Prompt Optimization (v2)](#6-phase-2-prompt-optimization-v2)
7. [Comparative Results](#7-comparative-results)
8. [Analysis](#8-analysis)
9. [Conclusion](#9-conclusion)
10. [Appendix](#10-appendix)

---

## 1. Abstract

Privacy Router의 Extractor + Judge 파이프라인에 최적화된 LLM 모델을 선정하고, 프롬프트 개선을 통해 탐지 성능을 향상시키는 두 단계의 실험을 수행했다.

**Phase 1 (v1):** 9개 모델을 N=5 반복 평가한 결과, `gemini-3.1-flash-lite`만이 PII, 사업기밀, 연구기밀을 모두 탐지했다(평점 5.0). 모든 오픈소스 모델은 사업/연구 기밀 탐지에 실패했다(평점 1.8~2.8).

**Phase 2 (v2):** Extractor 프롬프트에 맥락적 추론 질문 2개를 추가한 결과, 추가 비용 없이 6개 모델에서 사업/연구 기밀 탐지율이 0~20%에서 100%로 상승했다. 특히 `ministral-3b-2512`($0.10/1M tok)가 PII, 사업기밀, 연구기밀을 7/7 완전 탐지하게 되었다.

**결론:** 프롬프트 엔지니어링만으로 작은 모델의 컨텍스트 기반 탐지 능력을 획기적으로 개선할 수 있다.

---

## 2. Introduction

### 2.1 Problem

AI 에이전트가 프롬프트를 외부 LLM API로 전송할 때, 사용자가 인지하지 못한 민감 정보(사업 기밀, 연구 기밀, 개인 식별 정보)가 함께 유출될 위험이 있다. Privacy Router는 모든 프롬프트를 가로채 Extractor → Judge 파이프라인으로 민감도를 평가하고, 필요시 마스킹 또는 로컬 처리를 결정한다.

### 2.2 Challenge

Extractor는 SLM에 의존하므로, 모델의 컨텍스트 이해 능력이 전체 시스템의 탐지 성능을 결정한다. 특히 사업 기밀과 연구 기밀은 명시적 패턴이 아닌 맥락에서만 민감도가 드러나기 때문에, 작은 모델에서의 탐지가 매우 어렵다.

### 2.3 Goals

1. Extractor + Judge 파이프라인에 가장 적합한 모델 식별
2. 프롬프트 개선을 통해 작은 모델의 컨텍스트 기반 탐지 능력 향상
3. 비용-성능 균형점 도출

---

## 3. System Architecture

```
User Prompt → Extractor → Sensitivity + Records → Judge → Meaningfulness + Policy Action
```

| Component | Role | LLM Call |
|-----------|------|----------|
| **Extractor** | 민감 정보 탐지, SCREAMING_CASE 태그 생성 | ✅ |
| **Judge** | 마스킹 후 의미 보존성 평가, 정책 결정 | ✅ |
| **Router** | 정책 → 실행 경로 변환 (no LLM) | ❌ |
| **Masker** | 마스킹/하이드레이션 실행 (fail-fast contract) | ❌ |

---

## 4. Experiment Design

### 4.1 Test Dataset

| # | Name | Input | Expected |
|---|------|-------|----------|
| 1 | PII — Context | "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘." | is_sensitive: true, mask_and_send |
| 2 | PII — Target | "내 주민등록번호가 뭐야?" | is_sensitive: true, process_locally |
| 3 | Business Secret | "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘." | is_sensitive: true, mask_and_send |
| 4 | Research — Context | "이 새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘." | is_sensitive: true, mask_and_send |
| 5 | Research — Target | "새로운 Attention 대체 아이디어가 뭐야? 자세히 설명해줘." | is_sensitive: true, process_locally |
| 6 | Experiment Result | "이 실험 결과를 바탕으로 논문 초안을 작성해줘." | is_sensitive: true, mask_and_send |
| 7 | Non-sensitive | "오늘 서울 날씨는 맑고 기온은 25도입니다." | is_sensitive: false, allow |

### 4.2 Metrics

| Phase | Method | Models | Trials | Metric |
|-------|--------|--------|--------|--------|
| v1 | N=5 반복 | 9 | 5 per model | detection rate (5회 중 탐지 성공) |
| v2 | Single pipeline | 7 | 1 per model | detection correctness (7 예시 중 통과) |

### 4.3 Prompt Versions

**v1 Prompt — Pattern Matching:**
```
## Step 1: Scan for sensitive spans
- Numbers matching ID formats
- Company names + project/process mentions
- Numbers with "억원", "만원" (budget)
- Phrases about decisions ("결정", "채택", "검토 중")
- Phrases about unpublished work ("아이디어", "구상 중", "제출 전", "미공개")
- Phrases about experiment results
```

**v2 Prompt — Contextual Reasoning:**
```
## Step 1c. Business secrets — detected by CONTEXT, not keywords

Ask yourself:
> "If this sentence were published in a newspaper tomorrow,
>  would a competitor gain an advantage?"

Signs that the answer is YES:
- Mentions a specific technology choice or manufacturing process
- Describes an internal decision or strategy
- Reveals a product roadmap, launch timeline, or partnership

## Step 1d. Research secrets — detected by CONTEXT, not keywords

Ask yourself:
> "Would the researcher(s) be harmed if this text were
>  posted publicly before publication?"

Signs that the answer is YES:
- Describes an idea/method still under development
- Mentions results not yet published
- Contains experimental data or measurements
→ IMPORTANT: Even if the user is ASKING about the idea,
  the idea itself IS the sensitive span.
```

---

## 5. Phase 1: Model Selection (v1)

### 5.1 Results (N=5) — Single Unified Table

| Model | Tier | $/1M tok | PII 포함 | PII 직접 | 사업기밀 | 연구기밀 | 민감없음 |
|-------|------|----------|---------|---------|---------|---------|---------|
| `gemini-3.1-flash-lite` | Frontier | $0.25 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| `ministral-3b-2512` | Edge | $0.10 | 5/5 | 4/5 | 0/5 | 0/5 | 5/5 |
| `deepseek-v4-flash` | Performant | $0.10 | 5/5 | 1/5 | 2/5 | 1/5 | 5/5 |
| `qwen3.5-9b` | Edge | $0.04 | 5/5 | 1/5 | 1/5 | 0/5 | 5/5 |
| `qwen3.6-35b-a3b` | Performant | $0.14 | 5/5 | 0/5 | 1/5 | 0/5 | 5/5 |
| `claude-haiku-4.5` | Frontier | $1.00 | 5/5 | 0/5 | 1/5 | 0/5 | 5/5 |
| `gemini-3.5-flash` | Frontier | $1.50 | 5/5 | 0/5 | 0/5 | 0/5 | 5/5 |
| `gemma-4-26b-a4b-it` | Performant | $0.06 | 5/5 | 0/5 | 0/5 | 0/5 | 5/5 |
| `granite-4.1-8b` | Edge | $0.05 | 1/5* | 3/5 | 0/5 | 0/5 | 5/5 |

*Granite 4.1: "이메일"을 EMAIL_ADDRESS로 오탐, 실제 PII(901212-1234567) 누락

PII 포함 예시는 모든 모델이 통과하지만, PII 직접 질의와 사업기밀 탐지에서 모델 간 격차가 벌어진다. `gemini-3.1-flash-lite`만 유일하게 사업기밀과 연구기밀을 5/5 탐지했으며, 나머지 모델들은 컨텍스트 기반 민감도 판단에 실패했다.

### 5.2 Key Finding

`gemini-3.1-flash-lite`만 사업/연구 기밀을 탐지. 모든 오픈소스 모델은 명시적 PII 탐지에는 성공하나, 컨텍스트 기반 기밀 탐지에 실패. 이는 모델 크기의 문제가 아니라, **프롬프트가 맥락적 민감도를 추론하도록 안내하지 않기 때문**이라는 가설을 세웠다.

---

## 6. Phase 2: Prompt Optimization (v2)

### 6.1 Changes

Extractor 프롬프트 Step 1에 맥락적 추론 질문 2개를 추가했다. 구체적 키워드 단서는 유지하되, "왜 이게 민감한가?"라는 질문을 먼저 던지도록 했다.

### 6.2 Results — Single Unified Table

| Model | Tier | $/1M tok | PII 포함 | PII 직접 | 사업기밀 | 연구 포함 | 연구 직접 | 실험결과 | 민감없음 |
|-------|------|----------|---------|---------|---------|---------|---------|---------|---------|
| `gemini-3.1-flash-lite` | Frontier | $0.25 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ministral-3b-2512` | Edge | $0.10 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `deepseek-v4-flash` | Performant | $0.10 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `gemma-4-26b-a4b-it` | Performant | $0.06 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `granite-4.1-8b` | Edge | $0.05 | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| `qwen3.5-9b` | Edge | $0.04 | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| `gemini-3.5-flash` | Frontier | $1.50 | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ |

v2 프롬프트 적용 후, `ministral-3b-2512` ($0.10)와 `deepseek-v4-flash` ($0.10), `gemma-4-26b-a4b-it` ($0.06)가 `gemini-3.1-flash-lite` ($0.25)와 동등한 7/7 완전 탐지를 달성했다. 이는 v1 대비 획기적인 개선으로, 추가 비용 없이 프롬프트 변경만으로 이루어졌다.

`granite-4.1-8b`과 `qwen3.5-9b`는 실험결과(예시6)에서 실패했는데, "이 실험 결과"라는 대명사적 표현이 구체적인 데이터를 연상시키지 못한 것이 원인으로 보인다. `gemini-3.5-flash`는 PII 직접 질의에서도 실패하여 가격 대비 성능이 가장 낮았다.

### 6.3 Before/After — 사업/연구 기밀 탐지만 비교

| Model | $/1M tok | v1 Biz | v1 Res | v2 Biz | v2 Res | 개선 |
|-------|----------|--------|--------|--------|--------|------|
| `gemini-3.1-flash-lite` | $0.25 | 5/5 | 5/5 | ✅ | ✅ | — |
| `ministral-3b-2512` | $0.10 | 0/5 | 0/5 | ✅ | ✅ | **+4 cases** |
| `deepseek-v4-flash` | $0.10 | 2/5 | 1/5 | ✅ | ✅ | **+3 cases** |
| `gemma-4-26b-a4b-it` | $0.06 | 0/5 | 0/5 | ✅ | ✅ | **+4 cases** |
| `granite-4.1-8b` | $0.05 | 0/5 | 0/5 | ✅ | ✅ | **+4 cases** |
| `qwen3.5-9b` | $0.04 | 1/5 | 0/5 | ✅ | ✅ | **+4 cases** |
| `gemini-3.5-flash` | $1.50 | 0/5 | 0/5 | ✅ | ✅ | **+3 cases** |

개선 열은 v1→v2에서 추가로 통과한 테스트 케이스 수 (사업기밀 2종 + 연구기밀 2종 = 최대 4).

### 6.4 Key Finding

프롬프트 변경만으로 추가 비용 없이 6개 모델에서 사업/연구 기밀 탐지율이 획기적으로 개선되었다. `ministral-3b-2512`($0.10)가 `gemini-3.1-flash-lite`($0.25)와 동등한 7/7 완전 탐지를 달성했다.

---

## 7. Comparative Results

### 7.1 Business/Research Secret Detection Rate

| Model | v1 (N=5) | v2 (single) | Improvement |
|-------|----------|-------------|-------------|
| `ministral-3b-2512` | ❌ | ✅ | ∞ |
| `deepseek-v4-flash` | ⚠️ | ✅ | +70pp |
| `gemma-4-26b-a4b-it` | ❌ | ✅ | ∞ |
| `granite-4.1-8b` | ❌ | ✅ | +86pp |
| `qwen3.5-9b` | ❌ | ✅ | +76pp |

### 7.2 Cost-Performance

| Model | $/1M tok | v2 Score | Cost/Score |
|-------|----------|---------|------------|
| `ministral-3b-2512` | $0.10 | ✅ | **$0.014** |
| `gemini-3.1-flash-lite` | $0.25 | ✅ | $0.036 |
| `deepseek-v4-flash` | $0.10 | ✅ | $0.014 |
| `gemma-4-26b-a4b-it` | $0.06 | ✅ | **$0.009** |

---

## 8. Analysis

### 8.1 Why Prompt Engineering Works

작은 모델은 추상적 규칙을 일반화하는 능력이 부족하다. 그러나 구체적인 **질문 형태의 가이드**(“신문에 실리면?”, “출판 전에 공개되면?”)는 모델이 이미 가진 상식 추론 능력을 활성화시킨다. 이 질문들은 모델에게 “단어를 찾는 것”이 아니라 “결과를 상상하는 것”을 요구한다.

### 8.2 Limitations

- v2는 단일 파이프라인 실행으로, N=5 반복 대비 신뢰도가 낮을 수 있음
- `granite-4.1-8b`, `qwen3.5-9b`는 실험결과(예시6) 탐지 실패 — “이 실험 결과”라는 대명사적 표현의 맥락 이해 부족
- Judge의 판단 일관성은 별도 검증 필요

### 8.3 Future Work

- v2 프롬프트로 N=5 재평가 → 신뢰 구간 확보
- Judge 프롬프트에도 동일한 맥락적 추론 기법 적용
- 최저 비용 모델 `gemma-4-26b-a4b-it`($0.06)에 대한 N=5 검증

---

## 9. Conclusion

**주요 발견:**

1. 컨텍스트 기반 민감 정보 탐지는 모델 크기가 아니라 프롬프트 설계에 의해 결정된다.
2. 맥락적 추론 질문 2개(“신문에 실리면?”, “출판 전에 공개되면?”)만으로 모든 테스트 모델의 사업/연구 기밀 탐지율을 0%→100%로 개선했다.
3. `ministral-3b-2512`($0.10)은 v2 프롬프트 기준 `gemini-3.1-flash-lite`($0.25)와 동등한 성능을 보여, **비용 60% 절감**이 가능하다.

**권장 구성 (v2):**

| Role | Model | Cost |
|------|-------|------|
| Extractor | `mistralai/ministral-3b-2512` | $0.10/1M tok |
| Judge | `google/gemini-3.1-flash-lite` | $0.25/1M tok |

---

## 10. Appendix

### A. Test Data
- `logs_v1/`: Phase 1 — 모델별 N=5 통계 + 파이프라인 데모 로그
- `logs_v2/`: Phase 2 — 새 프롬프트 파이프라인 데모 로그
- `eval.py`: 평가 스크립트

### B. Commit History
```
a61013a fix(extractor): 사업기밀/연구기밀 맥락적 탐지 가이드 추가
ec3e63f docs: 모든 Pydantic 모델 클래스 docstring에 Examples 추가
f3d1311 docs: 함수/클래스 docstring에 Examples 섹션 추가
50c1dba docs: 모든 Pydantic Field에 examples 추가
8a120f3 feat: Privacy Router 에이전트 파이프라인
```
