# Architecture Decision Timeline

Privacy Router numbers ADRs by the order of verified architecture change packages. A package groups changes introduced together for one coherent reason. Numbers do not indicate topic importance or whether a decision remains active.

## How to read the dates

| Field | Meaning |
|---|---|
| `decided` | Independently supported decision date. It is `unknown` when only implementation or later documentation is observable. |
| `implemented` | Earliest verified implementation date or the verified implementation range. This orders records when `decided` is unknown. |
| `recorded` | Date the decision record itself was first written or reconstructed, which can be later than implementation. |
| `date_basis` | Evidence and uncertainty behind the three dates. |

An implementation commit is evidence that a design existed by that date; it is not automatically evidence that the decision was made on that date.

## Implemented architecture decisions

| Sequence | Decided | Implemented | Recorded | Status | Decision package | Relationship |
|---|---|---|---|---|---|---|
| [ADR-001](ADR-001-sqlite-default-database.md) | unknown | 2026-06-07 | 2026-07-16 | Accepted | Use SQLite by default while keeping PostgreSQL configurable. | Reaffirmed by ADR-003 |
| [ADR-002](ADR-002-dedicated-admin-key.md) | unknown | 2026-07-16 | 2026-07-22 | Superseded | Separate management authority from client bearer keys with a dedicated administrator header. | Superseded by ADR-003 |
| [ADR-003](ADR-003-browser-sessions-and-runtime-startup.md) | 2026-07-21 | 2026-07-21–22 | 2026-07-22 | Accepted | Replace the reusable administrator header with browser sessions and CSRF; separate loopback development from fail-closed deployment startup. | Supersedes ADR-002; reaffirms ADR-001 |

## Current architecture in one pass

1. **Storage:** SQLite is the default; PostgreSQL is selected through `DATABASE_URL` when deployment needs it.
2. **Management:** the administrator password creates a short-lived signed browser session; state changes also require CSRF.
3. **Data plane:** client bearer keys authorize LLM-facing routes; only the loopback development session can use browser chat without one.
4. **Startup:** `privacy-router dev` is loopback-only; `privacy-router serve` requires persistent deployment secrets and stops on database or migration failure.
5. **Provider credentials:** provider keys are read from server environment variables and are not stored in SQLite or returned by the API.

## Historical notes outside the ADR sequence

These records preserve rationale and risks but do not represent verified architecture packages.

| Period | Note | Why it is not an ADR |
|---|---|---|
| 2026-06 | [Public management proposal](history/2026-06-public-management-proposal.md) | The earlier records claimed a public standalone management architecture that repository snapshots do not show as a complete implementation. |
| 2026-06 | [Deprecated MCP test retention](history/2026-06-deprecated-mcp-test-retention.md) | Retaining an intentionally broken test was repository maintenance, not a runtime architecture boundary. |

## Relationship rules

- `supersedes` means the later package replaces an implemented earlier package.
- `reaffirms` means the later package explicitly keeps an earlier decision while changing adjacent architecture.
- Superseded records preserve their own historical rationale; current behavior is defined only by the later record.
- Proposals or maintenance notes without a verified architecture implementation remain in `history/` and receive no ADR ID.

## Record format

Each ADR uses YAML frontmatter for lifecycle and evidence, then the same prose order: Summary, Context, Decision, Included Changes, Evidence, Consequences, Alternatives Considered, Risks and Mitigations, and History. Historical evidence uses `revision:path`; current evidence uses working-tree paths.
