# Architecture

## Pipeline

Privacy Router is an on-device **Extractor → Judge → Router** pipeline that intercepts every agent-generated prompt before it reaches an external LLM API.

```
Agent Prompt
    ↓
┌─────────────────────────────────────────────────────────────┐
│  Extractor (facade, precision="default"|"high")             │
│  ├── ExtractorCore: Socratic sensitivity detection          │
│  │   → Free-form SCREAMING_CASE categories                  │
│  │   → Minimal entity spans (exclude particles/adverbs)     │
│  │   → is_essential flag (masking feasibility)               │
│  └── Critic: post-review (precision="high" only)            │
│      → Catches spans Phase 1 missed                         │
│      → Runs even on empty texts                             │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Query aggregation + Judge (rule-based, no LLM calls)       │
│  Canonical policy decision:                                 │
│    → not sensitive:              allow                      │
│    → all spans non-essential:    selective_mask             │
│    → essential span / no safe span: block                   │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
                   ┌───────┴───────┐
                   ↓               ↓
              External API    Local API
              (raw/masked)     (block)
                   ↓
              Hydration for masked responses
```

![Privacy Router consumer protection flow: safe prompts go to an external model as raw text; maskable prompts leave as placeholders and are hydrated locally; essential or no-safe-span prompts stay local.](../../assets/generated/privacy-router-consumer-flow.svg)

## Runtime Model Bindings

The pipeline has three model-bound roles, not one model per named component:

| Runtime role | Current model | Trust boundary | Used by |
|---|---|---|---|
| Decision Model | Gemma 4 26B (`openai/google/gemma-4-26b-local`) | Local only | ExtractorCore and optional high-precision Critic; returns sensitivity, spans, categories, and `is_essential` |
| Local Model | Gemma 4 26B (same endpoint) | Local only | Generation for essential-sensitive raw prompts |
| External Model | OpenRouter Gemma 4 26B (`openrouter/google/gemma-4-26b-a4b-it`) | External | Generation for non-sensitive prompts or validated masked prompts |

`Judge` is rule-based policy code and `Router` is deterministic execution code. Neither has an LLM binding. Extractor, Critic, and Judge remain useful component names, but they are not independent selectable model roles.


## Component Architecture

```
Extractor (facade)
  ├── ExtractorCore  — Socratic extraction (always runs)
  │   └── extract.prompt / extract.short.prompt
  └── Critic         — post-review (precision="high" only)
      └── critic.prompt

Judge (rule-based) — injected by Router
  └── classify.prompt (reference only, not used)

Router — policy → execution path mapping
```
## Detector Contract (implemented detector layer)

The backend-independent detector contract is implemented in `agents/extractor`.
The current `ExtractorCore`/`Extractor` path remains the compatibility surface
for the existing Judge and Router until their planned cutover. The detector
layer normalizes LLM, Presidio, OpenAI Privacy Filter (OPF), and LFM2.5 outputs
into one privacy entity type. Detection does not perform policy judgment,
masking, unmasking, or persistence.

```text
Detector adapter
  → validate exact span and offsets
  → normalize kind and tag
  → issue an occurrence-specific uid
  → return PrivacyEntity
```

`PrivacyEntity` fields:

| Field | Meaning |
|---|---|
| `id: UUID` | Internal identity of this entity record |
| `kind: "contextual" \| "structural"` | Why the value is privacy-relevant |
| `tag: str` | Canonical short label, such as `EMAIL` or `API_KEY` |
| `uid: str` | 128-bit random occurrence token generated with `secrets` |
| `span: str` | Exact sensitive substring from the input |
| `offsets: tuple[int, int]` | `(start, end)`, zero-based, end-exclusive Unicode code-point offsets |
| `reason: str \| None` | Optional explanation from the detector |
| `confidence: float \| None` | Optional detector score in `[0, 1]` |
| `native_label: str \| None` | Original backend label before normalization |
| `native_metadata` | Backend-specific metadata, including recognizer identity |
| `detection_method` | `regex`, `ner`, `token_classifier`, `llm`, or `hybrid` |
| `is_required` | Nested assessment: `value` is `true`, `false`, or `null`; `reason` is required for every state |

The externally visible identifier is computed, not persisted:

```python
@property
def identifier(self) -> str:
    return f"{self.tag}#{self.uid}"
```

