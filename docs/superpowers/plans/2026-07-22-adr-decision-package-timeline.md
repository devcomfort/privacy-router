# ADR Decision-Package Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inaccurate topic-based ADR set with three chronologically ordered, evidence-backed architecture change packages while preserving disputed proposals and maintenance rationale as historical notes.

**Architecture:** ADR-001 records SQLite adoption, ADR-002 records the dedicated administrator-key boundary, and ADR-003 records the 2026-07-21–22 browser-session and runtime hardening package. Old public-management and deprecated-test records move outside the ADR sequence because repository history does not support them as implemented architecture packages.

**Tech Stack:** Markdown, YAML frontmatter, Git historical evidence, SvelteKit static assets, JSON i18n.

## Global Constraints

- Preserve all context, rationale, consequences, alternatives, and risks from the four existing records.
- Package changes by the architecture change that actually introduced them together.
- Use plain observable titles; do not invent internal architecture terminology.
- Keep source records and public static copies byte-identical.
- Remove old filenames and update every reference; leave no aliases.
- Keep unsupported decision dates as `unknown`; never copy an implementation date into `decided`.
- Do not create an intermediate commit; this documentation is part of the existing hardening package.

---

### Task 1: Rebuild the Implemented ADR Sequence

**Files:**
- Create: `docs/dev/adr/README.md`
- Create: `docs/dev/adr/ADR-001-sqlite-default-database.md`
- Create: `docs/dev/adr/ADR-002-dedicated-admin-key.md`
- Create: `docs/dev/adr/ADR-003-browser-sessions-and-runtime-startup.md`
- Create: `docs/dev/adr/history/2026-06-public-management-proposal.md`
- Create: `docs/dev/adr/history/2026-06-deprecated-mcp-test-retention.md`
- Remove: four old ADR files under `docs/dev/adr/`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-22-adr-decision-package-timeline-design.md`.
- Produces: three implemented ADR packages, a chronological index, and two non-ADR historical notes.

- [ ] **Step 1: Write ADR-001 for SQLite adoption**

Use `decided: unknown`, `implemented: 2026-06-07`, `recorded: 2026-07-16`, `status: accepted`, and `reaffirmed_by: [ADR-003]`. Preserve the old SQLite context, rationale, consequences, and risks. Keep startup-mode and fail-closed behavior out of this storage package. Cite `e1262cce:db/session.py` plus current `db/session.py`, `db/models.py`, `tests/core/test_db_migrations.py`, and `docker-compose.yml`.

- [ ] **Step 2: Write ADR-002 for the dedicated administrator key**

Use `decided: unknown`, `implemented: 2026-07-16`, `recorded: 2026-07-22`, `status: superseded`, and `superseded_by: [ADR-003]`. Explain that `ccb32569` verifies the implementation but does not contain this dedicated-key decision record; the record is first reconstructed on 2026-07-22. Preserve its motivation, consequences, alternatives, and risks. Cite `ccb32569:server/api/auth.py`, `ccb32569:server/api/routes/keys.py`, `ccb32569:server/api/routes/proxy.py`, `ccb32569:web/src/lib/api/client.ts`, and `ccb32569:web/src/routes/admin/+page.svelte`.

- [ ] **Step 3: Write ADR-003 as the current hardening package**

Use `decided: 2026-07-21`, `implemented: "2026-07-21/2026-07-22"`, `recorded: 2026-07-22`, `status: accepted`, `supersedes: [ADR-002]`, and `reaffirms: [ADR-001]`. Package administrator password-to-session exchange, CSRF, data-plane bearer keys, public metadata, loopback-only `dev`, authenticated `serve`, fail-closed secrets and database migrations, environment-only provider credentials, usage-dashboard removal, and environment-key duplicate-hash deactivation.

Cite current `server/api/auth.py`, `server/api/session_tokens.py`, `server/api/routes/admin_session.py`, `server/api/routes/runtime.py`, `server/runtime.py`, `server/__init__.py`, `server/api/main.py`, `db/session.py`, `server/tests/test_admin_boundary.py`, `server/tests/test_server.py`, and `tests/core/test_api_lifespan.py`; cite `ccb32569:web/usage-dashboard.html` for the removed dashboard.

- [ ] **Step 4: Preserve the inaccurate public-management records as a historical note**

Move the complete old ADR-001 and ADR-002 context, decisions, consequences, and risks into `history/2026-06-public-management-proposal.md`. Add a correction section: no `web/admin.html` exists; `e1262cce` key/provider routes require `require_auth`; only early settings routes are public; `admin/` is a starter and is removed in `a2d69994`. Use `type: historical-note`, not an ADR ID.

- [ ] **Step 5: Preserve the MCP test policy as a historical note**

Move complete old ADR-004 information into `history/2026-06-deprecated-mcp-test-retention.md`. Reconcile it with `d3c80c1b` (added), `94c3f97a` (marked deprecated), and later removals. Use `type: historical-note`; do not attribute this maintenance lifecycle to ADR-003.

- [ ] **Step 6: Write the timeline index and remove old files**

Order ADR-001 through ADR-003 by verified implementation date. Show decision, implementation, and recording dates separately; document `unknown`. Add a separate historical-notes table. Delete the four old source ADR filenames only after all information is relocated.

### Task 2: Synchronize Public Copies and References

**Files:**
- Mirror: index, three ADRs, and two history notes under `web/static/docs/adr/`
- Remove: four old files under `web/static/docs/adr/`
- Modify: `docs/dev/audit-report.md`
- Modify: `web/static/docs/AUDIT_REPORT.md`
- Modify: `docs/user/security.md`
- Modify: `web/src/lib/i18n/en.json`
- Modify: `web/src/lib/i18n/ko.json`

**Interfaces:**
- Consumes: canonical source records from Task 1.
- Produces: byte-identical public copies and current references.

- [ ] **Step 1: Mirror all six canonical records exactly**

Copy the index, three ADRs, and two historical notes without rewriting links or prose.

- [ ] **Step 2: Update audit and security documentation**

Describe ADR-001 as accepted/reaffirmed, ADR-002 as superseded, and ADR-003 as current. Link disputed old records through the historical notes. Synchronize `web/static/docs/AUDIT_REPORT.md` exactly with `docs/dev/audit-report.md`. Make `docs/user/security.md` point first to the index and then to ADR-003.

- [ ] **Step 3: Update English and Korean labels**

Expose ADR-001 SQLite, ADR-002 dedicated admin key (superseded), and ADR-003 current session/runtime package. Remove ADR-004 keys.

- [ ] **Step 4: Replace all removed filename references**

Search `docs`, `web/src`, `web/static`, and `README.md`; every old ADR filename must have zero references outside the design/implementation records that explain the migration.

### Task 3: Verify Timeline, Evidence, and Published Output

- [ ] **Step 1: Parse frontmatter and validate lifecycle**

Use a one-off Python check for exactly ADR-001..003, nondecreasing implementation dates, valid relationship targets, accepted/superseded consistency, and no ADR IDs on history notes.

- [ ] **Step 2: Validate typed evidence**

Assert every current path exists, every historical `<revision>:<path>` resolves, and every deletion entry has `D` status in the declared commit while the path is absent from that commit's tree.

- [ ] **Step 3: Compare source and public checksums**

Compare all six source/public pairs; every pair must match.

- [ ] **Step 4: Search for stale guidance and links**

Require zero removed-file links and zero stale guidance in user-facing current summaries. Historical public-management claims are allowed only in the two history notes; reusable administrator-header behavior is also allowed in superseded ADR-002. Direct-`uvicorn` text is allowed only when explicitly rejected as unsupported.

- [ ] **Step 5: Run documentation-facing checks**

Run Ruff on `server/api/main.py` and `server/api/routes/proxy.py`. Run `npm run check && npm run build` under `web`; require zero Svelte errors/warnings and a successful build.
