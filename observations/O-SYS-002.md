# O-SYS-002: Per-Model vLLM Parameter Sweep Results

## Raw Data
- `experiments/results/full_param_sweep.json`

## Config
- gpu_utilization: 0.87
- max_model_len: 4096
- MRv2 + prefix-caching: on
- N=20 cases per config

## E2B Results (baseline acc: 65.0%)
| max_num_seqs | Throughput | Accuracy | Latency | Status |
|---|---|---|---|---|
| 16 | 3.19/s | 65.0% | 2.10s | baseline |
| **32** | **4.38/s** | **65.0%** | **2.53s** | **OPTIMAL** |
| 48 | 3.63/s | 65.0% | 3.46s | ↓ decline |
| 64 | 3.69/s | 65.0% | 3.51s | plateau |

## E4B Results (baseline acc: 60.0%)
| max_num_seqs | Throughput | Accuracy | Latency | Status |
|---|---|---|---|---|
| 16 | 2.27/s | 60.0% | 4.62s | baseline |
| **24** | **2.92/s** | **60.0%** | **4.68s** | **OPTIMAL** |
| 32 | 2.81/s | 60.0% | 4.90s | ↓ decline |
| 48 | 2.43/s | 60.0% | 6.09s | ↓↓ decline |

## EXAONE Results (instructor: 0% accuracy)
| max_num_seqs | Throughput | Accuracy | Latency | Status |
|---|---|---|---|---|
| 16 | 3.33/s | 0.0% | 2.64s | — |
| **32** | **4.94/s** | **0.0%** | **2.74s** | best throughput |
| 48 | 4.92/s | 0.0% | 2.71s | plateau |
| 64 | 4.84/s | 0.0% | 2.77s | ↓ decline |

## Optimal Configs (Solo Profile)
| Model | gpu | len | seqs | Throughput | Accuracy |
|---|---|---|---|---|---|
| E2B | 0.87 | 4096 | 32 | 4.38/s | 65.0% |
| E4B | 0.87 | 4096 | 24 | 2.92/s | 60.0% |
| EXAONE | 0.87 | 4096 | 32 | 4.94/s | 0.0% |