`uid` is an opaque random token, not a cryptographic hash of `span`. The
normalizer issues a new value for every retained occurrence, checks collisions
within the current extraction result, and does not deduplicate equal values by
content.

Valid supplied offsets are authoritative even when two recognizers report the
same range or overlapping ranges; each retained evidence item receives its
own `uid`. Only candidates without valid offsets are assigned to the next
unused exact occurrence of their span.

`DetectorRunProvenance` is stored at result level, not only on entities. It is
a discriminated union identified by `detector_type`, and every run requires a
full kebab-case `detector_id` containing its implementation version:

```text
llm:     privacy-router-llm-extractor-v1-0-0
presidio: microsoft-presidio-analyzer-v2-2-358
opf:     openai-privacy-filter-v1-0-0
lfm:     liquidai-lfm2-5-encoder-350m-pii-detector-v1-0-0
```

Each run records its `run_id`, `status` (`complete`, `partial`, or `failed`),
`external_opt_in`, adapter version, and backend-specific model/configuration
revision. LLM runs may also record the model and prompt revision; Presidio
runs record the configured recognizer list; LFM runs may record the decoder
revision.

For Presidio, one analyzer run may produce entities from multiple recognizers.
The run-level provenance therefore preserves the configured recognizer list,
while each entity's `native_metadata` preserves the result-level
`recognizer_name` and `recognizer_identifier` when supplied.

`DetectionResult.detector_runs` is populated even when a detector returns zero
entities or fails. An entity's `run_id` points to the exact run that produced
it. This preserves clean-negative and failed-run auditability without
duplicating provenance on every entity.

`reason` and `confidence` remain optional because OPF, Presidio, and LFM do
not expose the same evidence as the LLM extractor.

`DetectionResult` contains `detector_runs`, the entity list, a
complete/partial/failed status, and diagnostics. It does not contain a second
`uid → value` storage copy. The result exposes a derived `identifier → span`
mapping through a consumer-owned helper or storage adapter. The raw span may
enter the trusted local detector, but must never enter telemetry. The LLM
extractor is local-only by default; sending raw input to an external model
requires explicit per-request opt-in, recorded on the detector run, and
otherwise fails closed.

## Follow-up Cutover Decisions

The initial detector adapters are implemented. Before replacing the current
pipeline, the following decisions must be frozen:

1. The canonical `tag` vocabulary and each backend's native-label mapping.
2. Cross-detector merge and overlap rules; same-run duplicate supplied offsets
   are preserved as separate evidence by the normalizer.
3. Failure behavior for `partial` and `failed` results; these must not be
   interpreted as a clean no-detection result.
4. The persistence boundary for consumer-owned `uid → span` storage.
5. The LLM trust policy: local-only by default; raw-input extraction by an
   external model is permitted only with explicit opt-in, otherwise it fails
   closed.

## Optional Detector Installation

The base installation contains the LiteLLM-backed LLM extractor. Install the
rule/model detector extras with:

```bash
uv sync --extra privacy-detectors --extra local-inference
```

`privacy-detectors` installs `presidio-analyzer` and the OpenAI Privacy Filter
package from the immutable git revision
`f7f00ca7fb869683eb732c010299d901457f19c3`. `local-inference` supplies the
Transformers/PyTorch runtime used by LFM2.5. The LFM adapter pins model files
and decoder helpers to revision
`b8c9cf3d2d6ae52501b35a27ba46f271449c9ce2`; it enables
`trust_remote_code=True` only for that pinned revision.

## Middle-Man Architecture

The Middle-Man Agent orchestrates the pipeline and manages user interaction.

```
agents/router/
├── middle_man.py      # Middle-Man Agent (decision logic)
├── cache.py           # SQLite KV cache
├── router.py          # Router (policy → execution path)
└── schemas.py         # Schema definitions
```

### Decision Flow

```python
def process_with_middle_man(text, metadata):
    # 1. Extract (with cache check)
    extraction = extract_with_cache(text, metadata.cache_strategy)

    # 2. Middle-Man decision
    if not extraction.is_sensitive:
        return auto_process(text, extraction)

    if metadata.auto_mask:
        if all_confident(extraction, metadata.masking_threshold):
            return auto_process(text, extraction)
        else:
            return ask_user(text, extraction)
    else:
        return ask_user(text, extraction)
```

