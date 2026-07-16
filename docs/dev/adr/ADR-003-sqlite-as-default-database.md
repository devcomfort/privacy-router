# ADR-003: SQLite as the Default Database

## Date

2026-06-16

## Status

Accepted

## Context

The data access layer (`db/session.py`) uses SQLModel/SQLAlchemy and selects a database URL from the environment:

```python
DATABASE_URL = _env_db_url or os.getenv("DATABASE_URL", "sqlite:///privacy_router.db")
```

If `DATABASE_URL` is not set, the application defaults to a local SQLite file named `privacy_router.db`. The repository includes `.env.example` with PostgreSQL credentials, but those credentials are only meaningful when a PostgreSQL service is running (e.g., via Docker Compose). In practice, developers run the server directly with `uvicorn`, and no PostgreSQL instance is guaranteed to be available. The startup logic in `server/api/main.py` calls `init_db()` during the application lifespan and silently ignores failures, which means the system will start with whatever engine URL resolves.

## Decision

Retain SQLite as the default database and keep PostgreSQL as an opt-in configuration via `DATABASE_URL`.

Rationale:

1. **Zero external dependency**: SQLite lets a new contributor or demo user run the entire application after `pip install` without starting a separate database service.
2. **Single-file portability**: The database is a single file on disk, making backups, resets, and CI setups trivial.
3. **SQLModel compatibility**: The model definitions are database-agnostic; switching to PostgreSQL only requires changing the URL.
4. **PostgreSQL is supported but not required**: Production deployments can set `DATABASE_URL=postgresql://...` to use a server-grade database when one is available.

## Consequences

Positive:

- `uvicorn server.api.main:app` works immediately on a fresh clone.
- No Docker, `pg_ctl`, or cloud database is needed for development, demos, or small internal deployments.
- Schema creation is handled automatically by `SQLModel.metadata.create_all(engine)`.

Negative:

- SQLite's file-level locking limits write concurrency; multiple parallel writers can encounter `database is locked` errors under load.
- Durability and backup features (point-in-time recovery, replication, managed snapshots) are not provided by SQLite alone.
- Some SQLModel/SQLAlchemy features and migrations may behave differently between SQLite and PostgreSQL.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Performance degradation or lock contention under concurrent LLM requests that write usage logs | Medium | Medium | Increase SQLite timeout/wal mode; or set `DATABASE_URL` to PostgreSQL for production/multi-user deployments. |
| Data loss if the SQLite file is deleted, corrupted, or not backed up | Medium | High | Document that SQLite is for development/demo; encourage PostgreSQL for persistent production data; add periodic backups. |
| Subtle dialect differences causing bugs that only appear in production PostgreSQL | Medium | Medium | Run integration tests against PostgreSQL in CI before declaring production readiness; keep SQL simple and portable. |
| `init_db()` silently swallowing exceptions and leaving the app in an undefined state | Low | Medium | Log startup failures rather than silently passing; fail fast when a configured PostgreSQL URL is unreachable. |
