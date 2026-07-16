# Response Analysis: Privacy Router — gemma-4-E4B-it

## Run Summary

| Metric | Value |
|--------|-------|
| Prompt | `extract.fewshot.prompt` |
| Model | gemma-4-E4B-it (4B params) |
| Temperature | 0.4 |
| Top-p | 0.7 |
| **Overall Accuracy** | **12/17 (70.6%)** |
| Detection (sensitive/non-sensitive) | **17/17 (100%)** |
| Action accuracy | 12/17 (70.6%) |
| Morphological accuracy | 3/4 (75.0%) |
| **Contextual accuracy** | **5/9 (55.6%)** |
| Mixed accuracy | 1/1 (100%) |
| None (allow) accuracy | 3/3 (100%) |

## Key Finding

**The model achieves 100% sensitivity detection but 0% on the contextual is_essential judgment for failing cases.** All 5 failures are WRONG_ACTION — the model correctly identifies content as sensitive but misclassifies whether it can be masked.

## All 5 Failures: WRONG_ACTION

### Pattern A: Internal URL marked non-essential (1 case)

**Case: 내부URL**
- Input: `https://internal.company.com/project-x 에서 이번 분기 실적 데이터를 확인해줘.`
- Expected: `is_essential: true` → block
- Actual: `is_essential: false` → selective_mask
- Model rationale: "내부 시스템 URL 포함"

The model recognizes this is sensitive (correct) but thinks the URL can be masked. Internal URLs are inherently essential because they reveal internal system architecture and routing information.

### Pattern B: Research/business topic marked essential when it's just context (4 cases)

All 4 contextual failures share the same pattern — the user mentions a sensitive topic as context for a creation/consultation task, and the model incorrectly marks it as essential.

**Case: 이름+소속**
- Input: `광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해.`
- Expected: `is_essential: false` → selective_mask
- Actual: `is_essential: true` → block
- Model span: `contextual distillation이라는 연구`
- Model reasoning: "구상 중인 연구 주제 언급"

**Case: 사업비밀(creation)**
- Input: `TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘.`
- Expected: `is_essential: false` → selective_mask
- Actual: `is_essential: true` → block
- Model span: `TSMC 3nm 공정 채택 결정`
- Model reasoning: "기업의 전략적 결정 사항 언급"

**Case: 모호한실험결과(creation)**
- Input: `이 실험 결과를 바탕으로 논문 초안을 작성해줘.`
- Expected: `is_essential: false` → selective_mask
- Actual: `is_essential: true` → block
- Model span: `이 실험 결과`
- Model reasoning: "아직 공개되지 않은 연구 결과에 대한 언급"

**Case: 미공개상태**
- Input: `아직 논문에 제출하지 않은 연구 아이디어를 정리해줘.`
- Expected: `is_essential: false` → selective_mask
- Actual: `is_essential: true` → block
- Model span: `아직 논문에 제출하지 않은 연구 아이디어`
- Model reasoning: "미공개 연구 아이디어에 대한 언급"

## Contrast with Passing Cases

The model IS capable of correct is_essential judgments — it passes on 12/17 cases including sensitive ones:

**Correct block (is_essential=true):**
- 연구아이디어: "새로운 Attention 대체 아이디어를 바탕으로 실험 설계를 도와줘" — the specific idea IS the content of the request
- 전략근거: "TSMC 대신 삼성 파운드리를 선택하기로 결정했어" — the decision and reasoning are inseparable
- 프로젝트예산: "프로젝트 블루스카이 예산은 1,200억원" — specific numbers ARE the sensitive content

**Correct selective_mask (is_essential=false):**
- PII 포함: "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘" — PII is a tool for the task, not the task itself
- 전화번호포함: "hong@example.com, 010-1234-5678" — contact info is context, not the goal

## Root Cause

The model applies a **binary heuristic** for contextual content: "if it's sensitive, mark it essential."

The correct logic is more nuanced:
- **Content** = what the user wants to discuss/review → essential
- **Context** = what the user mentions to frame their request → not essential

