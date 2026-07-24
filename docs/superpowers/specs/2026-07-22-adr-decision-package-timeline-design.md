# ADR Decision-Package Timeline Design

## Goal

Rebuild the Privacy Router architecture decision records as a chronological sequence of architecture changes that actually occurred together. Preserve the information in the existing records, but distinguish implemented decisions from proposals or maintenance notes whose claims do not match repository history.

## Evidence Correction

The original ADR set cannot be renumbered at face value:

- The old ADR-001 and ADR-002 claim that key, provider, and settings management were publicly accessible for a standalone `web/admin.html` application.
- No repository revision contains `web/admin.html`.
- In the earliest relevant implementation, `e1262cce` on 2026-06-07, key and provider routes already require `Depends(require_auth)`. The separate `admin/` project contains only the default Svelte starter page and is removed in `a2d69994` on 2026-06-08.
- Early `/api/settings` routes are public, but that narrower fact does not support the claimed public management architecture.
- In `ccb32569` on 2026-07-16, management routes require a dedicated `X-Privacy-Router-Admin-Key`, and the working Svelte `/admin` UI sends it.
- The old ADR-004 describes test-file retention, a repository-maintenance policy rather than an architecture boundary. Its lifecycle also conflicts with repository history.

These records remain useful as historical proposals and rationale, but they must not occupy the implemented ADR sequence.

## Decision-Package Model

An ADR represents one architecture change package: changes introduced together for one coherent reason. It does not represent every topic that remains valid, and it does not promote an unimplemented proposal into architecture history.

The reconstructed implemented sequence contains three packages.

### ADR-001 — Use SQLite as the Default Database

- First verified implementation: `e1262cce`, 2026-06-07.
- Independent decision date: unknown.
- First repository copy of the old decision record: `ccb32569`, 2026-07-16.
- Status: `accepted`.
- Reaffirmed by ADR-003.
- Scope: SQLite default, PostgreSQL opt-in, portability, concurrency limits, and dialect risks.

### ADR-002 — Use a Dedicated Administrator Key for Management Endpoints

- Verified implementation: `ccb32569`, 2026-07-16.
- Existing historical text claims the earlier unauthenticated design was superseded on 2026-07-15, but no independent decision record verifies that date; `decided` remains `unknown`.
- First dedicated-key decision record: this evidence-grounded reconstruction, 2026-07-22. The earlier ADRs recorded a different public-management claim.
- Status: `superseded`.
- Superseded by ADR-003.
- Scope: dedicated `X-Privacy-Router-Admin-Key`, management-route dependency wiring, and browser admin key handling.

### ADR-003 — Authenticate Management Endpoints with Browser Sessions and Separate Development from Deployment Startup

- Decision recorded in the 2026-07-21 hardening session; implemented across 2026-07-21–22.
- Status: `accepted`.
- Supersedes ADR-002 and reaffirms ADR-001.
- Includes the architecture changes introduced together:
  - administrator password exchange for short-lived signed browser sessions;
  - CSRF protection for state-changing management requests;
  - data-plane bearer keys and explicitly public metadata routes;
  - loopback-only `privacy-router dev` and authenticated `privacy-router serve` modes;
  - fail-closed master-key, administrator-password, database-initialization, and migration checks;
  - environment-only provider credentials;
  - removal of the obsolete unauthenticated usage dashboard;
  - environment client-key bootstrap ownership and duplicate-hash deactivation.

## Historical Notes Outside the ADR Sequence

### Public-management proposal

Move the complete information from old ADR-001 and ADR-002 to `docs/dev/adr/history/2026-06-public-management-proposal.md`. Preserve their context, rationale, consequences, and risks, then add an evidence correction explaining which claims were not implemented. The note receives no ADR number.

### Deprecated MCP test retention

Move the complete information from old ADR-004 to `docs/dev/adr/history/2026-06-deprecated-mcp-test-retention.md`. Preserve its rationale, consequences, and risks, then reconcile them with Git history: the test was added in `d3c80c1b` on 2026-06-08, marked deprecated in `94c3f97a` on 2026-06-09, and removed in later cleanup. The note receives no ADR number.

