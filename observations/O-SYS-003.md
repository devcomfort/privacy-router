# O-SYS-003: Full 10-Model Sweep Results

## Raw Data
- `experiments/results/all_models_sweep.json`
- `experiments/results/model_inventory.json`

## Config
- gpu_utilization: 0.87 (environment-dependent safe cap)
- max_model_len: 4096
- MRv2 + prefix-caching: on
- V2 runner: Gemma/EXAONE/Granite; V1 runner: Qwen
- N=20 cases per config

## Results

### Valid Models (errors=0, accuracy>0)
| Model | Disk | seqs | TPS | Accuracy | Latency |
|---|---|---|---|---|---|
| **Granite-8B** | 16.4 GiB | 24 | 0.69/s | **90.0%** | 16.4s |
| **EXAONE-1.2B** | 2.4 GiB | 48 | 4.90/s | **80.0%** | 2.7s |
| E2B | 9.6 GiB | 64 | 4.63/s | 65.0% | 2.3s |
| E4B | 14.9 GiB | 32 | 2.82/s | 60.0% | 4.9s |
| Gemma-26B | 48.1 GiB | 16 | 1.23/s | 60.0% | 9.7s |
| Gemma-12B | 22.3 GiB | 24 | 0.69/s | 60.0% | 14.1s |

### Throughput-Only (JSON parse errors)
| Model | Disk | seqs | TPS | Accuracy | Issue |
|---|---|---|---|---|---|
| Qwen3-4B | 7.5 GiB | 32 | 0.42/s | 35.0% | reasoning block + bare JSON |
| Qwen3.5-9B | 18.0 GiB | 24 | 0.22/s | 0.0% | V1 runner, Mamba arch |

### Skipped
| Model | Reason |
|---|---|
| Ministral-3B | PixtralForConditionalGeneration incompatible |
| Qwen3.6-MoE | Partial download (2/26 shards) |

## Model Inventory (23 cached)
- 10 vLLM-compatible: tested above
- 13 skipped: GGUF(4), OCR(2), diffusion(1), no weights(5), partial(1)
