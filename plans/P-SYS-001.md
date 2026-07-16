# P-SYS-001: vLLM Acceleration Techniques

## Goal
vLLM 서버 throughput 극대화 — ngram speculative, MRv2, prefix-caching, concurrency

## Model
- E4B (primary), E2B, EXAONE

## Variables
| Variable | Values | Type |
|---|---|---|
| Speculative decoding | none, ngram | Independent |
| MRv2 | off, on | Independent |
| Prefix caching | off, on | Independent |
| Concurrency | 1, 2, 4, 8, 12, 16, 24, 32 | Independent |

## Constants
| Constant | Value |
|---|---|
| Prompt | fewshot_v3 |
| Dataset | benchmark_v2.json (120 cases) |
| gpu_utilization | 0.75 |
| max_model_len | 4096 |

## Method
- Sequential benchmark per config
- Measure: accuracy, throughput (req/s), latency (p50/p95)
- Compatibility matrix between techniques

## Hypothesis
- MRv2 + ngram may be incompatible
- Concurrency scaling has diminishing returns

## Status: COMPLETE

## Results
→ [observations/O-SYS-001.md](../observations/O-SYS-001.md)
→ [insights/I-003.md](../insights/I-003.md)
