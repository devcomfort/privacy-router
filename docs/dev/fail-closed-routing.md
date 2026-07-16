# Fail-Closed Routing

This document defines the execution boundary used by the OpenAI-compatible endpoints:

- `POST /v1/chat/completions`
- `POST /v1/responses`

It applies after the privacy pipeline has produced a policy action. It does not define sensitivity classification or model configuration.

## Boundary Contract

Each request has one privacy decision and one selected execution route.

```text
prompt
  -> Extractor
  -> Judge
  -> Router
  -> selected route: local_api | external_api
  -> adapter call
  -> hydration, when an external masked request is used
```

The selected route is immutable for the lifetime of the request:

- `local_api` receives the original prompt and is never replaced by an external call.
- `external_api` receives a masked prompt whenever the policy requires masking.
- There is no local-to-external or external-to-local fallback.
- The API routes do not invoke a second Extractor. The `PipelineResult.records` produced by the original pipeline are the records passed to `Masker`.

This preserves the distinction in [Data Flow](data-flow.md): query-level aggregation selects policy, while exact `ExtractionRecord` spans remain the source of truth for masking and hydration.

## Fixed-Route Execution

`agents/router/execution.py` owns adapter retry behavior. Endpoint handlers prepare the selected model, API base, and payload once; the executor only re-invokes that same prepared call.

| Rule | Contract |
|---|---|
| Maximum attempts | Three total calls: the original call plus at most two retries. |
| Backoff | One second before attempt two; two seconds before attempt three. |
| Retriable failures | `TimeoutError`, LiteLLM timeout errors, connection errors, and LiteLLM service-unavailable errors. |
| Non-retriable failures | Invalid requests, invalid model responses, structured-output parse failures, schema failures, route validation failures, masking failures, hydration failures, and all other adapter failures. |
| Route changes | Forbidden. A retry uses the same adapter, model, API base, messages, and tool arguments. |
| Privacy work | Never repeated by retry logic. Extractor, Judge, Router, masking, and hydration are outside the retry loop. |

Transport errors are represented internally as `PrivacyRouteFailure`. The exception stores only the selected route, a stable reason code, retryability, attempt count, and HTTP status. The caught provider exception is neither serialized nor attached to logs.

## Fail-Closed Stages

The request stops rather than exposing an unsafe response in each of these cases:

| Stage | Failure outcome | HTTP status for JSON responses |
|---|---|---|
| Extractor / structured parse | `extraction_failed` | 503 |
| Invalid route invariant | `route_invariant_failed` | 409 |
| Adapter transport exhaustion | `timeout`, `connection`, or `service_unavailable` | 503 |
| Non-transient adapter error | `adapter_error` | 502 |
| Masking contract failure | `masking_failed` | 502 |
| Hydration failure | `hydration_failed` | 502 |

A hydration failure never returns a successful completion body. It also never emits a synthetic partial final response.

## Beta Malformed-Placeholder Repair

Set `PRIVACY_ROUTER_BETA_PLACEHOLDER_REPAIR=true` to enable one narrowly scoped recovery path before a hydration failure is returned.

The recovery model receives only the masked request, masked model output, malformed token, and registered contract placeholders. A candidate is accepted only when it exactly equals one registered placeholder. Ambiguous or unresolved mappings return `null`, after which the normal `hydration_failed` path remains in force. The repair path never receives or reconstructs original sensitive values.

The same boundary applies to normal text, Chat Completions tool-call arguments, Responses function-call arguments, and buffered streaming output. No text or tool arguments containing an unvalidated placeholder are delivered to the client.

## Client-Safe Errors

Non-streaming failures use the normal endpoint envelope and contain stable fields only:

```json
{
  "error": {
    "code": "privacy_route_unavailable",
    "reason": "timeout",
    "message": "A privacy-preserving processing route did not respond after three attempts.",
    "retryable": true,
    "attempts": 3,
    "request_id": "chatcmpl-..."
  }
}
```

The production message is localized. The example shows structure only. Client payloads and server logs exclude raw prompts, extracted spans, masking placeholders, decrypted values, provider URLs, API keys, and caught exception text.

## Streaming Contract

Streaming uses the same selected route and prepared payload.

1. The stream may retry only while opening the upstream iterator, before the first client-visible output chunk.
2. Once any output chunk is emitted, the stream cannot be retried because a replay could duplicate or contradict client-visible content.
3. A late adapter or hydration failure emits one safe failure event and `data: [DONE]`.
4. The failure path does not emit `response.completed`, `response.output_text.done`, or a final chat `finish_reason` chunk.

`/v1/chat/completions` emits the safe error as an OpenAI-style SSE `data` payload. `/v1/responses` emits it in a `response.failed` event. Both use the same public error fields.

## Verification

`server/tests/test_fail_closed_retry.py` exercises both API surfaces with mock adapters. It verifies local and external selected routes, fixed-payload retries, non-retriable failures, masking and hydration failures, safe JSON errors, and pre-first-chunk versus post-first-chunk streaming behavior.

`eval/scripts/placeholder_repair_eval.py` evaluates the opt-in repair model with masked-only cases:

```bash
python eval/scripts/placeholder_repair_eval.py \
  --trials 5 \
  --output docs/experiments/results/placeholder-repair-gemma4-26b-20260712.json
```

The 2026-07-12 Gemma 4 26B run produced 50/50 exact decisions: 100% registered-placeholder mapping accuracy and 100% ambiguous-`null` accuracy. Mean, median, and nearest-rank p95 latency were 1.71 s, 0.63 s, and 8.08 s respectively. The checked-in result contains masked placeholders only.

## Related Documents

- [Data Flow](data-flow.md) — evidence records and query-level decision summaries.
- [Architecture](architecture.md) — service components and API boundaries.
- [Security](../user/security.md) — threat model and secret-handling constraints.
