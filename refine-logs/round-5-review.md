# Round 5 Review

**Initial verdict:** REVISE with one narrow proposal blocker
**Scores:** Problem 9; Novelty discipline 10; Scope/mechanism 10; Experiment credibility 8; Feasibility 9; Overall 8.

## Sole Proposal Blocker

RQ2 asked for recall “at fixed benign FPR,” but the draft only said that thresholds were frozen on a disjoint calibration split. Different methods can have different score distributions; without method-specific threshold selection targeting the same benign FPR, an apparent recall gain could result from operating at a higher false-positive rate.

The reviewer offered two coherent choices:

1. matched-FPR evaluation, where each method selects its own threshold on calibration data to target the same predeclared benign FPR; or
2. remove fixed-FPR language and report unmatched operating points/Pareto dominance.

## Final Resolution

The final proposal adopts the matched-FPR version:

- each method selects its threshold only on a disjoint calibration split;
- every method targets the same predeclared benign FPR;
- thresholds are frozen before test evaluation;
- a discrete score uses the conservative point at or below the target;
- achieved test FPR, recall, and task success are all reported.

The reviewer explicitly stated that no other proposal-level issue blocked implementation and that this narrow revision would make the direction READY. The revision was applied after the fifth and final review round.

**Final status after applying the sole blocker:** READY at proposal level. The prior-art gate can still force the planned benchmark/replication pivot.
