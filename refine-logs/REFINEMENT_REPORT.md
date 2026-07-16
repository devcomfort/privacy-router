# Refinement Report

**Problem:** Future research direction for Privacy Router
**Initial approach:** Stateful disclosure control
**Date:** 2026-07-13
**Rounds:** 5 / 5
**Last numerical score:** 8/10
**Final verdict:** READY at proposal level after applying the final reviewer’s sole specified revision

## Problem Anchor

Prevent context-dependent sensitive information from leaking through LLM-agent egress while preserving real task completion.

## Output Files

- Final proposal: `refine-logs/FINAL_PROPOSAL.md`
- Timestamped proposal: `refine-logs/FINAL_PROPOSAL_20260713-000000.md`
- Review summary: `refine-logs/REVIEW_SUMMARY.md`
- Round reviews: `refine-logs/round-1-review.md` through `round-5-review.md`
- Score history: `refine-logs/score-history.md`

## Score Evolution

| Round | Problem | Novelty | Mechanism/Scope | Experiment | Feasibility | Overall | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | — | — | — | — | — | 5 | REVISE |
| 2 | 8 | 6 | 8 | 6 | 6 | 6 | REVISE |
| 3 | 9 | 8 | 8 | 8 | 8 | 8 | REVISE |
| 4 | — | 5 | 4 | 6 | — | 5 | REVISE |
| 5 | 9 | 10 | 10 | 8 | 9 | 8 | REVISE: one blocker |
| Final edit | — | — | — | — | — | not re-scored | READY by explicit reviewer condition |

Dashes indicate that the reviewer did not issue that dimension in a comparable numeric form.

## Final Proposal Snapshot

- Primary contribution: Cumulative disclosure benchmark and empirical failure study.
- Measured object: unauthorized recipient-fact first disclosure across heterogeneous agent egresses.
- Utility contract: final closed-loop task success, not response fluency or schema validity alone.
- Reference system: stateful disclosure controller with recipient-purpose semantic enforcement state and deterministic actions.
- RQ2 comparison: method-specific thresholds calibrated to the same benign FPR before test.
- Novelty claim: conditional on a source-quoted independent prior-art gate; otherwise pivot to replication/failure analysis.

## Method Evolution Highlights

1. Replaced “least disclosure” and mechanism-first novelty with benchmark-first empirical measurement.
2. Replaced single-request sensitivity with recipient-purpose-partitioned cumulative semantic facts.
3. Replaced proxy utility with deterministic closed-loop task success and non-inferiority bounds.
4. Removed external hydration rather than expanding the trusted computing base.
5. Added matched-FPR calibration to make cumulative-recall comparisons causally interpretable.

## Pushback / Drift Log

| Round | Reviewer Said | Author Response | Outcome |
|---|---|---|---|
| 1 | Claim a new least-disclosure mechanism only with stronger formalism | Rejected the unnecessary formal claim; narrowed to empirical control | Accepted simplification |
| 2 | Make hydration a fully mediated egress | Initially accepted | Exposed excessive TCB complexity |
| 4 | Specify distributed anti-replay/rollback/transport details | Removed external hydration from the research mechanism instead | Better anchor fidelity |
| 4 | Novelty requires more than one-paper anticipation | Expanded gate to text, code, explicit combinations, and obviousness | Accepted |
| 5 | Fixed-FPR wording needs actual matched operating points | Added method-specific calibration to the same target FPR | Resolved |

## Remaining Weaknesses

- The literature gap is not established until the claim-chart gate completes.
- Human annotation and adjudication are expensive.
- Deterministic mock tools strengthen internal validity but limit ecological validity.
- Several 2026 papers may not yet expose code/data; reconstruction fidelity must be reported honestly.
- A conservative state ledger may reduce utility under send failures.

## Next Step

Run `/experiment-plan` using `refine-logs/FINAL_PROPOSAL.md`. The first experiment-plan phase must execute the prior-art kill gate before allocating benchmark construction work.
