# Detection

## Socratic Sensitivity Detection Framework

Extractor가 민감 정보를 탐지하는 프레임워크입니다. Socratic 민감도 탐지를 통해 AI가 민감한 이유를 스스로 설명하고 카테고리를 동적으로 생성합니다.

### 핵심 원칙

> **"이 정보에 기밀 가치가 조금이라도 있으면 마스킹합니다."**

의심스러우면 마스킹하세요. 일반적 개념이나 기관명이라도 민감한 맥락에 있으면 태깅합니다.

---

## Socratic Chain (3단계 질문)

Extractor는 각 문장에 대해 다음 질문을 **순서대로** 적용합니다. 첫 "YES"에서 멈춥니다:

### Question 1: Identity Exposure (식별 노출)
> "이 문장에 특정 개인을 식별할 수 있는 정보가 있는가?"

- 주민등록번호, 전화번호, 이메일, 여권번호, 이름+소속기관 쌍
- 민감 정보 자체를 **언급하는 것**도 민감 ("주민등록번호가 뭐야?" → 태그)

### Question 2: Competitive Harm (경쟁 해악)
> "이 정보가 경쟁사에게 유용한가?"

- 미공개 연구 (아이디어, 방법론, 데이터, 진행 상태)
- 내부 사업 결정, 전략 근거, 제조 로드맵
- 심각도: **방법론(HOW) > 아이디어(WHAT) > 진행 상태(STATUS)**

### Question 3: Personal Harm (개인 해악)
> "이 정보가 공개되면 누군가에게 실제 해가 되는가?"

- 자격 증명, 내부 URL, 연봉, 예산

---

## Socratic Category Derivation (카테고리 유도)

> **프롬프트별 접근법 차이:**
> - `extract.prompt` (기본): 소크라테스 질문으로 카테고리를 **동적 유도**
> - `extract.socratic.prompt` (CoT): 18개 **고정 카테고리** 사용 (절대 새로 생성하지 않음)

각 span에 대해 다음 질문을 스스로에게 던지고, 답변을 종합하여 **카테고리 이름**을 만듭니다:

### 질문 1: 이 정보의 핵심 속성은 무엇인가?
> "이 정보가 가진 가장 두드러진 특성은?"

### 질문 2: 이 정보가 왜 민감한가?
> "이 정보가 노출되면 어떤 피해가 있는가?"

### 질문 3: 이 정보를 한 단어로 표현하면?
> "이 정보의 본질을 가장 잘 나타내는 이름은?"

### 카테고리 이름 생성 규칙

1. **SCREAMING_SNAKE_CASE**로 작성 (예: `RESIDENT_REGISTRATION_NUMBER`, `UNPUBLISHED_RESEARCH_CONCEPT`)
2. **구체적으로** 작성 (예: `BATTERY_MATERIAL_RESEARCH`而不是 `UNPUBLISHED_RESEARCH`)
3. **고유하게** 작성 (같은 텍스트에서 같은 카테고리 이름 사용)
4. 기존 예시에 없는 새로운 유형이라도 소크라테스 질문으로 유도

### 카테고리 유도 예시

| span | 질문 1 | 질문 2 | 질문 3 | 카테고리 |
|------|--------|--------|--------|----------|
| "<personal-id>" | 개인 식별 번호 | 신원 노출 | 주민등록번호 | `RESIDENT_REGISTRATION_NUMBER` |
| "<person-name>" | 개인 실명 | 신원 노출 | 이름 | `PERSON_NAME` |
| "<unpublished-research-concept>" | 연구 주제 | 경쟁 우위丧失 | 연구 개념 | `UNPUBLISHED_RESEARCH_CONCEPT` |
| "<fabrication-process-decision>" | 제조 공정 결정 | 기술 유출 | 공정 선택 | `FABRICATION_PROCESS_DECISION` |
| "<project-budget>" | 예산 금액 | 재정 노출 | 예산 | `PROJECT_BUDGET_AMOUNT` |
| "<api-credential>" | 인증 키 | 시스템 접근 | 자격증명 | `API_CREDENTIAL` |

---

## Span Rules (추출 규칙)

span은 민감 정보의 **실체만** 포함하는 최소 텍스트 단위입니다.

### 포함 (실체)
- 고유명사: "<organization-name>", "<vendor-name>"
- 숫자/수치: "<personal-id>", "94.2%", "<project-budget>"
- 기술 용어: "<research-concept>", "<fabrication-process-decision>"

### 제외 (문법적 요소)
- 조사: 에, 에서, 을, 를, 이, 가, 은, 는
- 수식어: 새로운, 높은, 긴
- 동사 파생형: 선택하기로, 달성한, 재학 중인

### 예시

| 원문 | ✅ 올바른 span | ❌ 잘못된 span |
|------|--------------|--------------|
| "광주과학기술원에 재학 중인 김동현" | "광주과학기술원", "김동현" | "광주과학기술원에 재학 중인 김동현" |
| "TSMC 3nm 공정 채택 결정" | "TSMC 3nm 공정" | "TSMC 3nm 공정 채택 결정" |

### 여러 엔티티 분리 규칙

하나의 문자열에 여러 민감 정보가 포함되어 있으면 **각각 별도 span**으로 추출합니다:

