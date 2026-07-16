# Fail-Closed Route Retry and Error Contract Design

## Status

Approved design — 12 July 2026.

## Problem

Privacy Router already selects a route, but its failure handling does not consistently preserve that decision:

- `server/api/routes/proxy.py` catches a local-model failure and changes the policy to a masked external route.
- `server/api/routes/proxy.py` and `server/api/routes/responses.py` silently ignore hydration errors in some paths.
- Backend errors can expose `str(exception)` directly to clients or streams.
- The project has no acceptance contract that proves the selected route remains unchanged during retries and failure.

A route chosen for local processing is a trust-boundary decision. A local failure must not create any external call, masked or raw.

## Goal

Make one routing decision immutable for a request. Retry only transient adapter failures against that same decided route, then return a safe, explainable error. Every fail-closed branch must produce a raw-free structured server log and a stable client error.

## Non-Goals

- Do not introduce a fallback from local to external or external to local.
- Do not retry extraction, structured parsing, schema validation, summary/action validation, masking, or hydration.
- Do not re-run extraction, aggregation, policy selection, masking, or payload preparation during an adapter retry.
- Do not expose original prompts, extracted spans, placeholder restoration values, API keys, provider URLs, or raw exception strings through API responses, streams, or logs.
- Do not add a database table, queue, background worker, or configurable retry policy in this change.

## Route Is an Immutable Decision

The route is chosen once from the query summary and policy action. Its endpoint and prepared payload remain fixed for every later attempt.

```text
summary + action
    → validate route invariant once
    → choose local_api or external_api once
    → prepare the allowed payload once
    → attempt the same endpoint at most three times
    → success or safe failure
```

For a local route:

```text
local attempt 1
    → transient failure
local attempt 2
    → transient failure
local attempt 3
    → safe 503 error

external adapter calls = 0
```

For a masking-required external route, all attempts use the same already-masked payload and the same masking contract. The original query is never re-forwarded as a fallback.

## Retry Policy

`max_attempts = 3` means one initial adapter call plus at most two retries.

Only these transport-level exceptions are retryable:

- `TimeoutError`
- `ConnectionError`
- `litellm.Timeout`
- `litellm.CompletionTimeout`
- `litellm.APIConnectionError`
- `litellm.ServiceUnavailableError`

All other adapter failures stop after the first call with `reason=adapter_error` and `retryable=false`. `RateLimitError`, invalid requests, invalid model responses, parsing failures, privacy invariant failures, masking failures, and hydration failures are not retried.

The retry delays are 1 second before attempt two and 2 seconds before attempt three. This gives a model backend time to recover from a short overload or connection disruption without introducing another route decision. Tests inject a no-op sleeper and assert calls rather than waiting.

For streaming, retries are permitted only before the first output chunk is emitted. Once any chunk has crossed the client boundary, the stream emits one safe `response.failed` event and stops; it does not retry because a new stream could duplicate output.

## Execution Boundary

Add one small internal route-execution function shared by `/v1/chat/completions` and `/v1/responses`. It receives:

```text
RouteResult             the already selected endpoint and masking requirement
prepared payload        original local payload or already-masked external payload
adapter invocation      the exact backend call to retry
request_id              correlation identifier already created by the endpoint
```

It does not inspect raw text, infer sensitivity, select a route, call the Extractor, call the Judge, mask, hydrate, or change models. It only retries the supplied adapter call under the fixed-route policy above.

The Router remains the final policy/invariant guard. The shared executor is only the transport reliability boundary. The legacy proxy local-failure-to-external reassignment is deleted.

## Failure Contract

### Server logs

Each retry emits a structured warning:

```text
event=privacy_route_retry
request_id=<response-or-chat-id>
route=local_api|external_api|unresolved
attempt=2|3
max_attempts=3
reason=timeout|connection|service_unavailable
```

The final failure emits a structured error:

```text
event=privacy_route_failed
request_id=<response-or-chat-id>
route=local_api|external_api|unresolved
attempts=1|2|3
reason=<safe reason code>
retryable=true|false
```

The log message is the fixed event name. The log record contains only the listed safe fields. It does not attach `exc_info`, `str(exception)`, raw payloads, spans, placeholder maps, restoration values, credentials, or provider URLs.

### Client errors

A retry-exhausted adapter failure returns HTTP 503 with this stable shape:

```json
{
  "error": {
    "code": "privacy_route_unavailable",
    "reason": "timeout",
    "message": "선택된 개인정보 보호 처리 경로가 3회 시도 후 응답하지 않았습니다. 요청은 다른 처리 경로로 전환되지 않았습니다.",
    "retryable": true,
    "attempts": 3,
    "request_id": "req_..."
  }
}
```

A non-retryable failure returns the same shape with `retryable: false`, `attempts: 1`, and one of these safe reason codes:

| Failure | HTTP | `code` | `reason` |
|---|---:|---|---|
| Non-transient adapter failure | 502 | `privacy_route_unavailable` | `adapter_error` |
| Extractor, parse, or schema failure | 503 | `privacy_analysis_failed` | `extraction_failed` |
| Route-summary/action contradiction | 409 | `privacy_route_rejected` | `route_invariant_failed` |
| Invalid mask contract or masking failure | 502 | `privacy_contract_failed` | `masking_failed` |
| Hydration failure | 502 | `privacy_contract_failed` | `hydration_failed` |

Streaming uses the same safe fields inside its final `response.failed` event, then sends `[DONE]`. It never sends `str(exception)`.

## Test Contract

The fail-closed acceptance suite uses fake adapters that count calls and raise controlled errors whose message contains a harmless test sentinel. It verifies:

1. A transient local failure calls the local adapter exactly three times and the external adapter zero times.
2. A transient external failure calls the originally selected external adapter exactly three times and the local adapter zero times.
3. Every retry uses the exact same prepared payload; retries do not re-extract, re-summarize, re-judge, or re-mask.
4. A local route never falls through to external after exhaustion.
5. Extractor, parsing, summary/action, masking, and hydration failures make zero retry calls and zero prohibited adapter calls.
6. Hydration failure never returns an unhydrated or partially hydrated success response.
7. Each retry and final failure creates a `caplog` record with route, attempt, reason, and request ID.
8. The API and streaming errors expose safe code, reason, retryability, attempts, and request ID, but not the sentinel or a raw exception string.
9. Streaming may retry only before the first emitted output chunk; after output begins it emits exactly one safe failure event and does not retry.

## Implementation Order

1. Add fail-closed acceptance tests, including `caplog` and response/stream payload assertions.
2. Add the fixed-route retry executor and its direct unit tests.
3. Route both API endpoints through that executor.
4. Delete the local-to-external fallback and debug `print` statements.
5. Replace swallowed hydration failures with typed fail-fast errors.
6. Run focused unit, API, and streaming tests before the wider Query Aggregation P0 work.

## Definition of Done

A selected route is never changed after policy selection. Transient backend failures may produce at most three calls to that selected adapter and zero calls to every other adapter. All privacy-processing and hydration failures stop before unsafe forwarding. Logs and client errors explain the safe reason without exposing protected content or backend internals.
