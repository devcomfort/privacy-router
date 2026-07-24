---
id: ADR-003
title: Authenticate Management Endpoints with Browser Sessions and Separate Development from Deployment Startup
status: accepted
decided: 2026-07-21
recorded: 2026-07-22
implemented: "2026-07-21/2026-07-22"
date_basis:
  - The architecture hardening decision was made in the operator-reviewed 2026-07-21 work session.
  - Implementation and verification continued through 2026-07-22 in the current working tree.
supersedes: [ADR-002]
superseded_by: []
reaffirms: [ADR-001]
reaffirmed_by: []
related: []
evidence:
  - kind: current
    path: server/api/auth.py
  - kind: current
    path: server/api/session_tokens.py
  - kind: current
    path: server/api/routes/admin_session.py
  - kind: current
    path: server/api/routes/runtime.py
  - kind: current
    path: server/runtime.py
  - kind: current
    path: server/__init__.py
  - kind: current
    path: server/api/main.py
  - kind: current
    path: db/session.py
  - kind: current
    path: config/db_loader.py
  - kind: current
    path: server/tests/test_admin_boundary.py
  - kind: current
    path: server/tests/test_server.py
  - kind: current
    path: tests/core/test_api_lifespan.py
  - kind: historical
    revision: ccb32569
    path: web/usage-dashboard.html
---

# ADR-003: Authenticate Management Endpoints with Browser Sessions and Separate Development from Deployment Startup

## Summary

Privacy Router now separates two explicit runtime postures. `privacy-router dev` is a loopback-only browser demonstration that uses an ephemeral master key and a short-lived local demo session. `privacy-router serve` is the deployment posture: it requires a persistent master key and administrator password before startup.

Management requests exchange the administrator password for a short-lived signed `HttpOnly` session cookie. State-changing requests also present a matching CSRF token. Data-plane requests use client bearer keys, except for the loopback-only development session. Provider credentials remain server environment variables. Database initialization and privacy migrations fail closed.

This package supersedes ADR-002's reusable administrator header and explicitly reaffirms ADR-001's SQLite default.

## Context

ADR-002 improved on public or client-key management by introducing a dedicated `X-Privacy-Router-Admin-Key`. That design still placed a reusable deployment secret in browser JavaScript and repeated it on every management request. It had no browser-session lifetime, selective revocation, CSRF binding, or failed-login window.

The application also exposed one ambiguous startup path. Direct ASGI import could bypass the intended distinction between a local browser demo and an authenticated deployment. Missing persistent secrets were discovered only when a protected path ran. Database migration failures could leave operators uncertain whether the service had accepted traffic.

Provider credentials had previously moved through database-backed encrypted-key designs. The resulting key ownership and master-key fallback rules were difficult to audit. The service needed one explicit rule: outbound provider secrets belong to the deployment environment, while SQLite stores only the environment-variable name and availability metadata.

The hardening work changed these boundaries together. Treating authentication, runtime mode, startup validation, credential ownership, and migration behavior as separate topic records would hide their shared purpose: make the selected runtime posture explicit before the service accepts requests.

## Decision

### Management authentication

Use `PRIVACY_ROUTER_ADMIN_PASSWORD` only for a password-to-session exchange at `POST /api/admin/session`. On success, issue a signed 30-minute `HttpOnly`, `SameSite=Strict`, `Path=/api` cookie. Bind the encrypted session subject to a SHA-256 digest of a random CSRF token. Require the matching `X-Privacy-Router-CSRF-Token` for `POST`, `PATCH`, `PUT`, and `DELETE` management requests.

Use constant-time comparison for the administrator password and CSRF digest. Apply a bounded failed-login window per directly connected peer. Reject management login over insecure non-loopback transport unless the deployment explicitly opts into the documented Docker bridge exception.

### Request boundaries

- Management routes require the administrator session; state changes also require CSRF.
- LLM-facing data routes require `Authorization: Bearer pr-...`.
- `/v1/models` and `/api/runtime` expose non-secret metadata without authentication.
- In `dev` mode only, a loopback peer can obtain a short-lived demo session for browser chat. It cannot select external models.

### Runtime startup

- `privacy-router dev` forces a loopback host, creates an ephemeral process master key when needed, and uses local model configuration.
- `privacy-router serve` requires a valid persistent `PRIVACY_ROUTER_MASTER_KEY` and `PRIVACY_ROUTER_ADMIN_PASSWORD` before importing and starting the API stack.
- The FastAPI lifespan initializes the database, runs privacy migrations, and propagates failures. The server does not accept traffic after a failed initialization.
- Direct `uvicorn server.api.main:app` is not a supported startup instruction because direct import has the secure deployment posture and therefore requires deployment secrets.

### Credential ownership

Store only `provider.api_key_env` in SQLite. Resolve provider keys from the named server environment variable; the built-in OpenRouter provider uses `OPENROUTER_API_KEY`. Do not persist raw, encrypted, preview, or fingerprint forms of provider credentials. Startup migration purges and removes legacy credential columns.

### Client-key bootstrap

Allow deployment integrations to supply a fixed `PRIVACY_ROUTER_API_KEY` of at least 24 characters beginning with `pr-`. Store only its SHA-256 hash. The environment-managed row owns both its previous and next hashes during rotation; deactivate other rows that collide with either hash so rotation cannot leave the old environment secret active through a duplicate row.

## Included Changes

