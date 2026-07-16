# Cost Estimate

Provider cost is configuration-dependent. This page describes the currently active default profile; it is a planning aid, not a bill.

## Current Runtime Roles

| Runtime role | Current model | Location | Marginal provider cost |
|---|---|---|---:|
| Decision Model | EXAONE 4.0 1.2B | Local | $0 |
| Local Model | Gemma 4 26B | Local | $0 |
| External Model | OpenRouter Gemma 4 26B | Cloud | $0.06 / 1M tokens |
| Judge / Router | Deterministic Python | Local | $0 |

The local rows have no external provider charge. Hardware, electricity, and operations costs are not included.

## Planning Calculation

Only requests routed to the External Model incur the configured provider rate:

```text
external model cost =
  external billable tokens / 1,000,000 × $0.06
```

For a planning workload of 50 requests/day, 500 combined billable tokens/request, 30 days, and every request routed externally, the estimated provider charge is **$0.045/month**.

Actual charges depend on the external-route ratio and the prompt plus response tokens reported by the provider. Essential-sensitive requests use the Local Model; non-sensitive and validated masked requests use the External Model.

## Cost Controls

1. **Select the external model deliberately:** Change the active profile only after evaluating privacy detection and generation quality.
2. **Keep local routing available:** Essential-sensitive prompts avoid an external provider call, while local infrastructure costs remain separate.
3. **Measure actual token usage:** Reconcile provider billing with the external routes before making cost claims.
4. **Keep prompts concise:** Fewer billed tokens reduce external-model charges when output requirements stay unchanged.

## Comparison Scope

Subscription products and request-priced APIs have different billing units and included services. This project does not claim a directly comparable monthly price for other providers.
