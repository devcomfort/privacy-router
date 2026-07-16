# Query Aggregation Spec

Status: **spec-first target**. This document defines the required behavior before implementation changes are made. Current code may still perform parts of this aggregation implicitly inside `Judge.classify()`.

## Purpose

Privacy Router MUST separate two concerns:

1. **Span evidence** — exact sensitive spans needed for masking, hydration, and audit.
2. **Query decision summary** — query-level variables used by the Judge and Router.

The guiding rule is:

```text
Aggregate for decision. Preserve spans for action.
```

Korean summary: 이 명세는 span-level 증거와 query-level 의사결정을 분리한다. 집계값은 라우팅 판단에만 쓰고, 실제 마스킹/하이드레이션은 원본 `ExtractionRecord`와 `MaskingContract`를 source of truth로 유지해야 한다.

## Pipeline Position

Target pipeline:

```text
Input query q
  -> Extractor
  -> Span evidence R(q): ExtractionRecord[]
  -> QueryAggregator
  -> QueryDecisionSummary z(q)
  -> Judge
  -> policy_action
  -> Router
  -> allow | selective_mask | block
```

`QueryAggregator` MUST NOT replace `ExtractionRecord[]`. It derives a compact summary from the records and extraction status, while the Masker and Hydrator continue to use the original records and masking contract.

## Layer 1: Span Evidence

For a query `q`, the Extractor produces a set of records:

\[
R(q)=\{r_1,\dots,r_n\}
\]

Each record is:

\[
r_i=(s_i,c_i,a_i,b_i,p_i,e_i)
\]

| Symbol | Field | Meaning |
|---|---|---|
| \(s_i\) | `span` | Exact sensitive substring from the input text. |
| \(c_i\) | `category` | Dynamic `SCREAMING_SNAKE_CASE` category. |
| \(a_i,b_i\) | `start`, `end` | Character offsets, 0-indexed, end-exclusive. |
| \(p_i\) | `confidence` | Detection confidence in `[0, 1]`. |
| \(e_i\) | `is_essential` | `true` when masking the span breaks the query intent. |

Span rules:

- `span` MUST contain only the sensitive entity itself. It MUST exclude particles, adverbs, and verb derivations.
- `category` MUST be generated dynamically as `SCREAMING_SNAKE_CASE`; the system MUST NOT rely on a closed fixed category list.
- `is_essential=true` means the raw value is the object of the user's request, not just background material.
- The placeholder format for maskable spans is `CATEGORY#hash8`, without brackets.

Redacted example:

```json
{
  "category": "PERSONAL_IDENTIFIER",
  "span": "<personal-id>",
  "confidence": 0.98,
  "start": 18,
  "end": 31,
  "detection_type": "pattern",
  "reasoning": "The span directly identifies a person.",
  "is_essential": false
}
```

## Layer 2: QueryDecisionSummary

`QueryDecisionSummary` is the required query-level aggregate artifact.

Target schema:

```python
@dataclass(frozen=True)
class QueryDecisionSummary:
    extraction_failed: bool
    extraction_failure_reason: str | None
    is_sensitive: bool
    has_essential: bool
    is_maskable: bool
    record_count: int
    essential_count: int
    category_counts: dict[str, int]
    essential_categories: tuple[str, ...]
    maskable_categories: tuple[str, ...]
    mask_indices: tuple[int, ...]
```

Field requirements:

| Field | Requirement |
|---|---|
| `extraction_failed` | MUST be `true` when extractor call, structured parsing, schema validation, offset validation, or confidence gating fails. |
| `extraction_failure_reason` | SHOULD contain a short machine-readable reason when `extraction_failed=true`. |
| `is_sensitive` | MUST be `true` only when extraction succeeded and at least one validated record exists. |
| `has_essential` | MUST be `true` if any validated record has `is_essential=true`. |
| `is_maskable` | MUST be `true` only when extraction succeeded, the query is sensitive, and no record is essential. |
| `record_count` | MUST equal `len(R(q))` for validated records. |
| `essential_count` | MUST equal the number of records with `is_essential=true`. |
| `category_counts` | MUST count categories across validated records. |
| `essential_categories` | MUST contain categories whose records are essential. |
| `maskable_categories` | MUST contain categories whose records are non-essential. |
| `mask_indices` | MUST contain indexes of records eligible for masking on the `selective_mask` path. |