- Replace `X-Privacy-Router-Admin-Key` with password-to-session exchange and CSRF.
- Add explicit `dev` and `serve` runtime modes.
- Require persistent deployment secrets before server startup.
- Restrict development sessions to the directly connected loopback peer.
- Keep data-plane keys separate from management sessions.
- Make provider credentials environment-only and remove legacy stored-key columns.
- Propagate database initialization and privacy migration failures.
- Preserve SQLite as the default database when `DATABASE_URL` is unset.
- Remove the obsolete `web/usage-dashboard.html` surface that used the retired administrator header.
- Make environment client-key bootstrap idempotent, redacted, rotation-safe, and collision-safe.
- Update the Svelte `/admin` UI to use session cookies and in-memory CSRF state rather than a reusable administrator secret.

## Evidence

| Evidence | What it establishes |
|---|---|
| `server/api/auth.py` | Loopback detection, administrator-session validation, CSRF enforcement, client bearer keys, and environment-key bootstrap ownership. |
| `server/api/session_tokens.py` | Purpose-derived Fernet session tokens, expiry, and subject verification. |
| `server/api/routes/admin_session.py` | Password exchange, secure-cookie policy, login throttling, status, and logout. |
| `server/api/routes/runtime.py` | Public capabilities and loopback-only development-session issuance. |
| `server/runtime.py`, `server/__init__.py` | Explicit runtime mode and CLI startup validation. |
| `server/api/main.py` | Fail-closed lifespan initialization and supported CLI guidance. |
| `db/session.py`, `config/db_loader.py` | SQLite fallback, legacy provider-key purge, and environment credential resolution. |
| `server/tests/test_admin_boundary.py` | Management boundary, CSRF, transport, demo-session, and environment-key regression coverage. |
| `server/tests/test_server.py` | CLI mode and required-secret startup coverage. |
| `tests/core/test_api_lifespan.py` | Database initialization failure prevents startup. |
| `ccb32569:web/usage-dashboard.html` | Historical dashboard removed because it used the superseded reusable administrator-header flow. |

## Consequences

### Positive

- Browser JavaScript never stores or repeats the administrator password after login.
- Management sessions expire after 30 minutes and become unverifiable after master-key rotation.
- CSRF state is bound to the signed session and compared in constant time.
- Development convenience cannot silently become a remotely reachable deployment posture.
- Deployment configuration errors and migration failures stop startup before traffic is accepted.
- Provider secrets have one auditable source and never enter API responses or SQLite.
- Client-key rotation cannot preserve an old secret through a duplicate active hash.
- SQLite remains available for local and single-node use without weakening deployment startup rules.

### Negative

- Operators must provision two deployment secrets: a persistent master key and administrator password.
- Changing `PRIVACY_ROUTER_ADMIN_PASSWORD` does not revoke an already-issued session because session verification does not consult the password.
- Browser sessions depend on cookie and CSRF handling, increasing boundary-test surface.
- Plain HTTP administration is rejected outside the explicit loopback/Docker bridge exception.
- Rotating the master key invalidates all browser and masking-session ciphertext derived from it.
- Environment-only provider credentials require a restart or deployment-secret refresh rather than UI editing.
- `dev` and `serve` are intentionally different, so a demo cannot be used as a production launch shortcut.

## Alternatives Considered

### Keep the reusable administrator header

Rejected because the browser repeatedly handled a long-lived deployment secret and the server could not express session lifetime or CSRF binding.

### Use client bearer keys for management

Rejected because client keys are managed resources and should not automatically grant configuration authority.

### Add persistent administrator accounts or SSO

Not selected for the current single-operator service. It would add account storage, recovery, role policy, and identity-provider dependencies without replacing the need for secure startup secrets.

### Keep one startup command with flags

Rejected because the security posture would remain implicit. Separate verbs make loopback demo behavior and authenticated deployment behavior observable before import.

### Store encrypted provider keys in SQLite

Rejected because encryption still leaves key lifecycle and master-key ownership inside the application database. Environment or deployment secret management gives the provider credential one external owner.

### Require PostgreSQL in deployment mode

Rejected. Runtime authentication and fail-closed startup do not require changing the storage decision; ADR-001 remains valid.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Administrator password guessing | Medium | High | High-entropy deployment secret, bounded per-peer login attempts, TLS or authenticated ingress. |
| Administrator password rotation leaves issued sessions valid until expiry | Medium | Medium | Rotate the master key when immediate global revocation is required; otherwise wait for the 30-minute TTL. |
| CSRF token mismatch or stale session | Medium | Low | Return explicit `401`/`403`; clear browser session state and reauthenticate. |
| Insecure administration exposed beyond loopback | Medium | High | Reject it by default; bind Compose ports to loopback; require explicit override only for the bridge topology. |
| Master-key loss makes encrypted records unreadable | Low | High | Provision and back up a persistent deployment key; do not auto-generate one in `serve`. |
| SQLite contention under deployment load | Medium | Medium | Keep ADR-001's PostgreSQL opt-in for multi-user or sustained write workloads. |
| Environment provider secret missing | Medium | Medium | Report availability metadata without exposing values; fail the outbound operation rather than storing a fallback credential. |
| Demo-session privilege expands to external models | Low | High | Restrict demo issuance to loopback and enforce local-model selection at the server boundary. |
| Database migration fails after a release | Low | High | Abort lifespan startup and repair the schema before accepting traffic. |

## History

- **2026-07-16:** ADR-002's reusable administrator-key implementation is verified in `ccb32569`.
- **2026-07-21:** Operator-reviewed hardening decision establishes browser sessions, runtime separation, and fail-closed deployment requirements.
- **2026-07-22:** Implementation, legacy cleanup, collision handling, documentation, and regression verification complete in the working tree.
