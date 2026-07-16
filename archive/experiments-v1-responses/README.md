# Response Analysis Results

Generated: 2026-06-22

## Contents

- `analysis_summary.json` — Machine-readable summary of all 17 test cases
- `*.json` — Individual raw model responses for each test case
- `FINDINGS.md` — Detailed analysis of failure patterns and prompt improvements
- `prompt_improvements.prompt` — Ready-to-use improved prompt variant

## Quick Stats

| Metric | Value |
|--------|-------|
| Overall Accuracy | 70.6% (12/17) |
| Detection (sensitive/non-sensitive) | 100% (17/17) |
| Action Accuracy | 70.6% (12/17) |
| Contextual Accuracy | 55.6% (5/9) |

## Key Finding

The model achieves **100% sensitivity detection** but fails on **is_essential judgment** for 5 cases. All failures are WRONG_ACTION — the model correctly identifies content as sensitive but misclassifies whether it can be masked.

## Files

### Summary
- `analysis_summary.json` — Full metrics and failure list

### Failing Cases (5)
- `내부URL.json` — Internal URL marked non-essential (should be block)
- `이름+소속.json` — Research topic marked essential (should be selective_mask)
- `사업비밀creation.json` — Business decision marked essential (should be selective_mask)
- `모호한실험결과creation.json` — Vague experiment reference marked essential (should be selective_mask)
- `미공개상태.json` — Unpublished idea marked essential (should be selective_mask)

### Passing Cases (12)
- Morphological: `PII 포함creation.json`, `PII 직접interrogation.json`, `전화번호포함creation.json`
- Contextual: `연구아이디어consultation.json`, `전략근거statement.json`, `연구방법론consultation.json`, `프로젝트예산statement.json`, `비밀유지마커.json`
- Mixed: `다중span+혼합동사.json`
- None: `일반날씨.json`, `일반지식.json`, `일반창업조언.json`

## Prompt Improvements

See `FINDINGS.md` for detailed analysis. Key changes:

1. **Topic vs. Content distinction** — Clarify when a sensitive topic is context vs. content
2. **Fewshot examples** — Add examples showing selective_mask for contextual cases
3. **Internal URL rule** — Explicit rule that internal URLs are always essential
4. **Self-check guidance** — Add specific checks for is_essential judgment

## Expected Impact

If improvements are applied:
- Contextual accuracy: 55.6% → 77.8% (7/9 correct)
- Overall accuracy: 70.6% → 82.4% (14/17 correct)
