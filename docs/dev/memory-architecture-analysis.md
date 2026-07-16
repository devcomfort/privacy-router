# Memory Architecture Analysis for Privacy Router

> Research conducted 2026-06-08. Sources: Strands Agents SDK (GitHub), MCP specification (modelcontextprotocol.io), MCP Memory Server (official), LangGraph memory concepts, Anthropic agent building guidance, Wikipedia blackboard pattern.

---

## 1. Strands Agents Framework Memory

**What it does:** Model-driven SDK (Python/TypeScript) for building AI agents. Lightweight agent loop with native MCP support, multi-provider LLM integration, and `@tool` decorators. Core loop is intentionally stateless.

**Session persistence:** No built-in session manager. Three patterns available:
- Custom history management (external DB/file)
- Model context window as implicit memory (200K+ token contexts)
- Custom state objects wrapping agent with session store

Developer controls all persistence — no accidental retention in the framework.

**MCP integration:** First-class via `MCPClient` wrapper. MCP tools treated identically to `@tool` decorators. Supports stdio and SSE transports. Lifecycle managed via context managers.

| Aspect | Assessment |
|--------|-----------|
| Privacy safety | High — no telemetry, no built-in data retention |
| Session support | None — must build from scratch |
| MCP fit | Excellent — `process()` tool integrates naturally |
| Complexity | Low — library, not framework |

**Pros for Privacy Router:**
- Stateless core = no accidental data retention in framework
- MCP tools integrate naturally
- Developer controls all persistence — can enforce privacy at storage layer
- No telemetry or data phoning home

**Cons for Privacy Router:**
- No session memory out-of-box — must build own
- Context-window-as-memory sends all history to LLM — privacy risk
- No masking contract propagation across turns
- MCP stdio servers run in-process — malicious tool could access agent state

---

## 2. MCP Server Memory Implementation (Official Memory Server)

**What it does:** Knowledge graph pattern with three primitives: entities (nodes), relations (directed edges), observations (atomic facts). JSONL persistence. Eight mutation tools (`create_entities`, `create_relations`, `add_observations`, `delete_entities`, `delete_observations`, `delete_relations`, `read_graph`, `search_nodes`).

**Session persistence:** JSONL file on disk (configurable `MEMORY_FILE_PATH`). Mutations are idempotent (deduplication built in). Entity deletion cascades to relations. No TTL or session scoping — flat knowledge graph.

**MCP integration:** Standard tool-based pattern. LLM decides when to call memory tools (model-controlled). Supports `readOnlyHint` and `destructiveHint` behavioral annotations.

| Aspect | Assessment |
|--------|-----------|
| Privacy safety | Low — LLM-controlled writes could store raw PII |
| Session support | None — flat graph, no scoping |
| MCP fit | Good — tool-based memory aligns with MCP pattern |
| Complexity | Medium — knowledge graph for simple KV needs |

**Pros for Privacy Router:**
- Tool-based memory aligns with MCP `process()` tool
- Deduplication prevents duplicate masking entries
- JSONL is auditable
- Entity/relation model could represent masking contracts

**Cons for Privacy Router:**
- Knowledge graph overkill for masking contract persistence
- No session scoping — cross-session leakage risk
- LLM-controlled memory = privacy risk (model decides what to remember)
- No encryption or access control
- No TTL/expiration for sensitive data

---

## 3. Agent Session Memory Architecture Patterns

### LangGraph Model

**What it does:** Splits memory into two scopes:
- **Short-term (thread-scoped):** Conversation-local, checkpointed per thread ID
- **Long-term (namespace-scoped):** Cross-session, shared per user/org

Three memory types from cognitive science:
- **Semantic** (facts) — profile (single doc) or collection (many small docs)
- **Episodic** (experiences) — few-shot examples
- **Procedural** (instructions) — system prompt, reflection-derived rules

**Session persistence:** Checkpointer pattern — graph state persisted at each step. Store pattern uses `(namespace, key)` tuples with semantic search.

| Aspect | Assessment |
|--------|-----------|
| Privacy safety | High — thread isolation, namespace scoping |
| Session support | Excellent — built-in checkpointing |
| MCP fit | Indirect — patterns map to MCP resources/tools |
| Complexity | High — adds LangGraph dependency |

**Pros:**
- Thread-scoped isolation prevents cross-conversation leakage
- Collection-based semantic memory has lower cross-contamination than monolithic profiles
- Background memory writing avoids latency impact
- Namespace isolation enforces per-user boundaries architecturally

