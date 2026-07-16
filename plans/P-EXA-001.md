# P-EXA-001: EXAONE vLLM Parameter Sweep

## Goal
EXAONE 모델의 최적 max_num_seqs 탐색

## Model
- EXAONE (LGAI-EXAONE/EXAONE-4.0-1.2B, 2.39 GiB)

## Variables
| Variable | Values |
|---|---|
| max_num_seqs | 16, 32, 48, 64 |

## Constants
| Constant | Value |
|---|---|
| gpu_utilization | 0.87 |
| max_model_len | 4096 |
| Prompt | fewshot_v3 |
| Dataset | benchmark_v2.json (N=20) |

## Note
- EXAONE + instructor: 0% accuracy (structured output incompatible)
- Throughput measurement only

## Status: COMPLETE

## Results
→ [observations/O-EXA-001.md](../observations/O-EXA-001.md)
