# ADR-002: Public Admin Endpoints for Standalone Admin UI

## Date

2026-06-16

## Status

Accepted

## Context

The project ships a browser-based admin dashboard at `web/admin.html`, served from `/admin` (`server/api/routes/proxy.py`). This dashboard is a standalone single-page application that communicates directly with the backend using `fetch()`:

- `GET /api/v1/keys` to list API keys
- `POST /api/v1/keys` to create a new key
- `PATCH /api/v1/keys/{key_id}` to toggle key state
- `DELETE /api/v1/keys/{key_id}` to remove a key
- `GET /api/v1/providers` to populate the provider selector
- `GET /api/settings` and `POST /api/settings` to read and update agent/model configuration

None of these requests include an `Authorization` header or any session cookie. The backend is also configured with permissive CORS (`allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]` in `server/api/main.py`), so the dashboard can be opened from any origin.

Because the admin UI is intended to work out of the box without login credentials, SSO, or a pre-provisioned API key, the endpoints it consumes must be publicly reachable.

## Decision

Keep the admin UI endpoints publicly accessible (no `require_auth` dependency) so that the standalone admin dashboard can manage keys, providers, and settings without an authentication flow.

Rationale:

1. **Standalone UI requirement**: The admin dashboard is distributed with the server and must function immediately after `uvicorn server.api.main:app` starts, without additional setup such as creating an admin user.
2. **No frontend auth mechanism**: `web/admin.html` has no login form, token store, or session handling. Adding auth to the backend alone would break the UI.
3. **CORS already permits arbitrary origins**: Even if the endpoints required a token, a browser-based attacker on another origin could still attempt requests; a proper auth design would need to address CORS and token storage together.
4. **Scope control**: Re-architecting the admin UI to include login, token refresh, and role-based access is deferred to a future production-hardening phase.

## Consequences

Positive:

- The admin dashboard is fully functional on first run.
- No extra dependency on an identity provider, cookie store, or admin credential database.
- Simple mental model: the API has a public "management plane" and a key-protected "data plane."

Negative:

- The entire admin functionality is exposed to any client that can reach the server, not just the intended dashboard.
- Cross-site request forgery (CSRF) becomes relevant: a malicious webpage visited by a user on the same machine could trigger state-changing requests to `localhost` if the user has the admin UI open or recently used it.
- Rate limiting and abuse detection for admin actions are absent.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| CSRF or cross-origin drive-by requests to `POST /api/settings` or `DELETE /api/v1/keys/{id}` from a malicious site | Medium | High | Bind the server to `127.0.0.1`; do not browse arbitrary websites while the admin server is running; eventually add SameSite cookies or a CSRF token when an auth layer is introduced. |
| Unauthorized provider/key modification if the server is reachable from the LAN/WAN | High if exposed | High | Firewall/administrative control; reverse proxy with authentication; document that public exposure requires additional hardening. |
| Inability to distinguish legitimate admin-UI actions from attacker actions in logs | Medium | Medium | Add client IP and user-agent logging; consider an admin action audit log. |
| Future auth migration will require coordinated backend + frontend changes | Medium | Low | Keep the auth boundary explicit (`require_auth` dependency) so protected routes already use the right abstraction; admin routes can be migrated incrementally. |
