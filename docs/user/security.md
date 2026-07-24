# Privacy and Security

## Data Flow

```
User Prompt → Extractor (on-device) → Judge (on-device) → Router
                                                    ↓
                                        ┌───────────┼───────────┐
                                        ↓           ↓           ↓
                                   External API  Local API    Block
                                   (masked)      (full)
                                        ↓
                                   Hydration (on-device)
```

**Key invariant:** The Extractor runs entirely on-device. Sensitive data is never sent to an external service for classification.

## Threat Model

| Threat | Risk | Mitigation |
|--------|------|-----------|
| **PII in prompts** | Agent sends user's RRN, phone, email to cloud | Extractor detects and masks before forwarding |
| **Business secrets** | Internal decisions, strategies leak via prompts | Contextual reasoning detects non-keyword secrets |
| **Research secrets** | Unpublished ideas, experimental data exposed | Socratic categories classify research-sensitive content |
| **Credential exposure** | API keys, passwords in prompts | Credential keyword detection with high confidence |
| **Response leakage** | LLM response contains masked placeholders | Hydration restores original values before user sees response |
| **Tool-call exfiltration** | A model or prompt injection places sensitive values in executable function arguments | Keep input-derived placeholders and inspect local-model argument output before delivery; mask detected plaintext by default and permit it only with explicit `privacy_router.allow_sensitive_tool_arguments: true` consent |
| **Database snapshot exposure** | Ciphertext and metadata are copied | Fernet encryption, keyed HMAC fingerprints, and 24-hour raw-data TTL |
| **Cross-owner resource access** | One client retrieves another client's response or masking contract | Exact API-key-ID ownership checks on stored resources |
| **Management API exposure** | Unauthorized callers change keys or runtime settings | Exchange a dedicated administrator password for a short-lived signed session; require CSRF tokens on state-changing requests and fail closed when credentials or signing keys are unset |

## Encryption

- **At rest:** Fernet authenticated encryption (AES-128-CBC + HMAC-SHA256)
  - Extraction cache: extracted records and labeled conversation context
  - Masking records: original `span` values
  - Stored OpenResponses resources: full `output_json`
  - Master key: `PRIVACY_ROUTER_MASTER_KEY`, then legacy `MASKING_ENCRYPTION_KEY`; only `dev` may create a process-local key
- **In transit:** TLS for all external API calls
- **Masking:** a request-scoped random token (`CATEGORY#random8`) identifies each placeholder. A separate keyed HMAC fingerprint supports equality checks without placing a value-derived hash in the token.

## Credential Handling

| Credential | Storage | Format | Purpose |
|---|---|---|---|
| Client API keys | `api_keys.key_hash` | SHA-256 hash | Authenticate incoming requests |
| Provider API keys | Server environment variables only | Raw provider secret, never returned | Authenticate outbound LLM calls |
| Administrator password | `PRIVACY_ROUTER_ADMIN_PASSWORD` environment variable only | Raw deployment secret, never returned | Create management sessions |
| Management session | `HttpOnly`, `SameSite=Strict`, `/api` cookie | Purpose-derived Fernet token containing `admin:SHA-256(CSRF)`; Fernet timestamp enforces expiry | Authenticate management requests |

**Client keys** are created through an authenticated management session and shown once. Only the SHA-256 hash is stored.

**Provider keys** are resolved only from the environment variable named by `provider.api_key_env`. The built-in OpenRouter provider uses `OPENROUTER_API_KEY`. The database and management API retain only that environment variable name and availability state.

**Administrator sessions** expire after 30 minutes. State-changing management requests must carry the matching `X-Privacy-Router-CSRF-Token`; password exchange and CSRF checks use constant-time comparison.

## Data Retention

| Data | Storage | Retention |
|------|---------|-----------|
| Active request text | Process memory | Request lifetime |
| Extraction and labeled conversation context | Database (encrypted) | 24 hours after last cache update |
| Placeholder mappings and original spans | Database (span encrypted) | 24 hours after session creation |
| Stored OpenResponses resources (`store=true`) | Database (encrypted) | 24 hours after creation |
| Usage metadata | Database, without prompt/response text or input fingerprints | Until administratively deleted |

Expired rows become unreadable immediately. Startup cleanup and an hourly retention worker physically delete expired extraction-cache rows, masking sessions and records, and stored responses. Encryption protects database contents, but not a host or master-key compromise.

## Authentication and Ownership

- Client API keys start with `pr-`, are shown once, and are stored only as SHA-256 hashes.
- Management login requires `PRIVACY_ROUTER_ADMIN_PASSWORD` and a persistent master key. Session cookies are `Secure` on HTTPS requests; deployments must terminate TLS before exposing management routes.
- Every management `POST`, `PATCH`, `PUT`, and `DELETE` request requires the session's CSRF token.
- `privacy-router dev` may issue a separate loopback-only demo session for browser chat. It cannot select external models and does not authorize management routes.
- A validated client key's stable database ID is the owner namespace for stored responses and masking sessions.
- Response retrieval, response chaining, masking metadata, and hydration require an exact owner match.
- Ownerless MCP masking sessions are a separate namespace and cannot load REST-owned contracts.
- Provider credential values are environment-only, read-only through the UI, and never included in API responses.

## Residual Risk and Trust Boundaries

- A host-process or master-key compromise can decrypt protected database values.
- `value_hash` permits equality correlation inside the database for the same master key, although placeholders remain random and unlinkable.
- If the administrator password is disclosed, rotating `PRIVACY_ROUTER_ADMIN_PASSWORD` and restarting prevents new logins with the old value, but existing sessions remain valid for up to 30 minutes. Immediate global session invalidation requires master-key rotation, which also makes previously encrypted records unreadable.
- Usage metadata has no automatic TTL; operators must define deletion policy for it.
- Output-inspection failure logs are metadata-only: request ID, route, attempt count, reason, and retryability. Raw argument JSON, decoded values, and extracted spans are never attached.
- Sensitive tool-argument release applies to every function call in that response; there is no per-tool allowlist. Enable it only when all callable tools are trusted. Every local tool call is still inspected. Opt-in releases both hydrated input-derived values and sensitive values newly generated by the local model. Without opt-in, sensitive string values are replaced with `SENSITIVE_DATA#<8 hex>` placeholders before either streaming or non-streaming delivery.

## Related Documents

- [Data types and sensitivity classification](../dev/data-flow.md) — what data the system handles
- [Storage and encryption details](../dev/storage.md) — where and how data is stored
- [API key management](api-keys.md) — client and provider key management
- [Architecture decision timeline](../dev/adr/README.md) — implemented change packages, dates, lifecycle links, and corrected historical notes
- [ADR-001: SQLite by default](../dev/adr/ADR-001-sqlite-default-database.md) — storage decision reaffirmed by the current hardening package
- [ADR-003: Browser sessions and runtime startup](../dev/adr/ADR-003-browser-sessions-and-runtime-startup.md) — current management, credential, and deployment boundaries