### Cache Strategies

| Strategy | Description | DB Operation |
|----------|-------------|--------------|
| `auto` | Default. HIT → use, MISS → run & store | SELECT / INSERT |
| `bypass` | Always re-run, no storage | (none) |
| `refresh` | Re-run, overwrite cache | UPSERT |
| `delete` | Delete then re-run, no storage | DELETE |

Cache stores **extraction results only** (not LLM responses).
Cache key: chunked MD5 hash of input text (4KB chunks → parallel hash → combine → rehash).

## Response Formats

### Case 1: Auto-processed (default)

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
  "privacy_router": {
    "status": "completed",
    "is_sensitive": true,
    "extraction_records": [...],
    "policy_action": "selective_mask",
    "masking_applied": true,
    "cached": false
  }
}
```

### Case 2: User input required

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": null}, "finish_reason": "requires_action"}],
  "privacy_router": {
    "status": "needs_input",
    "question": "Sensitive data detected. How should it be handled?",
    "extraction_summary": {
      "is_sensitive": true,
      "record_count": 2,
      "essential_count": 1,
      "extraction_records": [
        {"index": 0, "category": "UNPUBLISHED_RESEARCH_CONCEPT", "span": "<research-concept>", "is_essential": true, "confidence": 0.95},
        {"index": 1, "category": "INTERNAL_PROJECT_NAME", "span": "<internal-project-name>", "is_essential": false, "confidence": 0.90}
      ],
      "default_action": "block"
    },
    "options": [
      {"id": "auto", "label": "Auto", "description": "Follow system decision"},
      {"id": "mask_all", "label": "Mask all", "description": "Mask all sensitive data"},
      {"id": "mask_essential", "label": "Mask essential only", "description": "Mask is_essential=true only"},
      {"id": "block", "label": "Local processing", "description": "Use local model instead of external API"},
      {"id": "custom", "label": "Custom", "description": "Per-record selection"}
    ],
    "default_option": "auto"
  }
}
```

### Case 3: User selection → re-request

```json
{
  "model": "privacy-router",
  "messages": [
    {"role": "user", "content": "Original text..."},
    {"role": "assistant", "content": null, "privacy_router": {"status": "needs_input", ...}},
    {"role": "user", "content": null, "privacy_router": {
      "selected_option": "custom",
      "overrides": [
        {"record_index": 0, "is_essential": true},
        {"record_index": 2, "remove": true}
      ]
    }}
  ]
}
```

## API vs MCP

| Aspect | API (OpenAI Compatible) | MCP Server |
|--------|------------------------|------------|
| Entry point | `server/api/routes/proxy.py` | `server/mcp/tools.py` |
| Caller | External clients | AI agents |
| Middle-Man | Pipeline-internal auto-execution | Agent calls `review()` / `decide()` directly |
| User prompt | `status: needs_input` response → client prompts user | Agent prompts user directly |
| State | Stateless (client manages context) | Stateless (agent manages context) |
| Cache | `cache_strategy` metadata | `no_cache` flag |

## API

```python
# Default mode (fast, 1 LLM call)
extractor = Extractor()
result = extractor.extract("Please review <personal-id>")

# High-precision mode (with Critic, 2 LLM calls)
extractor = Extractor(precision="high")
result = extractor.extract("Please review <personal-id>")

# Dependency injection (for testing)
extractor = Extractor(core=my_core, critic=my_critic)
```

## Detection Surfaces

### Pattern-Based (형태적)
PII, phone numbers, emails, real names — detectable by pattern.
- Accuracy: 83.3% (Gemma4 E4B)

### Context-Based (맥락적)
Business secrets, research ideas, strategy, budgets, internal URLs — requires contextual understanding.
- Accuracy: 62.5% (Gemma4 E4B)

`kind` describes the privacy property of the value, not the mechanism that
found it. A structural entity may be detected by a regex, NER model, or token
classifier; a contextual entity is normally detected by an LLM or another
context-aware detector. `detection_method` records that mechanism separately.

## Prompts