The prompt's masking test exists ("이 span을 [MASKED]로 치환하면 원래 질의 의미가 유지되는가?") but the fewshot examples don't demonstrate this distinction for contextual cases. The model only sees:
- Example 1: PII → is_essential: false (easy morphological case)
- Example 2: Research idea → is_essential: true (no context-only example)

## Specific Prompt Improvements

### 1. Add a "topic vs. content" clarification to the Masking Test section

Current masking test is abstract. Add concrete guidance:

```
### Masking Test (for is_essential)
- "이 span을 [MASKED]로 치환하면 원래 질의 의미가 유지되는가?"
- YES, meaning preserved → is_essential: false
- NO, meaning lost → is_essential: true
- Explicit markers ("비밀로 해줘", "공개하지 마") → ALWAYS is_essential: true

**Topic vs. Content distinction:**
- User asks to WRITE/CREATE about a topic → topic is context → is_essential: false
- User asks to DISCUSS/REVIEW the topic itself → topic is content → is_essential: true
- User STATEMENTS a fact as their message → fact is content → is_essential: true
```

### 2. Add fewshot examples showing selective_mask for contextual cases

The current 3 examples are:
1. Morphological PII → selective_mask ✓
2. Research idea (consultation) → block ✓
3. No sensitivity → allow ✓

Add 2 contextual examples that should be selective_mask:

```
### Example 4
Input: "TSMC 3nm 공정 채택 결정에 대한 보고서를 작성해줘."
Output:
{
  "sensitivity": {"is_sensitive": true, "rationale": "미공개 사업 결정"},
  "records": [
    {"category": "BUSINESS_SECRET", "span": "TSMC 3nm 공정 채택 결정", "confidence": 0.94, "reasoning": "미공개 제조 결정", "is_essential": false}
  ]
}

### Example 5
Input: "광주과학기술원에 재학 중인 김동현인데, contextual distillation이라는 연구를 하려고 해."
Output:
{
  "sensitivity": {"is_sensitive": true, "rationale": "개인 식별 정보 및 연구 아이디어"},
  "records": [
    {"category": "PERSONAL_NAME", "span": "김동현", "confidence": 0.95, "reasoning": "개인 식별 정보", "is_essential": false},
    {"category": "AFFILIATION", "span": "광주과학기술원", "confidence": 0.90, "reasoning": "소속 기관", "is_essential": false},
    {"category": "UNPUBLISHED_RESEARCH_CONCEPT", "span": "contextual distillation이라는 연구", "confidence": 0.88, "reasoning": "구상 중인 연구 주제", "is_essential": false}
  ]
}
```

### 3. Add explicit rule for internal URLs

The prompt lists internal URLs in morphological patterns but doesn't clarify they should be essential:

```
### Internal URLs (always essential)
- Internal URLs (https://internal.*, https://*.local) → ALWAYS is_essential: true
- They reveal internal system architecture and project identifiers
- Masking them loses routing information entirely
```

### 4. Add self-check step for is_essential

The self-check prompt exists but doesn't specifically address this failure pattern:

```
## Self-Check for is_essential

Before assigning is_essential: true, verify:
1. Is this span the CORE of what the user wants, or just CONTEXT?
2. If I mask this span, can the user still accomplish their goal?
3. Is the user REVEALING this information, or just MENTIONING it?

If #2 is YES or #3 is "mentioning" → is_essential: false
```

## Expected Impact

If these prompt changes are applied:
- The 4 contextual Pattern B failures should be fixed (selective_mask instead of block)
- Contextual accuracy: 55.6% → 77.8% (7/9 correct)
- Overall accuracy: 70.6% → 82.4% (14/17 correct)
- Morphological accuracy should be maintained at 75%+ (internal URL fix is separate)

## Next Steps

1. Implement prompt improvements in a new variant (e.g., `extract.fewshot+topic-context.prompt`)
2. Run 5 trials with the improved prompt to measure consistency
3. Monitor for false positives — the model should not become too permissive on sensitive content
4. Consider adding more test cases that explicitly test the topic/content boundary
