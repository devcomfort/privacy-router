# Round 1 Review

**Verdict:** REVISE
**Overall score:** 5/10

## Strongest Rejection

The initial least-disclosure proposal read as a composition of contextual-integrity tuples, egress interposition, data-minimizing rewriting, local/remote delegation, provenance/history tracking, and policy action selection rather than a demonstrated new privacy mechanism. “Least disclosure” was unsupported: per-atom deletion did not establish joint minimality, schema validity was not task executability, and LLM entailment could not be treated as a deterministic security invariant.

## Main Blocking Issues

1. Mechanism novelty collided with DelegateCI-Bench, ToolPrivacyBench, PAPILLON/PUPA, PRISM, RTBAS, and classical reference-monitor/DLP ideas.
2. Gold necessity/policy inputs risked making the experiment an oracle evaluation rather than a deployable system comparison.
3. Record/replay and local verifier proxies did not establish closed-loop task utility.
4. Threat model, supported sinks, recipient identity, retention, and cumulative-state semantics were underspecified.
5. The evaluation lacked a power-grounded paired design and fair capability/cost-matched baselines.

## Revision Triggered

- Removed “least/minimal,” lattice, formal noninterference, and generic reference-monitor claims.
- Reframed semantic entailment and executability as empirical estimators.
- Added independently authored deployable contracts, explicit threat boundaries, closed-loop tasks, matched baseline capabilities, and task-level privacy/utility endpoints.
