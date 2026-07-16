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
│    → any essential span:         block                      │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
                   ┌───────┴───────┐
                   ↓               ↓
              External API    Local API
              (raw/masked)     (block)
                   ↓
              Hydration for masked responses
```

## Runtime Model Bindings

The pipeline has three model-bound roles, not one model per named component:

| Runtime role | Current model | Trust boundary | Used by |
|---|---|---|---|
| Decision Model | EXAONE 4.0 1.2B (`openai/LGAI-EXAONE/EXAONE-4.0-1.2B`) | Local only | ExtractorCore and optional high-precision Critic; returns sensitivity, spans, categories, and `is_essential` |
| Local Model | Gemma 4 26B (`openai/google/gemma-4-26b-local`) | Local only | Generation for essential-sensitive raw prompts |
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
