# Privacy Router source-native pilot protocol

## Purpose

This pilot validates source adapters, gold-label boundaries, egress capture, and scoring before any benchmark-size decision or paper claim. It is a systems-validity exercise, not a performance comparison.

The pilot implements the approved layered source-native design in `2026-07-25-source-native-evaluation-corpus-design.md`.

## Pilot inventory

Use 80 source cases. Each case retains its upstream identifier, source version, license record, and original split.

| Stratum | Source-native pilot cases | Selection rule | Pilot output |
| --- | ---: | --- | --- |
| Surface spans: English | OpenPII 1.5M, 20 | Source-provided `language=en`; select varied PII labels and text lengths without changing text or span labels | Extractor input, source spans, Unicode offset checks |
| Surface spans: Korean | OpenPII 1.5M, 20 | Source-provided `language=ko`; select varied PII labels and text lengths without translation | Extractor input, source spans, Unicode offset checks |
| Contextual confidentiality | AgentLeak, 20 | Cover all 7 channels at least twice and all four published domains at least four times; store any balancing substitution | Source scenario, adjudicated Router policy context, captured egress channel |
| General agent utility | tau3-bench, 20 | Use the pinned release's `base` task split; stratify across available customer-service domains and record task ids | Native task result before and after Router |

AgentDojo and Agent Security Bench do not enter the 80-case pilot. After the four core paths pass, use five smoke cases from each only to validate the stress adapters; do not report these ten cases as an adversarial result.

## Required manifest fields

Every row contains the common source manifest plus exactly the fields needed for its stratum.

```json
{
  "case_id": "stable local id",
  "source": {
    "dataset": "OpenPII | AgentLeak | tau3-bench",
    "artifact_version": "dataset revision, release tag, or commit",
    "source_id": "upstream record or task id",
    "source_split": "upstream split or not_provided",
    "license": "verified license",
    "source_url": "canonical URL"
  },
  "language": "source-provided language code",
  "stratum": "surface | context | utility",
  "source_payload_ref": "immutable source content or reproducible pointer",
  "adapter_version": "git hash"
}
```

Surface rows add `extraction_records` from the upstream exact spans. Context rows add `policy_context`, one canonical `expected_action` (`allow`, `selective_mask`, or `block`), and `egress_sink` only after annotation. Utility rows add source-native `native_outcome` and the task environment reference. Gold fields remain evaluator-only.

## Annotation protocol for AgentLeak rows

AgentLeak supplies a private vault, an allowed set, scenario objective, channel, and domain. It does not by itself define Privacy Router's automatic action vocabulary. For the 20 selected cases:

1. Annotator A independently maps factual information to recipient, purpose, authorization, disclosure state, and raw-value necessity.
2. Annotator B sees the source case only and makes the same mapping.
3. A deterministic policy adapter maps the completed factual record to exactly one implemented automatic action: `allow`, `selective_mask`, or `block`.
4. An adjudicator resolves each disagreement and any non-unique action before the case becomes C1-eligible gold.
5. The record preserves both initial annotations, adjudication rationale, and the policy version.

The annotation is source-derived rather than source-provided. The published dataset card and future paper must say this explicitly. User overrides are excluded from the automatic-action target.

## Adapter and leakage gates

The pilot passes only if all gates pass:

1. Every row resolves to a pinned upstream artifact and a declared license.
2. OpenPII source spans round-trip through NFC code-point, UTF-16, and UTF-8 byte mappings without boundary drift.
3. Every AgentLeak case has a fully adjudicated, unique `allow`, `selective_mask`, or `block` expected action; no unresolved factual factor or multiple-action target remains.
4. The request serializer rejects any model-visible request containing `extraction_records`, `policy_context`, `expected_action`, or other evaluator-only gold.
5. Known-answer fixtures detect literal protected-span leakage and confirm a protected span is absent from captured external bytes when the selected action requires protection.
6. The tau3-bench adapter reproduces the source evaluator's result for a no-Router control run.
7. Every row records its upstream `source_split`. All Router variants derived from one upstream scenario or task remain in that split; when no upstream split exists, record `not_provided` and retain the deterministic selection log rather than inventing a Router-specific split.

A failed gate stops the pilot. It is fixed before adding scenarios, models, or language variants.

The current automatic policy resolver consumes sensitivity, record count, and essentialness only. The pilot's source-derived `policy_context` and `expected_action` therefore establish evaluator readiness, not runtime C1 readiness. A C1 comparison may begin only after `RuntimePolicyContext` is integrated at the shared Judge/MiddleMan policy-decision boundary, its chosen action is passed to the Router execution mapping, one-factor full-pipeline tests demonstrate each permitted contextual action change, and serializer tests confirm evaluator-only fields remain unavailable at runtime.

## Pilot reporting and statistics

The pilot reports counts, failure modes, and uncertainty only:

- exact-span precision, recall, and F1 separately for OpenPII English and Korean;
- AgentLeak factual-factor and action disagreement before adjudication, plus the final adjudicated action distribution;
- literal or span-level egress leakage on known-answer fixtures;
- tau3-bench native task completion before and after Router;
- parse, serialization, timeout, and unsupported-tool failures by source.

Use document-level bootstrap confidence intervals for span metrics and exact binomial intervals for event rates. Do not run significance tests, compare models, combine strata, or claim language equivalence from the pilot.

For a full evaluation, the independent unit is the upstream semantic scenario or task. The baseline and Router run on the same unit. Use paired cluster bootstrap or permutation tests for policy-action, leakage, and utility differences; retain all transformations and retries inside the same source cluster. Select full-corpus size only after the pilot estimates the observed event rate and variance.

## Pilot completion record

The pilot report must contain:

- the source manifest with pinned revisions and artifact checksums;
- selection and balancing log for all 80 rows;
- annotation agreement and adjudication log for the 20 AgentLeak rows;
- evaluator known-answer results and captured-byte fixtures;
- per-stratum metric table with confidence intervals;
- all excluded, failed, or substituted source cases and the reason.

No claim may describe the pilot as a new benchmark, a model comparison, or evidence of Privacy Router superiority.