Example:

```json
{
  "extraction_failed": false,
  "extraction_failure_reason": null,
  "is_sensitive": true,
  "has_essential": false,
  "is_maskable": true,
  "record_count": 2,
  "essential_count": 0,
  "category_counts": {
    "PERSONAL_IDENTIFIER": 1,
    "INTERNAL_PROJECT_NAME": 1
  },
  "essential_categories": [],
  "maskable_categories": ["PERSONAL_IDENTIFIER", "INTERNAL_PROJECT_NAME"],
  "mask_indices": [0, 1]
}
```

## Decision Variables

Define uncertainty:

\[
U(q)=\mathbb{1}[\text{extraction failed or output invalid}]
\]

Sensitivity is safe to compute only after successful extraction:

\[
S(q)=\mathbb{1}[U(q)=0 \land |R(q)|>0]
\]

Essentiality:

\[
E(q)=\max_{r_i \in R(q)} e_i
\]

Maskability:

\[
M(q)=S(q)\cdot(1-E(q))
\]

Category profile:

\[
N_k(q)=\sum_i \mathbb{1}[c_i=k]
\]

Essential category set:

\[
K_{ess}(q)=\{c_i\mid e_i=1\}
\]

Maskable category set:

\[
K_{mask}(q)=\{c_i\mid e_i=0\}
\]

Mask index set:

\[
I_{mask}(q)=\{i\mid e_i=0\}
\]

Important invariant:

```text
Empty records are safe only when extraction succeeded.
Failed extraction is unknown, not non-sensitive.
```

## Routing Policy

Canonical policy actions are:

- `allow`
- `selective_mask`
- `block`

Any action outside this canonical set is invalid and MUST be rejected.
Normative policy:

\[
\pi(q)=
\begin{cases}
\texttt{block}, & U(q)=1 \\
\texttt{allow}, & U(q)=0 \land S(q)=0 \\
\texttt{block}, & U(q)=0 \land S(q)=1 \land E(q)=1 \\
\texttt{selective\_mask}, & U(q)=0 \land S(q)=1 \land E(q)=0
\end{cases}
\]

Operational table:

| Condition | Canonical `policy_action` | Router endpoint | External raw prompt allowed? |
|---|---|---|---|
| `extraction_failed=true` | `block` | `local_api` | **No** |
| `is_sensitive=false` | `allow` | `external_api` | **Yes** |
| `has_essential=true` | `block` | `local_api` | **No** |
| `is_maskable=true` | `selective_mask` | `external_api` with masking | **No raw prompt** |

The project default is conservative: if any record is essential, the whole query MUST be processed locally and MUST NOT be sent to an external model.

## Fail-Closed Invariants

The implementation MUST satisfy these invariants:

1. `extraction_failed=true` MUST NOT resolve to external raw transmission.
2. `has_essential=true` MUST NOT resolve to external transmission, even if a caller requests forced generation.
3. `policy_action=allow` is valid only when `extraction_failed=false` and `record_count=0`.
4. `policy_action=selective_mask` requires `record_count>0`, `has_essential=false`, and a non-empty `mask_indices` list.
5. `policy_action=block` means the external model receives no input from this query.
6. `QueryDecisionSummary` MUST be derivable from `ExtractionResult`, but MUST NOT be the only retained artifact.

Korean summary: extractor 실패나 parse 실패는 “민감 정보 없음”이 아니다. 반드시 unknown으로 처리하고 외부 raw 전송을 막아야 한다. 또한 essential span이 하나라도 있으면 강제 generate 모드에서도 외부 전송으로 downgrade하면 안 된다.

## Privacy Boundaries

