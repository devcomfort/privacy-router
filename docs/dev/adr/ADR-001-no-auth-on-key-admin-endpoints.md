# ADR-001: Management Endpoints Without Authentication (Superseded)

## Date

2026-06-16

## Status

Superseded on 2026-07-15

## Context

The Privacy Router HTTP API is primarily intended to run on the operator's local workstation or inside a trusted local network during development, demo, and small-scale deployments. The project currently has a single authentication primitive: API keys (`server/api/auth.py`) that are verified via a `Bearer` token and a SHA-256 hash stored in the `ApiKey` table. This primitive is used to protect LLM-facing routes such as `/v1/chat/completions`, `/v1/responses`, `/api/v1/classify`, and `/api/v1/generate`.

However, several management endpoints in `server/api/routes/keys.py` and `server/api/routes/proxy.py` do **not** call `Depends(require_auth)`:

- `GET /api/v1/keys`
- `POST /api/v1/keys`
- `POST /api/v1/keys/{key_id}/renew`
- `PATCH /api/v1/keys/{key_id}`
- `DELETE /api/v1/keys/{key_id}`
- `GET /api/settings`
- `POST /api/settings`

There is also a bootstrapping problem: the only way to create the first API key is through the key-management endpoint, but the key-management endpoint itself currently requires no credentials. Requiring authentication for these endpoints would force the project to add a separate admin account system (passwords, sessions, or OAuth) and increase operational complexity for users who just want to run the server locally.

## Decision

Leave the key-management and admin/settings endpoints unauthenticated for the current release.

Rationale:

1. **Local-only/trusted-network deployment model**: The server is not exposed to the public internet in the recommended deployment model. Authentication is therefore treated as a network-layer concern rather than an application-layer requirement for management endpoints.
2. **Avoid account-management cost**: Adding an admin user model, password hashing, session handling, or SSO integration would materially increase code size, test surface, and user onboarding friction.
3. **Bootstrap simplicity**: A new installation must be configurable without first possessing a valid API key. Keeping key creation open solves the chicken-and-egg problem.
4. **Consistent with current admin UI**: `web/admin.html` performs key, provider, and settings operations with plain `fetch()` calls that carry no authorization header. Adding auth to the backend would require a matching frontend authentication flow.

## Consequences

Positive:

- Zero-config onboarding: users can start the server and create the first API key immediately.
- The standalone admin UI works without a login page or session handling.
- Lower maintenance burden: no password reset, account lockout, or session expiry logic.

Negative:

- Any process or user that can reach the management port can list, create, renew, revoke, or delete API keys and change runtime settings.
- A leaked admin URL or accidental public binding of the server exposes the entire key store and configuration.
- Audit logging of administrative actions cannot be attributed to a specific authenticated principal.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Unauthorized key creation/revocation by anyone with network access to the admin port | High in shared networks | High | Run the server bound to `127.0.0.1` only; use a reverse proxy with mTLS or VPN for remote access. |
| Accidental exposure when a user binds the server to `0.0.0.0` on a public interface | Medium | High | Document the security model clearly in README and startup logs; add an explicit `--host` warning in startup scripts. |
| Key material exfiltration through `GET /api/v1/keys` (note: the raw key value is not returned by this endpoint, but metadata such as prefix, status, and usage timestamps is) | Medium | Medium | Avoid exposing the admin port to untrusted clients. |
| Inability to meet compliance/audit requirements that demand authenticated administrative actions | Medium | Medium | Treat this architecture as a development/demo tier; production hardening must add an authentication layer before exposing the API. |

## Superseding Decision (2026-07-15)

Every management endpoint now requires a separate shared secret:

- Server configuration: `PRIVACY_ROUTER_ADMIN_KEY`
- Request header: `X-Privacy-Router-Admin-Key`
- Missing server configuration: fail closed with `503`
- Missing request key: reject with `401`; incorrect request key: reject with `403`
- Comparison: constant-time `hmac.compare_digest`

This applies to client-key, model, provider-key, settings, profile, and dashboard-data management routes. Masking-session retrieval and hydration remain data-plane operations protected by `Authorization: Bearer pr-...` client keys and ownership checks; public metadata such as `/v1/models` remains unchanged.

The independent shared secret solves the bootstrap problem without introducing accounts or persistent browser sessions. The admin UI keeps the secret only in the current browser tab's memory and clears it on sign-out, refresh, or navigation. Operators must still use TLS or authenticated ingress on untrusted networks because disclosure of this static secret grants full management access.
