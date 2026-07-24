---
type: historical-note
topic: Public management endpoints for a standalone browser admin application
status: corrected
claimed_date: 2026-06-16
recorded: 2026-07-16
date_basis:
  - The two earlier ADRs claim 2026-06-16.
  - Their first repository copies appear in ccb32569 on 2026-07-16.
  - Repository snapshots do not show the claimed architecture as a complete implemented package.
evidence:
  - kind: historical
    revision: e1262cce
    path: admin/src/routes/+page.svelte
  - kind: historical
    revision: e1262cce
    path: server/api/routes/keys.py
  - kind: historical
    revision: e1262cce
    path: server/api/routes/providers.py
  - kind: historical
    revision: e1262cce
    path: server/api/routes/proxy.py
  - kind: deletion
    revision: a2d69994
    path: admin/src/routes/+page.svelte
  - kind: historical
    revision: ccb32569
    path: docs/dev/adr/ADR-001-no-auth-on-key-admin-endpoints.md
  - kind: historical
    revision: ccb32569
    path: docs/dev/adr/ADR-002-public-admin-endpoints-for-standalone-ui.md
---

# Historical Note: Public Management for a Standalone Browser Admin Application

## Why this is not an ADR

The previous ADR-001 and ADR-002 described one proposed operating model: management routes would remain public so a standalone browser administrator UI could work without login credentials, sessions, SSO, or a pre-provisioned key. The records divided the authentication rationale and UI rationale into separate files even though they described the same package.

Repository history does not establish that package as implemented architecture. The information remains valuable as a proposal, threat analysis, and rejected alternative, so this note preserves it outside the numbered ADR sequence.

## Claims in the Earlier Records

The earlier records described Privacy Router as a local-workstation or trusted-network service with two surfaces:

- LLM-facing routes protected by bearer API keys;
- key, provider, profile, telemetry, dashboard, and settings management routes left public.

They listed these management operations:

- list, create, renew, update, bulk-toggle, bulk-delete, and delete client keys;
- list and update providers;
- read and update model/agent settings;
- list and activate profiles;
- read telemetry and dashboard data.

They also claimed a standalone `web/admin.html` application used plain `fetch()` without an authorization header or session cookie. Permissive CORS and local binding were treated as sufficient for a first-run browser workflow.

## Proposed Decision

The proposed package would leave management routes without `require_auth` so a browser administrator could configure the service and create the first client key without a separate authentication flow.

The two earlier documents gave these reasons:

1. **Local or trusted network assumption:** application-level management authentication was treated as network policy.
2. **Bootstrap simplicity:** requiring a client key to create the first client key creates a circular dependency.
3. **Avoid account-management cost:** persistent administrator accounts introduce password hashing, reset, session, role, and identity-provider work.
4. **Standalone UI compatibility:** adding backend authentication without a matching browser flow would break management.
5. **Scope control:** a full login, token-refresh, and role system was deferred.
6. **Permissive CORS already existed:** authentication, CORS, and browser secret storage needed to be designed together rather than patched independently.

## Expected Consequences

### Positive

- The administrator UI would work on first run.
- A first client API key could be created without an existing credential.
- No administrator account database, identity provider, password reset, or session store would be required.
- The API would have a simple public management surface and key-protected data surface.

### Negative

- Any process or user that could reach the management port could alter keys and runtime configuration.
- Accidental LAN or public binding would expose high-impact control operations.
- Cross-origin or drive-by requests could trigger state changes.
- Administrative actions could not be attributed to an authenticated principal.
- Rate limiting and abuse detection for administrator actions were absent.
- A later authentication migration would require coordinated server and browser changes.

## Risks Recorded at the Time

| Risk | Claimed likelihood | Impact | Proposed mitigation |
|---|---:|---:|---|
| Unauthorized key creation, renewal, revocation, or configuration changes | High on shared networks | High | Bind to `127.0.0.1`; use firewall, VPN, mTLS, or authenticated reverse proxy. |
| Accidental public bind | Medium | High | Document the local-only model and warn on explicit host changes. |
| CSRF or cross-origin state changes | Medium | High | Avoid untrusted browsing during use; later add SameSite cookies and CSRF. |
| Metadata disclosure through key listing | Medium | Medium | Keep the management port private; never return raw key values. |
| No accountable administrator identity | Medium | Medium | Add authenticated administration before compliance-sensitive deployment. |
| Browser/server migration drift | Medium | Low | Keep authentication dependencies explicit and migrate both surfaces together. |

## Repository Evidence Correction

### The cited `web/admin.html` did not exist

No repository revision contains `web/admin.html`. The separate `admin/` SvelteKit project exists in `e1262cce`, but `admin/src/routes/+page.svelte` is the default “Welcome to SvelteKit” starter page rather than the management application described by the records. Commit `a2d69994` removes the `admin/` project on 2026-06-08.

### Key and provider routes were not public in the earliest verified snapshot

In `e1262cce` on 2026-06-07:

- `server/api/routes/keys.py` applies `Depends(require_auth)` to key operations;
- `server/api/routes/providers.py` applies `Depends(require_auth)` to provider operations;
- `server/api/routes/proxy.py` does expose early settings routes without the same dependency.

Thus, one narrow public-settings fact is verified, but the claimed public management package is not.

### The first recorded ADR snapshot already contains a different boundary

The old ADR files first appear in `ccb32569` on 2026-07-16. In that same revision:

- management routes use `Depends(require_admin_auth)`;
- `require_admin_auth` checks `X-Privacy-Router-Admin-Key` against `PRIVACY_ROUTER_ADMIN_KEY`;
- the working Svelte `/admin` UI supplies that key.

That verified implementation is now ADR-002. ADR-003 later supersedes it with browser sessions and CSRF.

## Disposition

- The proposal is **not** part of the implemented ADR sequence.
- Its bootstrap problem, alternatives, consequences, and risks remain preserved here.
- ADR-002 records the first verifiable dedicated management-authentication package.
- ADR-003 records the current browser-session and runtime hardening package.
