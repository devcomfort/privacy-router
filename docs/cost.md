# Cost Estimate

## Monthly Cost Breakdown

| Component | Usage | Unit Cost | Monthly |
|-----------|-------|----------|--------:|
| Extractor (Ministral 3B) | 50 req/day × 500 tokens | $0.10/1M tokens | $0.075 |
| Judge (rule-based) | 50 req/day | $0 (no LLM) | $0 |
| Local model (optional) | Sensitive queries only | $0 (self-hosted) | $0 |
| **Total** | | | **$0.075** |

## Two-Tier Routing

The key cost optimization is **sensitivity-based routing**:

```
Non-sensitive queries (33%) → Cloud SLM ($0.10/1M)
Sensitive queries (67%)     → Local LLM ($0) or masked cloud
```

Unlike complexity-based routers that send difficult queries to expensive models, Privacy Router routes by **information sensitivity**. Non-sensitive queries get full cloud quality at SLM prices.

## Comparison

| Solution | Monthly Cost | Notes |
|----------|------------:|-------|
| ChatGPT Plus | $20.00 | Fixed subscription, US-centric PII |
| Gemini Advanced | $20.00 | Fixed subscription |
| Azure AI Content Safety | $50.00+ | Per-1K-records pricing |
| **Privacy Router** | **$0.075** | Per-request, rule-based Judge |

## Cost Optimization Strategies

1. **Caching:** Repeated patterns (common PII formats) cached by hash
2. **Batch processing:** Multiple prompts processed in single Extractor call
3. **Model compression:** 3B → 1.5B possible with minimal accuracy loss
4. **Prompt optimization:** Shorter prompts = fewer tokens = lower cost
