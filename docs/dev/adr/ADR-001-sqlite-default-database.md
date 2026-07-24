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
  - The earlier ADR claims 2026-06-16; its first repository copy is ccb32569 dated 2026-07-16.
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
  - kind: current
    path: db/models.py
  - kind: current
    path: tests/core/test_db_migrations.py
  - kind: current
    path: docker-compose.yml
---

# ADR-001: Use SQLite as the Default Database

## Summary

Privacy Router uses a local SQLite file when `DATABASE_URL` is unset. PostgreSQL remains an opt-in deployment database. ADR-003 reaffirms this storage choice while changing how development and deployment startup handle configuration and migration failures.

## Context

Privacy Router needs persistent storage for model configuration, client-key hashes, usage metadata, responses, masking sessions, masking records, and extraction cache entries. Requiring a database service for every local run would add installation and demo overhead.

The SQLModel data layer supports both SQLite and PostgreSQL. The earliest verified implementation, `e1262cce:db/session.py`, selects SQLite by default. The current implementation keeps the same boundary:

```python
DATABASE_URL = _env_db_url or os.getenv("DATABASE_URL", "sqlite:///privacy_router.db")
```

The earlier record states a decision date of 2026-06-16, but no independent decision artifact supports that date. This ADR therefore records `decided: unknown`, the verified implementation date, and the later recording date separately.

## Decision

Use `sqlite:///privacy_router.db` when `DATABASE_URL` is not set. Allow deployments to select PostgreSQL by setting `DATABASE_URL` explicitly; Docker Compose does so for its database service.

The database choice is independent of runtime security posture. ADR-003 owns the current `privacy-router dev` and `privacy-router serve` startup rules, required deployment secrets, and fail-closed migration behavior.

## Included Changes

- Select a single-file SQLite database by default.
- Keep SQLModel models portable across SQLite and PostgreSQL.
- Accept a PostgreSQL URL through `DATABASE_URL` without changing application code.
- Use PostgreSQL in Docker Compose for the multi-service deployment topology.
- Run schema creation and privacy migrations through the shared data layer; startup behavior belongs to ADR-003.

## Evidence

| Evidence | What it establishes |
|---|---|
| `e1262cce:db/session.py` | Earliest verified SQLite default implementation on 2026-06-07. |
| `db/session.py` | Current `DATABASE_URL` fallback and SQLModel engine creation. |
| `db/models.py` | Database-neutral SQLModel schema. |
| `tests/core/test_db_migrations.py` | Current migration and legacy-sensitive-data cleanup contracts. |
| `docker-compose.yml` | PostgreSQL deployment URL and service topology. |

## Consequences

### Positive

- Local development and focused tests do not require a separate database service.
- The database is a single file, which simplifies reset, backup, and isolated test setup.
- The application can move to PostgreSQL through configuration rather than model rewrites.
- SQLModel provides one data model across both supported databases.

### Negative

- SQLite file-level locking limits sustained concurrent writes; parallel request logging can encounter lock contention.
- SQLite does not provide replication, managed snapshots, or point-in-time recovery.
- SQL and migration behavior can differ between SQLite and PostgreSQL.
- Deleting or corrupting the local file loses data unless it has been backed up.

## Alternatives Considered

### Require PostgreSQL everywhere

Rejected for the default path because it adds a service dependency to local development and demonstrations. It remains the deployment option when concurrency and durability matter.

### Keep all state in memory

Rejected because model configuration, key metadata, privacy records, and retention enforcement must survive process restarts.

### Maintain separate SQLite and PostgreSQL model layers

Rejected because duplicated schemas and migrations would increase drift without adding a useful domain boundary.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Lock contention under concurrent writes | Medium | Medium | Use short transactions; deploy PostgreSQL for multi-user or sustained workloads. |
| SQLite file deletion or corruption | Medium | High | Back up persistent installations; use PostgreSQL when managed durability is required. |
| Dialect differences surface only in deployment | Medium | Medium | Keep SQL portable and run database integration checks before production release. |
| Migration or initialization failure leaves an unknown schema | Low | High | ADR-003 requires startup to fail closed until the database is repaired. |

## History

- **2026-06-07:** SQLite fallback first appears in `e1262cce`.
- **2026-06-16:** Date claimed by the earlier ADR; independent decision evidence was not found.
- **2026-07-16:** Earlier ADR first appears in repository commit `ccb32569`.
- **2026-07-21–22:** ADR-003 reaffirms SQLite as the default while separating runtime startup and making migrations fail closed.