**Cons:**
- Adds framework dependency (LangGraph/LangChain)
- Checkpointer checkpoints everything — needs filtering for sensitive spans
- Over-engineered for single `process()` tool scenario

### Anthropic's Guidance

**Core principle:** "Simple, composable patterns over complex frameworks."

Key findings:
- Tool definition is more critical than prompt optimization (SWE-bench data)
- Avoid over-abstraction — frameworks hide prompts, making debugging harder
- Validate behavior empirically rather than assuming framework behavior
- Augmented LLM = base unit with retrieval + tools + memory

---

## 4. Blackboard Pattern

**What it does:** Architectural pattern where specialist agents coordinate via a central shared workspace. Each specialist watches for matching conditions, contributes partial solutions. Solution emerges from combined contributions.

**Components:**
1. **Blackboard** — central data structure (shared workspace)
2. **Knowledge Sources** — specialist modules triggered by constraints
3. **Control Mechanism** — decides which agents to trigger

**Session persistence:** Blackboard IS the session state. Persists for problem-solving session duration. No built-in cross-session persistence.

| Aspect | Assessment |
|--------|-----------|
| Privacy safety | High — specialists isolated, controlled message passing |
| Session support | Inherent — board = session state |
| MCP fit | Indirect — MCP tools as specialists, resources as board |
| Complexity | Medium-High — coordination overhead |

**Pros for Privacy Router:**
- Natural fit — Extractor, Judge, Router, Masker are already isolated specialists
- Each specialist sees only input + board state — privacy by architecture
- Existing Extract→Judge→Mask flow is already a sequential blackboard

**Cons for Privacy Router:**
- Adds coordination overhead for linear pipeline
- Over-engineered for single-agent scenarios
- Assumes concurrent specialists — Privacy Router runs sequentially
- No built-in persistence model

---

## 5. Implemented State

The 2026-06-08 survey informed the design, but its original recommendation is no longer the runtime contract. Current implementation details follow the code and the maintained [Storage](storage.md), [Database Structure](database-erd.md), and [Security](../user/security.md) documents.

| Data | Current handling |
|---|---|
| Extraction result and labeled context | Fernet-encrypted `extraction_cache`; 24-hour inactivity TTL |
| Original masking spans | Fernet-encrypted `masking_records.span`; 24-hour session TTL |
| Placeholders | Request-scoped random `CATEGORY#random8` tokens |
| Equality checks | Keyed HMAC-SHA256 in `value_hash`, never embedded in the placeholder |
| Stored OpenResponses resources | Fernet-encrypted JSON; 24-hour TTL |
| Usage logs | Metadata only; no prompt, response, span, or input fingerprint |

The API rejects expired rows on read and physically deletes them at startup and in an hourly retention sweep.
## 6. Adopted Architecture

The implementation adopts a scoped, database-backed contract store but rejects the survey's deterministic-placeholder proposal.

```text
Request
  -> extraction cache keyed by chat_id
  -> rule-based routing decision
  -> request-scoped random placeholders
  -> encrypted masking contract keyed by session_id
  -> external or local model route
  -> owner-bound hydration
```

### 6.1 Persistence Rules

- Persist only the raw values required for hydration, and encrypt them with Fernet.
- Encrypt extracted records, labeled conversation context, and stored response resources.
- Never persist prompt or response bodies in usage logs.
- Never derive externally visible placeholders from original values.
- Use a separate keyed HMAC only when equality comparison is required.
- Enforce 24-hour read-time expiry and physical cleanup for raw-data containers.

### 6.2 Anti-Patterns

| Anti-pattern | Why |
|---|---|
| Deterministic placeholder from a value hash | Enables cross-request correlation and offline guessing |
| Plain SHA-256 input fingerprint | Supports dictionary attacks on low-entropy prompts |
| Plaintext masking contract or response storage | Exposes raw content on DB compromise |
| LLM-controlled memory writes | Lets a model decide which sensitive values persist |
| Treating TTL as a read check only | Leaves expired ciphertext indefinitely |
| Sending full prior context to an external model | Can reintroduce previously protected values |

## 7. Survey Outcome

| Option | Outcome |
|---|---|
| Framework-owned memory | Rejected; retention must stay under Privacy Router control |
| Generic MCP memory server | Rejected for raw masking contracts |
| Full graph or blackboard memory | Rejected as unnecessary for a linear pipeline |
| Scoped SQLModel stores | Adopted for extraction context, masking contracts, and stored responses |

The survey remains background research. The maintained runtime contract is defined by the implementation and linked current documents, not by the 2026-06-08 proposals.

---

*Last updated: 2026-07-15*