| File | Location | Purpose |
|------|----------|---------|
| `extractor.prompt` | `agents/extractor/extract.prompt` | Default extraction (Socratic, 298 lines) |
| `extractor.short.prompt` | `agents/extractor/extract.short.prompt` | ≤2B models (24 lines) |
| `extractor.socratic.prompt` | `agents/extractor/extract.socratic.prompt` | Socratic CoT (131 lines) |
| `extractor.fixed.prompt` | `agents/extractor/extract.fixed.prompt` | Fixed categories (232 lines) |
| `critic.prompt` | `agents/extractor/critic.prompt` | 2nd-pass critique (92 lines) |
| `judge.prompt` | `agents/judge/classify.prompt` | Classification/policy (reference only) |

## Model Selection

```
Model size   → Prompt
─────────────────────────────
≤ 2B         → extract.short.prompt
3B ~ 4B      → extract.prompt (default)
> 4B         → extract.prompt or extract.socratic.prompt
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| Extractor | `agents/extractor/extractor.py` | Facade (precision, DI support) |
| ExtractorCore | `agents/extractor/extractor_core.py` | Socratic extraction logic |
| Critic | `agents/extractor/critic.py` | Post-review (standalone) |
| Judge | `agents/judge/judge.py` | Rule-based policy decision |
| Router | `agents/router/router.py` | Pipeline orchestration |
| MiddleMan | `agents/router/middle_man.py` | User interaction orchestrator |
| Masker | `agents/masker/masker.py` | span → placeholder substitution |
| Cache | `agents/router/cache.py` | chat_id-based state management |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLModel |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Models | SQLite-backed registry with local and external model entries |
| Frontend | SvelteKit (SSG) |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256) |
| Integration | OpenAI Compatible API + MCP Server |

## Testing

Two test suites:

### Unit Tests (mock-based)

- **Location**: `tests/core/`, `tests/sanity/`, `server/tests/`
- **Purpose**: Code structure and logic verification
- **Method**: `@patch` to mock LLM calls
- **Targets**: Pipeline paths, validation logic, masking/hydration, policy decisions, error handling
- **Run**: `python3 -m pytest tests/core/ tests/sanity/ server/tests/ -v`
- **Time**: ~30 seconds

### Eval Suite (real LLM calls)

- **Location**: `scripts/eval_runner.py`, `scripts/eval_all.py`
- **Purpose**: LLM output quality verification
- **Method**: N≥5 trials with real LLM calls
- **Targets**: Sensitivity detection rate, policy decision accuracy, pattern/context detection, JSON output
- **Run**: `python3 scripts/eval_runner.py --model gemma4-e4b-openrouter --trials 5`
- **Time**: Minutes to tens of minutes

### Why separate?

Without mocking, a test failure cannot distinguish "code bug" from "LLM variation".

## Related Documents

- [Detection](../user/detection.md) — Socratic sensitivity detection framework and examples
- [Query aggregation spec](query-aggregation-spec.md) — span evidence, query-level decision variables, and fail-closed routing invariants
- [Data flow](data-flow.md) — data types, policy actions, and masking/hydration boundaries
- [Fail-closed routing](fail-closed-routing.md) — fixed-route execution, retries, safe errors, and streaming cutoff behavior
- [Database ERD](database-erd.md) — SQLite schema
- [Config files](config-files.md) — YAML and DB configuration structure
- [Integration architecture](integration-architecture.md) — Hermes Agent, OpenCode, LiteLLM integration
- [Security](../user/security.md) — threat model and encryption

## Change Log

- 2026-08-28 — implemented the detector abstraction around `PrivacyEntity`,
  occurrence-specific opaque `uid` values, computed `tag#uid` identifiers,
  result-level discriminated detector provenance, and nested requiredness.
  Judge, Router, and current pipeline callers remain unchanged by design.

## Impact Surface

- Code: `agents/extractor/` now contains the common Pydantic contract,
  normalizer, parsers, four backend adapters, registry, and unit tests.
- Skills: none.
- Docs: this architecture document is the canonical contract record.
- Decisions: `kind` is `contextual|structural`; `uid` is a random token, not a
  value hash; detector IDs are versioned kebab-case strings; LLM external
  opt-in is request-scoped.
- Archive/versioning: no archive; the document remains the current guidance.
- Verification: detector and core agent unit tests pass; optional detector
  package import smoke passes without loading model weights.
- No-update rationale: masking/hydration and policy/routing replacement are
  intentionally unchanged until their separate design phase.
