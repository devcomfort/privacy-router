---
id: ADR-002
title: Use a Dedicated Administrator Key for Management Endpoints
status: superseded
decided: unknown
recorded: 2026-07-22
implemented: 2026-07-16
date_basis:
  - No independent decision-date evidence was found.
  - The earlier ADR says unauthenticated management was superseded on 2026-07-15.
  - The dedicated administrator-key implementation and working browser UI first appear together in ccb32569 on 2026-07-16.
  - This dedicated-key decision record was reconstructed from implementation evidence on 2026-07-22.
supersedes: []
superseded_by: [ADR-003]
reaffirms: []
reaffirmed_by: []
related: [ADR-001]
evidence:
  - kind: historical
    revision: ccb32569
    path: server/api/auth.py
  - kind: historical
    revision: ccb32569
    path: server/api/routes/keys.py
  - kind: historical
    revision: ccb32569
    path: server/api/routes/proxy.py
  - kind: historical
    revision: ccb32569
    path: web/src/lib/api/client.ts
  - kind: historical
    revision: ccb32569
    path: web/src/routes/admin/+page.svelte
---

# ADR-002: Use a Dedicated Administrator Key for Management Endpoints

## Summary

The 2026-07-16 implementation separated management authentication from client request authentication. Management routes accepted `X-Privacy-Router-Admin-Key`, configured through `PRIVACY_ROUTER_ADMIN_KEY`; data-plane routes continued to accept `Authorization: Bearer pr-...`. The Svelte administrator UI held the administrator key in memory and attached it to management requests.

ADR-003 supersedes this reusable-header design with a password-to-session exchange and CSRF protection.

## Context

Client API keys authorize LLM-facing requests and are themselves managed through the administrator interface. Reusing a client key to create, renew, disable, or delete client keys creates a bootstrap and privilege-boundary problem. Leaving those routes public exposes high-impact state changes to any network peer.

The dedicated administrator-key package addresses that boundary without introducing persistent administrator accounts. A deployment operator supplies one environment secret. The server compares the incoming header in constant time, and the browser UI keeps the value only in process memory.

The earlier records claim a broader unauthenticated management model and a 2026-07-15 superseding decision. Git history verifies the dedicated-key implementation on 2026-07-16 but does not independently verify the decision date; `decided` therefore remains `unknown`.

## Decision

Require the `X-Privacy-Router-Admin-Key` header on management routes. Read the expected value from `PRIVACY_ROUTER_ADMIN_KEY`; return `503` when the administrator API is not configured, `401` when the header is missing, and `403` when it does not match.

Keep data-plane bearer-key authentication separate. Have the Svelte `/admin` UI accept the administrator key, retain it in memory, attach it to management requests, and clear it when the administrator leaves or locks the UI.

## Included Changes

- Introduce `require_admin_auth` as a distinct dependency from `require_auth`.
- Protect key, settings, provider, profile, telemetry, and dashboard management routes with the administrator dependency.
- Use constant-time comparison for the reusable administrator secret.
- Add an administrator-key header to management requests from the Svelte UI.
- Keep client bearer-key authentication on LLM-facing routes.
- Avoid a persistent administrator-user table, password reset flow, or external identity provider.

## Evidence

| Evidence | What it establishes |
|---|---|
| `ccb32569:server/api/auth.py` | `PRIVACY_ROUTER_ADMIN_KEY`, `X-Privacy-Router-Admin-Key`, status semantics, and constant-time comparison. |
| `ccb32569:server/api/routes/keys.py` | Management-key dependency on client-key operations. |
| `ccb32569:server/api/routes/proxy.py` | Management-key dependency on settings, providers, profiles, telemetry, and dashboard data. |
| `ccb32569:web/src/lib/api/client.ts` | In-memory administrator key and automatic management header. |
| `ccb32569:web/src/routes/admin/+page.svelte` | Browser administrator unlock and clear flow. |

## Consequences

### Positive

- Management operations no longer share authority with ordinary client requests.
- The first client key can be created without already possessing a client key.
- No persistent administrator account or identity-provider integration is required.
- The raw administrator key is not stored in SQLite.
- Constant-time comparison avoids content-dependent equality checks.

### Negative

- The browser handles a reusable deployment secret directly.
- Every management request repeats that secret in a JavaScript-created header.
- The server cannot independently revoke one browser session without rotating the deployment-wide key.
- There is no session lifetime, browser-specific principal, CSRF token, or login attempt window.
- Deployment security depends on transport encryption and careful secret distribution.

## Alternatives Considered

### Leave management routes public

Rejected because any process that could reach the service could alter keys and configuration. The historical rationale for this option is preserved in [`history/2026-06-public-management-proposal.md`](history/2026-06-public-management-proposal.md), together with the evidence correction showing it was not implemented as claimed.

### Reuse client bearer keys

Rejected because client keys are the resources being managed and should not automatically grant management authority.

### Add persistent administrator accounts or external SSO

Deferred because the local and single-operator deployment model did not justify account storage, recovery, role management, or identity-provider integration.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation at the time |
|---|---:|---:|---|
| Reusable key exposed through browser compromise or operator handling | Medium | High | Keep it in memory, do not persist it in SQLite, and use TLS on untrusted networks. |
| Public bind exposes management login attempts | Medium | High | Require a high-entropy key and authenticated ingress. |
| Deployment starts without administrator configuration | Medium | Medium | Return `503` from management dependencies. |
| One secret controls every browser and cannot be selectively revoked | Medium | Medium | Rotate `PRIVACY_ROUTER_ADMIN_KEY` and restart. |
| No browser-session expiry or CSRF binding | Medium | High | Superseded by ADR-003. |

## History

- **2026-07-15:** Superseding date claimed by the earlier ADR; independent decision evidence was not found.
- **2026-07-16:** Dedicated administrator-key code and working Svelte administrator UI appear together in `ccb32569`.
- **2026-07-21–22:** ADR-003 replaces the reusable header with a short-lived browser session and CSRF token.
- **2026-07-22:** This ADR is first written during the evidence-grounded timeline reconstruction.
