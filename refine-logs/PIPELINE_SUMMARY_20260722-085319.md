# Pipeline Summary

**Direction:** Beyond PII — controlled-intervention evaluation of context-dependent confidential data control at LLM-agent egress\
**Reviewer verdict:** **GO_TO_PILOT (8/10)**\
**Evidence status:** no proposed paper claim has been experimentally established

## Final Positioning

- Do **not** claim Privacy Router's extractor–masker–router architecture as a new privacy mechanism.
- Claim candidate: an EN/KO benchmark for organizational/research confidentiality that separates disclosure state, recipient authorization, purpose authorization, and raw-value necessity.
- Privacy Router is the reference implementation used to study span detection, policy compliance, masking, local/external routing, semantic leakage, utility, latency, and cost.
- Closest overlaps: Need to Know, ToolPrivacyBench, RedactionBench, REDACT, PAPILLON, AgentSCOPE, PrivacyAlign, RootGuard, and Dependency-Aware Privacy.

## Primary Confirmatory Questions

1. **C1:** At one preregistered safe-FPR threshold, does one frozen Privacy Router condition outperform one same-backbone fixed-taxonomy comparator on organizational/research protected-span recall?
2. **C3:** Against one strong privacy-aware comparator, does the system achieve leakage superiority and task-success non-inferiority within −5pp?

C1's practical target is a +10pp point estimate with a positive 95% scenario-cluster CI. C3 uses an intersection–union decision rule. These are hypotheses, not results.

## Evaluation Package

- 400 semantic scenarios
- average 3 controlled variants per scenario
- EN/KO realizations, translated and independently authored subsets
- 200–400 naturalistic/adversarial items
- planning total: 2,600–2,800 items
- factual labels separated from policy-derived actions
- exact/source spans plus proposition-level information atoms
- literal, semantic, derived, recipient, and placeholder-side-channel leakage
- transformation-only and full-system utility experiments
- shared-threshold bilingual analysis
- scenario-cluster bootstrap/permutation and mixed-effects/GEE analysis

## Immediate Run Order

1. **WP0:** artifact-level novelty matrix, licenses/code/venue verification, contextual-integrity and DLP/declassification coverage.
2. **Policy/schema freeze for pilot:** total deterministic $P_0$, closed action tuple, span/atom/event cardinality, trusted inputs, model-view serializer.
3. **Pilot:** 20–30 semantic scenarios × 2 variants × 2 languages = 80–120 items.
4. **Pilot gates:** label-specific AC1, ≥90% blind single-factor validity, lexical shortcut check, bilingual/subgroup validity, realism, scorer reliability, token/call/annotation measurements.
5. **Power and feasibility:** cluster-aware simulation, safe-case FPR precision, API/GPU/annotation budget.
6. Only after G0/G1 pass: full dataset, evaluator, dev selection, frozen hidden test, E2–E9.

## Venue

- **Primary:** ACL/EMNLP Findings — best match for a bilingual benchmark/resource and empirical NLP evaluation.
- **Conditional secondary:** PETS — requires stronger threat/policy model, semantic leakage, practitioner validity, and explicit privacy-versus-organizational-confidentiality framing.
- **Not yet supported:** USENIX Security / IEEE S&P.

## Deliverables

- `FINAL_PROPOSAL.md` — final research framing and claims
- `EXPERIMENT_PLAN.md` — detailed benchmark, metrics, baselines, statistics, run order, and budget
- `EXPERIMENT_TRACKER.md` — gates, run registry, claim status
- `REVIEW_SUMMARY.md` — three external-style review rounds and unresolved conditions
- `REFINEMENT_REPORT.md` — rationale and changes from the initial direction

## Next Action

Complete **WP0 full-text artifact audit**. Do not run another model sweep or start the 2,600–2,800-item benchmark before the policy/schema pilot gates are executable and tested.
