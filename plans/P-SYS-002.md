# P-SYS-002: Per-Model vLLM Parameter Sweep

## Goal
모델별 최적 max_num_seqs 탐색 (gpu=0.87, max_model_len=4096 고정)

## Model
- E2B, E4B, EXAONE (3 models × 4 seqs = 12 configs)

## Variables
| Variable | Values | Type |
|---|---|---|
| Model | E2B, E4B, EXAONE | Independent |
| max_num_seqs | 16, 24, 32, 48, 64 (model-dependent) | Independent |

## Constants
| Constant | Value |
|---|---|
| gpu_utilization | 0.87 |
| max_model_len | 4096 |
| Prompt | fewshot_v3 |
| Dataset | benchmark_v2.json (N=20 per config) |
| MRv2 | on |
| Prefix caching | on |

## Method
- Per-config: start vLLM → benchmark 20 cases → measure
- Find sweet spot: highest seqs before throughput decline

## Hypothesis
- Higher seqs = higher throughput (up to a point)
- KV cache contention causes decline at high seqs

## Status: COMPLETE

## Results
→ [observations/O-SYS-002.md](../observations/O-SYS-002.md)
→ [insights/I-004.md](../insights/I-004.md)
