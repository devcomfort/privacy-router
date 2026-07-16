# Review Summary

**Problem:** Define a defensible future research direction for Privacy Router after pattern-based PII, contextual sensitivity detection, task essentiality, and local/cloud routing.
**Initial approach:** A stateful disclosure-control runtime mechanism.
**Date:** 2026-07-13
**Rounds:** 5 / 5
**Last numerical score:** 8/10
**Final proposal-level verdict:** READY after applying the fifth review’s sole specified blocker; no numerical re-score was issued.

## Problem Anchor

How can an LLM-agent privacy layer prevent context-dependent sensitive information from leaking across real multi-turn, multi-tool work while preserving the ability to complete the user’s task?

## Round-by-Round Resolution Log

| Round | Main Reviewer Concerns | What Changed | Solved? | Remaining Risk |
|---|---|---|---|---|
| 1 | “Least disclosure” unsupported; semantic entailment treated as an invariant; oracle policies; broad novelty collision | Removed least/minimal/formal claims; added deployable contracts, closed-loop utility, explicit threat model | Yes | Mechanism differentiation and power |
| 2 | N=300 underpowered; undefined joint estimand; hydration bypass; threshold leakage | Added discarded pilot, task-level paired claims, simultaneous privacy/utility requirements, calibration split | Yes | Joint power and hydration TCB |
| 3 | Six comparison components underspecified; recall denominator unclear; zero risk ratio; novelty gate weak | Defined task-macro opportunities, joint components, power gate, source-quoted claim chart | Partial | Protocol became overbuilt |
| 4 | Sparse bootstrap edge cases; hydration became a distributed-security protocol; anticipation-only novelty rule | Pivoted to benchmark-first contribution; used absolute effects; removed external hydration; strengthened novelty kill rule | Yes | Matched-FPR estimand |
| 5 | Fixed-FPR language did not require equalized operating points | Adopted method-specific calibration thresholds targeting the same predeclared benign FPR | Yes | Prior-art gate may still trigger pivot |

## Overall Evolution

- The work moved from a broad mechanism-novelty claim to a focused benchmark and empirical failure study.
- “Task necessity” remains a utility constraint, not the claimed novelty.
- Recipient-purpose cumulative semantic disclosure became the measured phenomenon.
- The mechanism became a reference controller and ablation vehicle rather than a general security claim.
- External hydration was deleted from the research mechanism; only trusted local UI restoration remains.
- The evaluation now uses closed-loop task success, method-independent disclosure opportunities, matched benign FPR, deployable contracts, and capability/cost-matched baselines.
- Novelty is conditional on a reproducible prior-art gate with an explicit replication/failure-analysis pivot.

## Final Status

- **Anchor status:** Preserved. The project still protects context-dependent sensitive information while keeping tasks executable.
- **Focus status:** Tight. The cumulative disclosure benchmark and evaluation are the primary contribution; the stateful controller is secondary.
- **Modernity status:** Frontier-aware without forcing a new model or training objective.
- **Strongest parts:** benchmark-first framing, recipient-purpose cumulative state, closed-loop utility, matched-FPR comparison, novelty kill discipline.
- **Remaining weaknesses:** annotation cost, synthetic-to-real transfer, baseline reconstruction fidelity, and a possible prior-art pivot.