| 원문 | ✅ 올바른 span | ❌ 잘못된 span |
|------|--------------|--------------|
| "<person-name-1>, <person-name-2>, <person-name-3>" | "<person-name-1>", "<person-name-2>", "<person-name-3>" | "<person-name-1>, <person-name-2>, <person-name-3>" |
| "주민등록번호 <personal-id-1>, <personal-id-2>" | "<personal-id-1>", "<personal-id-2>" | "<personal-id-1>, <personal-id-2>" |

---

## Masking Test (마스킹 테스트)

각 span에 대해 마스킹 테스트를 적용합니다:

> **"이 span을 CATEGORY#hash로 치환했을 때, 원래 질의의 의미가 유지되는가?"**

| 답변 | is_essential | 설명 |
|------|-------------|------|
| 의미 유지됨 | `false` | 민감 정보가 질의의 재료/배경 |
| 의미 손실됨 | `true` | 민감 정보가 질의의 대상/주제 |

### 예외 규칙 (항상 is_essential: true)

- **명시적 비밀유지 마커**: "비밀로 해줘", "공개하지 마"
- **자격증명/내부 URL**: 비밀번호, API 키, `internal.` URL
- **미공개 연구 아이디어/개념**: 아이디어 자체가 핵심 가치

### 마스킹 테스트 예시

| 질의 | 마스킹 후 | is_essential |
|------|----------|-------------|
| "주민번호 포함한 이메일 작성" | "주민번호 [MASKED] 포함한 이메일 작성" | false |
| "내 주민번호가 뭐야?" | "내 [MASKED]가 뭐야?" | true |
| "TSMC 3nm 채택 결정에 대한 보고서" | "[MASKED]에 대한 보고서" | false |
| "새로운 Attention 대체 아이디어 실험" | "새로운 [MASKED] 실험" | true |
| "프로젝트 예산은 850억원" | "프로젝트 예산은 [MASKED]" | false |

---

## 처리 절차 (Steps)

### Step 1: 민감 span 추출
텍스트를 읽고 민감 정보를 찾습니다.

### Step 2: 소크라테스 카테고리 유도
각 span에 대해 3단계 질문을 던지고 카테고리 이름을 만듭니다.

### Step 3: 자기 검토
"놓친 민감 정보가 있는가?" 있다면 추가하세요.

### Step 4: 마스킹 테스트 적용
각 span에 대해 마스킹 테스트를 적용하여 is_essential을 판별합니다.

---

## 고정밀 추출 (High-precision extraction)

`Extractor(precision="high")`는 기본 추출 뒤 Critic 검토를 실행합니다:

1. **기본 추출**: 설정된 추출 모델이 민감 정보를 탐지
2. **Critic 검토**: 같은 공개 API 안에서 1차 결과를 검토하고 누락된 레코드를 보완

---

## Detection Examples

### Personal Information (PII)

**Input:** "주민등록번호 <personal-id>과 연락처 <phone-number>를 기재합니다."

```json
[
  {"category": "RESIDENT_REGISTRATION_NUMBER", "span": "<personal-id>", "confidence": 0.98, "is_essential": false},
  {"category": "MOBILE_PHONE_NUMBER", "span": "<phone-number>", "confidence": 0.95, "is_essential": false}
]
```

**Judge:** `is_essential: false` → **Mask & Send** — the request is "list my info", masking preserves meaning.

### Business Secrets

**Input:** "삼성전자 차세대 AP 개발 건으로, TSMC 3nm 공정을 채택하기로 내부적으로 결정했다."

```json
[
  {"category": "COMPANY_PROJECT_NAME", "span": "삼성전자 차세대 AP 개발 건", "confidence": 0.91},
  {"category": "FABRICATION_PROCESS_DECISION", "span": "TSMC 3nm 공정", "confidence": 0.94},
  {"category": "INTERNAL_BUSINESS_DECISION", "span": "내부적으로 결정", "confidence": 0.92}
]
```

**Judge:** `is_essential: false` → **Mask & Send** — the request is "write a report", not "tell me the decision".

### Research Secrets

**Input:** "Attention 메커니즘을 완전히 대체할 수 있는 새로운 아이디어를 구상 중이다."

```json
[
  {"category": "UNPUBLISHED_RESEARCH_CONCEPT", "span": "Attention 메커니즘을 완전히 대체할 수 있는 새로운 아이디어", "confidence": 0.91}
]
```

**Judge:** `is_essential: true` → **Route to Local LLM** — the idea IS the question.

### Contrast: When `is_essential` is true

**Input:** "내 주민등록번호가 뭐야?"

Same SSN detected, but `is_essential: true` — the SSN IS the question. **Route to Local LLM** — no data leaves the network.

---

## Output Format

```json
{
  "sensitivity": {
    "is_sensitive": true,
    "rationale": "민감 정보 포함 여부와 이유 (한 문장)"
  },
  "records": [
    {
      "category": "SCREAMING_SNAKE_CASE_NAME",
      "span": "추출된 최소 단위",
      "confidence": 0.95,
      "reasoning": "왜 이게 민감한지 한 줄 설명",
      "is_essential": false
    }
  ]
}
```

민감 정보가 없으면: `{"sensitivity": {"is_sensitive": false, "rationale": "민감 정보 없음"}, "records": []}`

---

## Related Documents

- [Architecture](/docs/architecture) — how detection fits in the pipeline
- [Masking & Hydration](/docs/masking) — what happens after detection
- [Security](/docs/security) — threat model and encryption