### External model boundary

The external LLM backend is untrusted for sensitive raw input.

- It MAY receive raw text only for `allow`.
- It MAY receive masked text for `selective_mask`.
- It MUST NOT receive raw text for `block`, extractor failure, or essential records.

### Caller-facing boundary

The caller already supplied the original prompt, but response metadata can still leak sensitive data into logs or third-party systems.

- API and MCP response metadata that contains `span`, `placeholder_map`, or `extraction_records` MUST be treated as sensitive.
- Persistent logs SHOULD store only counts, categories, actions, and redacted placeholders unless encrypted storage is explicitly required.
- Documentation examples MUST use placeholders such as `<personal-id>` and `PERSONAL_IDENTIFIER#7f3a9c2d`, not real identifiers.

## Masking and Hydration Contract

`QueryDecisionSummary` decides whether masking is needed. It does not perform masking.

Masking path:

```text
ExtractionRecord[] + input text
  -> Masker
  -> masked text + MaskingContract
  -> external LLM
  -> Hydrator
  -> caller-facing response
```

Requirements:

- Masker MUST use the original `ExtractionRecord[]`, not only `QueryDecisionSummary`.
- Hydrator MUST use `MaskingContract.placeholder_map` as the restoration source of truth.
- The contract MUST map `CATEGORY#hash8` placeholders to original values.
- If hydration cannot resolve a placeholder, the system MUST fail explicitly rather than silently dropping or inventing content.

Redacted example:

```json
{
  "masked_text": "Summarize the incident for PERSONAL_IDENTIFIER#7f3a9c2d.",
  "placeholder_map": {
    "PERSONAL_IDENTIFIER#7f3a9c2d": "<personal-id>"
  }
}
```

## Acceptance Tests

Before implementing this spec, create tests that cover the decision layer independently from the LLM.

| Case | Input state | Expected summary | Expected route |
|---|---|---|---|
| Safe query | extraction ok, zero records | `is_sensitive=false` | `allow -> external_api` |
| Non-essential sensitive query | extraction ok, records all `is_essential=false` | `is_maskable=true` | `selective_mask -> external_api`, masked only |
| Essential sensitive query | extraction ok, at least one `is_essential=true` | `has_essential=true` | `block -> local_api`, no external raw |
| Mixed essential/non-essential records | extraction ok, at least one essential | `has_essential=true` | `block -> local_api` by default |
| Extractor call failure | exception before structured result | `extraction_failed=true` | no external raw |
| Structured parse failure | malformed JSON or schema error | `extraction_failed=true` | no external raw |
| Invalid offsets | record span does not match offsets | `extraction_failed=true` or record rejected with explicit reason | no fail-open allow |
| Forced generation with essential record | `action="generate"`, `has_essential=true` | `has_essential=true` | no external raw |
| Invalid policy action | Unknown action reaches Router boundary | rejected with `ValueError` | no fallback route |

Regression test name recommendation:

```text
test_extraction_failure_never_routes_external_raw
```

## Metrics

Separate evaluation into span-level and query-level metrics.

Span-level:

- exact span F1
- category accuracy
- `is_essential` accuracy
- offset validity rate

Query-level:

- sensitivity precision/recall
- `has_essential` accuracy
- maskability accuracy
- policy action accuracy
- false external raw leak rate
- extractor failure fail-closed rate

No single aggregate score may hide a non-zero false external raw leak rate.

## Implementation Sequence

Spec-driven order:

1. Add `QueryDecisionSummary` schema and pure aggregation function.
2. Add mock-based unit tests for every acceptance case above.
3. Change Judge to consume the summary or delegate summary creation explicitly.
4. Enforce fail-closed behavior on extraction failure before Router resolution.
5. Reject unknown policy actions at the Router boundary.
6. Update API/MCP metadata after tests pass.
7. Run the real-LLM eval suite separately after code behavior is deterministic.

Implementation is complete only when the fail-closed tests pass and documentation examples use canonical `allow` / `selective_mask` / `block` labels.
