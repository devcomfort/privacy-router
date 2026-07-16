# O-EXA-001: EXAONE vLLM Parameter Sweep

## Raw Data
- Included in `experiments/results/full_param_sweep.json` (EXAONE section)

## Results (gpu=0.87, max_model_len=4096, N=20)
| max_num_seqs | Throughput | Accuracy | Latency | Total |
|---|---|---|---|---|
| 16 | 3.33/s | 0.0% | 2.64s | 6.0s |
| **32** | **4.94/s** | **0.0%** | **2.74s** | **4.0s** |
| 48 | 4.92/s | 0.0% | 2.71s | 4.1s |
| 64 | 4.84/s | 0.0% | 2.77s | 4.1s |

## Note
- **0% accuracy across all configs** — instructor structured output incompatible with EXAONE
- Throughput measurement valid: 4.94/s at seqs=32
- Sequential (non-concurrent) accuracy: 40.8% — instructor parsing issue at scale
