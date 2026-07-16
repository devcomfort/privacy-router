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
| **Management API exposure** | Unauthorized callers change keys or runtime settings | Require a separate `X-Privacy-Router-Admin-Key` secret for every management route; fail closed when it is unset |

## Encryption

- **At rest:** Fernet authenticated encryption (AES-128-CBC + HMAC-SHA256)
  - Extraction cache: extracted records and labeled conversation context
  - Masking records: original `span` values
  - Stored OpenResponses resources: full `output_json`
  - Provider API keys: `provider.encrypted_api_key`
  - Master key: `PRIVACY_ROUTER_MASTER_KEY`, then legacy `MASKING_ENCRYPTION_KEY`; development auto-generation is process-local
- **In transit:** TLS for all external API calls
- **Masking:** a request-scoped random token (`CATEGORY#random8`) identifies each placeholder. A separate keyed HMAC fingerprint supports equality checks without placing a value-derived hash in the token.

## API Key Storage

| Key Type | Storage | Format | Purpose |
|----------|---------|--------|---------|
| Client API keys | `api_keys.key_hash` | SHA-256 hash | Authenticate incoming requests |
| Provider API keys | `provider.encrypted_api_key` | Fernet ciphertext | Authenticate outbound LLM calls |
| Management admin key | `PRIVACY_ROUTER_ADMIN_KEY` environment variable | Raw shared secret | Authenticate management requests |

**Client keys** are created through the admin-authenticated `POST /api/v1/keys` endpoint and shown once. Only the SHA-256 hash is stored.

**Provider keys** are stored encrypted via Fernet. The key resolution chain is:
1. `provider.encrypted_api_key` (DB, if set)
2. `env[api_key_env]` (environment variable, e.g. `OPENROUTER_API_KEY`)
3. `OPENROUTER_API_KEY` (fallback)

## Data Retention

| Data | Storage | Retention |
|------|---------|-----------|
| Active request text | Process memory | Request lifetime |
| Extraction and labeled conversation context | Database (encrypted) | 24 hours after last cache update |
| Placeholder mappings and original spans | Database (span encrypted) | 24 hours after session creation |
| Stored OpenResponses resources (`store=true`) | Database (encrypted) | 24 hours after creation |
| Usage metadata | Database, without prompt/response text or input fingerprints | Until administratively deleted |
| Provider API keys | Database (encrypted) | Until manually deleted |

Expired rows become unreadable immediately. Startup cleanup and an hourly retention worker physically delete expired extraction-cache rows, masking sessions and records, and stored responses. Encryption protects database contents, but not a host or master-key compromise.

## Authentication and Ownership

- Client API keys start with `pr-`, are shown once, and are stored only as SHA-256 hashes.
- Every management request requires `X-Privacy-Router-Admin-Key` to match `PRIVACY_ROUTER_ADMIN_KEY`; missing configuration returns `503`, a missing request header returns `401`, and an incorrect key returns `403`.
- A validated client key's stable database ID is the owner namespace for stored responses and masking sessions.
- Response retrieval, response chaining, masking metadata, and hydration require an exact owner match.
- Ownerless MCP masking sessions are a separate namespace and cannot load REST-owned contracts.
- Provider key management uses the admin-authenticated `POST/DELETE /api/providers/{id}/key` endpoints.

## Residual Risk and Trust Boundaries

- A host-process or master-key compromise can decrypt protected database values.
- `value_hash` permits equality correlation inside the database for the same master key, although placeholders remain random and unlinkable.
- The management credential is a static environment secret. If it is disclosed, rotate `PRIVACY_ROUTER_ADMIN_KEY`, restart the server, and use TLS or an authenticated ingress on untrusted networks.
- Usage metadata has no automatic TTL; operators must define deletion policy for it.
- Output-inspection failure logs are metadata-only: request ID, route, attempt count, reason, and retryability. Raw argument JSON, decoded values, and extracted spans are never attached.
- Sensitive tool-argument release applies to every function call in that response; there is no per-tool allowlist. Enable it only when all callable tools are trusted. Every local tool call is still inspected. Opt-in releases both hydrated input-derived values and sensitive values newly generated by the local model. Without opt-in, sensitive string values are replaced with `SENSITIVE_DATA#<8 hex>` placeholders before either streaming or non-streaming delivery.

## Related Documents

- [API Keys](/docs/api-keys) — client and provider key management
- [Detection](/docs/detection) — how sensitive data is detected
- [Architecture](/docs/architecture) — system architecture
