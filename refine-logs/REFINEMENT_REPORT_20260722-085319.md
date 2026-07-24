# Refinement Report

**Date:** 2026-07-22\
**Initial question:** Can Privacy Router become an academically defensible paper, and how should detection, masking, routing, and a new dataset be evaluated?\
**Final status:** research direction selected; validity pilot approved; confirmatory study not yet approved.

## 1. Initial Direction

The initial direction treated Privacy Router's contextual extraction, typed masking, and local/external routing as the main method contribution. Existing evidence consisted of:

- 27 Korean benchmark cases and 48 annotated spans
- historical real-LLM model sweeps
- software unit and integration tests
- 46 organic Hermes usage records containing operational metadata but no prompt payloads

This evidence can validate implementation behavior and motivate deployment, but it cannot establish a publishable privacy or model-quality claim.

## 2. Novelty Reassessment

Recent work already covers:

- local/cloud privacy delegation: PAPILLON and PRISM-style routing
- task-essential disclosure and rewriting: Need to Know
- multilingual PII redaction: REDACT
- contextual PII redaction: RedactionBench
- tool recipient/purpose privacy: ToolPrivacyBench
- agent privacy-flow evaluation: AgentSCOPE
- human contextual privacy judgments: PrivacyAlign
- cumulative multi-turn disclosure: RootGuard and Dependency-Aware Privacy

Therefore the method-level novelty claim was rejected.

## 3. Final Research Contribution

The selected contribution is a bilingual evaluation/resource paper:

> Controlled interventions over disclosure state, recipient authorization, purpose authorization, and raw-value necessity for personal, organizational, research, and credential information at an LLM-agent candidate egress decision.

Novelty remains conditional on a full artifact audit. Privacy Router is a reference implementation, not a new privacy primitive.

## 4. Major Design Changes

1. Replaced broad privacy claims with a narrow organizational/research confidentiality gap.
2. Replaced causal language with controlled-intervention sensitivity.
3. Separated factual labels from policy-derived actions under profile $P_0$.
4. Separated model-visible input from gold metadata.
5. Defined a semantic-scenario hierarchy to prevent pseudo-replication.
6. Expanded leakage from character matching to literal, proposition, derived, recipient, and placeholder-side-channel measurements.
7. Split transformation-only utility from full routing/model utility.
8. Changed C1 to one frozen same-backbone comparison at one dev-selected threshold with achieved test FPR.
9. Changed C3 to a joint leakage-superiority and task-utility non-inferiority test against a strong privacy-aware baseline.
10. Added shared-threshold EN/KO analysis, independent authoring, semantic-equivalence and naturalness validation.
11. Added abstention burden and eventual completion, not only residual risk.
12. Recalculated the planning envelope to 400 semantic scenarios, 2,600–2,800 items, and 300–500 person-hours.

## 5. What Existing Assets Can Support

| Asset | Valid use | Invalid use |
|---|---|---|
| 27-case ground truth | schema prototype and smoke evaluation | paper-scale accuracy claim |
| Historical model sweeps | model shortlist and engineering history | final benchmark result after prompt/test reuse |
| Unit/integration tests | masking, streaming, fail-closed software correctness | contextual detection quality |
| 46 usage logs | route/latency/token/action workload metadata | real-world semantic privacy accuracy |
| OpenAI-compatible API + MCP | reference-system integration study | proof of privacy guarantee |
| EN/KO web/docs | dissemination and bilingual product support | evidence of bilingual model robustness |

## 6. Research Questions

- **RQ1:** Does contextual control improve organizational/research protected-span recall at a frozen safe-FPR threshold?
- **RQ2:** Which boundary, disclosure, authorization, necessity, atom, or policy component conditionally explains action errors?
- **RQ3:** Does the full system reduce unauthorized exposure against a strong privacy-aware baseline while maintaining task success within a −5pp margin?
- **RQ4:** What failure gap appears under a shared threshold across translated and independently authored EN/KO scenarios?
- **RQ5:** Does calibrated ask-user deferral improve selective risk after accounting for user burden and eventual completion?

## 7. Decision Gates

- **G0:** full artifact novelty audit
- **G1:** 80–120-item pilot agreement, intervention validity, lexical-shortcut, realism, and bilingual gates
- **G2:** policy/schema/model-view and dataset hierarchy freeze
- **G3:** known-answer evaluator correctness
- **G4:** primary method/comparator/threshold/statistics freeze
- **G5:** detector, oracle, end-to-end, and masking evidence
- **G6:** human utility validation, failure audit, release artifacts

## 8. Final Recommendation

Proceed to the validity pilot only. The current plan is potentially publishable as ACL/EMNLP Findings if the narrow novelty survives G0, the pilot validates the constructs, and C1/C3 obtain confirmatory evidence. PETS remains conditional on a stronger policy and threat model. A method-first or top-security claim is not defensible at present.
