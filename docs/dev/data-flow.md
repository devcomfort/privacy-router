# Data Flow

Privacy Router handles two different data layers: exact span evidence for action, and query-level summaries for decisions.

## Flow Overview

```text
User or agent prompt
    -> Extractor
    -> ExtractionResult
       - Sensitivity
       - ExtractionRecord[]
    -> Query aggregation
       - QueryDecisionSummary
    -> Judge
       - policy_action: allow | selective_mask | block
    -> Router
       - external_api | local_api
    -> Masker / Hydrator when needed
```

The key design rule is:

```text
Aggregate for decision. Preserve spans for action.
```

See [Query Aggregation Spec](query-aggregation-spec.md) for the normative schema, formulas, and fail-closed acceptance tests.

## Data Types

### 1. Input Prompt

| Property | Description |
|---|---|
| Format | Natural-language text, multilingual. |
| Source | AI agent, web UI, MCP client, or OpenAI-compatible client. |
| Storage | Process memory during routing. |
| External transfer | Allowed raw only when the final policy action is `allow`. |

### 2. Span Evidence: `ExtractionRecord`

An `ExtractionRecord` is one detected sensitive span. It remains the source of truth for masking and hydration.

```python
ExtractionRecord(
    category="PERSONAL_IDENTIFIER",
    span="<personal-id>",
    confidence=0.98,
    start=18,
    end=31,
    detection_type="pattern",
    reasoning="The span directly identifies a person.",
    is_essential=False,
)
```

Requirements:

- `span` is the exact sensitive substring.
- `category` is dynamically generated as `SCREAMING_SNAKE_CASE`.
- `start` and `end` are 0-indexed character offsets.
- `is_essential=false` means masking preserves the query intent.
- `is_essential=true` means masking breaks the query intent; the query must not go to an external model by default.

### 3. Query-Level Summary: `QueryDecisionSummary`

The summary is a derived decision artifact. It is not a replacement for records.

```python
QueryDecisionSummary(
    extraction_failed=False,
    extraction_failure_reason=None,
    is_sensitive=True,
    has_essential=False,
    is_maskable=True,
    record_count=2,
    essential_count=0,
    category_counts={"PERSONAL_IDENTIFIER": 1, "INTERNAL_PROJECT_NAME": 1},
    essential_categories=(),
    maskable_categories=("PERSONAL_IDENTIFIER", "INTERNAL_PROJECT_NAME"),
    mask_indices=(0, 1),
)
```

Decision variables:

\[
U(q)=\mathbb{1}[\text{extractor failed or output invalid}]
\]

\[
S(q)=\mathbb{1}[U(q)=0 \land |R(q)|>0]
\]

\[
E(q)=\max_{r_i\in R(q)} e_i
\]

\[
M(q)=S(q)\cdot(1-E(q))
\]

Important invariant:

```text
Empty records are safe only when extraction succeeded.
Extractor failure is unknown, not safe.
```

### 4. Policy Judgment

The Judge maps query-level conditions to canonical policy actions.

| Condition | Canonical `policy_action` | Meaning |
|---|---|---|
| `extraction_failed=true` | `block` | Fail closed; process locally and never send the raw prompt externally. |
| `is_sensitive=false` | `allow` | Raw prompt may go to the external model. |
| `has_essential=true` | `block` | Use local processing; no external raw prompt. |
| `is_maskable=true` | `selective_mask` | Mask non-essential records before external model call. |

Only `allow`, `selective_mask`, and `block` are valid policy actions. The runtime rejects any other action.

### 5. Routing Result

The Router maps policy actions to execution paths.

| `policy_action` | Endpoint | Masking required | External raw prompt? |
|---|---|---|---|
| `allow` | `external_api` | No | Yes |
| `selective_mask` | `external_api` | Yes | No |
| `block` | `local_api` | No | No |

### 6. Masking Contract

The Masker uses `ExtractionRecord[]`, not the summary, to replace spans with deterministic placeholders.

```python
MaskingContract(
    placeholder_map={
        "PERSONAL_IDENTIFIER#7f3a9c2d": "<personal-id>",
        "INTERNAL_PROJECT_NAME#b81e2a10": "<internal-project-name>",
    },
    count=2,
)
```

Placeholder rules:

- Format: `CATEGORY#hash8`.
- No square brackets.
- The hash is derived from the original value so repeated values map consistently.
- The contract is the source of truth for hydration.

### 7. Pipeline Result

A successful masked external path returns the model output after hydration.

```python
PipelineResult(
    sensitivity=Sensitivity(is_sensitive=True, rationale="Sensitive spans detected."),
    judgment=Judgment(
        policy_action="selective_mask",
        strategy="Mask non-essential records before external model call.",
        rationale="All detected spans are non-essential."
    ),
    route=RouteResult(endpoint="external_api", requires_masking=True),
    records=[ExtractionRecord(...)],
    mask_indices=[0, 1],
    response="Final hydrated response...",
)
```

## Privacy Boundaries

### External LLM boundary

The external LLM is untrusted for raw sensitive data.

- `allow`: external model receives the raw prompt.
- `selective_mask`: external model receives only masked text.
- `block`: external model receives nothing from this query.

### Caller-facing boundary

Caller-facing API/MCP metadata may include sensitive span details from the current request because the caller supplied that request, but this metadata must still be treated as sensitive operational data.

- Never echo spans that exist only in persisted conversation context.
- Never expose extractor reasoning; return only category, span, confidence, and `is_essential` for current-request records.
- Do not write raw spans to persistent logs unless encrypted and explicitly required.
- Prefer counts, categories, policy actions, and placeholders in logs.
- Documentation examples must use placeholders such as `<personal-id>` rather than concrete identifiers.

## Data Retention

| Data | Storage | Retention |
|---|---|---|
| Raw current request | Process memory | Request lifetime. |
| Conversation context with `X-Chat-ID` | Encrypted extraction cache | Session/cache lifetime; tenant-scoped by authenticated API-key ID. |
| Extraction records | Encrypted extraction cache | Session/cache lifetime. |
| QueryDecisionSummary | Memory/log-safe if spans excluded | May be logged as counts/actions. |
| Placeholder map | Masking contract storage | Session TTL; encrypted if persisted. |
| Masking records | DB when enabled | Encrypted at rest. |
| Policy decision | Usage log | Persistent, without raw spans. |
| Provider API keys | DB | Encrypted until deletion. |

## Acceptance Requirements

Data-flow correctness requires these checks before implementation is considered complete:

1. Safe query with successful extraction and zero records routes as `allow`.
2. Non-essential sensitive query routes as `selective_mask`, and the external backend receives masked text only.
3. Any essential record routes as `block`, never external raw.
4. Extractor call/parse/schema failure routes fail-closed, never `allow`.
5. Hydration uses `MaskingContract.placeholder_map`, not the query summary.
6. Unknown policy actions are rejected rather than normalized.
