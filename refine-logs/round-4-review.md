# Round 4 Review

**Verdict:** REVISE
**Overall score:** 5/10

## Why the Proposal Regressed

The attempt to satisfy every protocol-level concern overbuilt the proposal. A studentized log-risk-ratio bootstrap introduced sparse-count edge cases; the Monte-Carlo power procedure became too specific without being fully executable; and hydration expanded into a cryptographic distributed-systems protocol with concurrency, rollback, replica, clock, transport, and payload-binding obligations.

The novelty rule was also too narrow because it killed the claim only when one prior implementation contained all elements. It needed to cover textual disclosure, paper+code evidence, explicit cross-reference combinations, and obvious composition.

## Main Blocking Themes

- undefined sparse-count statistics;
- discretionary baseline/calibration details;
- ambiguous opportunity scoring and intention-to-treat rules;
- cumulative-state reservation not atomic with hydration;
- external hydration TCB far larger than the research anchor;
- anticipation-only novelty standard.

## Author Pushback and Simplification

The protocol-level expansion no longer served the original research problem. The next revision therefore:

1. Pivoted the primary contribution from a novel controller to a benchmark and empirical failure study.
2. Used paired absolute effects rather than sparse risk ratios.
3. Removed external cleartext hydration; local UI restoration only.
4. Kept the stateful disclosure controller as an explicitly non-novel reference system for comparisons and ablations.
5. Strengthened the novelty gate to include anticipation, implementation, explicit combination, and obviousness.