## Frontmatter Schema

Every implemented ADR uses YAML frontmatter:

```yaml
---
id: ADR-001
title: Use SQLite as the Default Database
status: accepted
decided: unknown
recorded: 2026-07-16
implemented: 2026-06-07
date_basis:
  - No independent decision-date evidence was found.
  - SQLite first appears in e1262cce on 2026-06-07.
  - The first repository copy of the old ADR is ccb32569 dated 2026-07-16.
supersedes: []
superseded_by: []
reaffirms: []
reaffirmed_by: [ADR-003]
related: []
evidence:
  - kind: historical
    revision: e1262cce
    path: db/session.py
  - kind: current
    path: db/session.py
---
```

Field meanings:

- `decided`: independently evidenced decision date; `unknown` when only implementation or later documentation is observable.
- `recorded`: date the decision record itself was first written or reconstructed, not the date of an implementation snapshot.
- `implemented`: verified implementation date or range; this is the chronological sort key when `decided` is unknown.
- `date_basis`: provenance for each date, including conflicting earlier claims.
- `supersedes` / `superseded_by`: replacement relationships between implemented change packages.
- `reaffirms` / `reaffirmed_by`: an earlier decision explicitly retained by a later package.
- `related`: relevant records without lifecycle implications.
- `evidence`: typed references. `current` entries name working-tree paths; `historical` entries name a Git revision and a path present in that revision; `deletion` entries name a commit whose diff marks the path `D` and whose post-commit tree no longer contains it.

Historical notes use `type: historical-note`, a plain-language `topic`, and typed evidence. They do not use ADR IDs or lifecycle relationships.

## Document Structure

Each ADR uses the same reading order:

1. Summary
2. Context
3. Decision
4. Included Changes
5. Evidence
6. Consequences
7. Alternatives Considered
8. Risks and Mitigations
9. History

Historical records describe their own period in the past tense. Current records use the present tense. A later package owns its current behavior; older records only link to it through frontmatter and History.

## Timeline Index

Create `docs/dev/adr/README.md` with:

- an implemented ADR table ordered by verified implementation date;
- decision, implementation, and recording dates as separate columns;
- status and lifecycle relationships;
- a one-sentence change-package summary;
- a separate historical-notes table for unimplemented proposals and maintenance policies.

ADR numbers follow verified change-package chronology, not topic importance or current validity. Unknown decision dates are never inferred from implementation dates.

## Evidence Rules

- Every current behavior claim cites code, configuration, or test evidence using `kind: current`.
- Historical claims cite a `kind: historical` Git revision and path.
- Deleted artifacts use `kind: deletion`; the declared commit must delete the path and the post-commit tree must not contain it.
- Historical proposal claims are labeled as claims and followed by the repository evidence that confirms or rejects them.
- Route-authentication evidence includes dependency wiring and boundary tests.
- Runtime evidence includes CLI mode selection, startup validation, lifespan initialization, and fail-closed tests.
- Storage evidence includes the database URL default, SQLModel session setup, and migration tests.

## Synchronization Scope

Update as one atomic documentation change:

- `docs/dev/adr/` ADRs, index, and historical notes;
- `web/static/docs/adr/` exact public copies;
- `docs/dev/audit-report.md` and `web/static/docs/AUDIT_REPORT.md`;
- `docs/user/security.md` cross-references;
- English and Korean ADR labels in `web/src/lib/i18n/`;
- every link to removed ADR filenames.

## Verification

- Source and public copies have matching checksums.
- No link references a removed ADR filename.
- Frontmatter parses as YAML and relationship targets exist.
- Verified implementation dates are nondecreasing by ADR number.
- Accepted records are not superseded; superseded records identify their replacement.
- Every current path exists; every historical path resolves at its declared revision; every deletion entry has `D` status in the declared commit and is absent from its post-commit tree.
- Historical notes have no ADR ID.
- Current summaries contain no stale public-management, direct-`uvicorn`, reusable admin-header, or broken-test-retention guidance.
- Svelte checks and the production build pass.
