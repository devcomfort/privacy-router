# Experiment Index

## ID Scheme
- **Plans**: `P-{MODEL}-{SEQ}` — 실험 계획
- **Observations**: `O-{MODEL}-{SEQ}` — 관측 결과 (raw data)
- **Insights**: `I-{SEQ}` — 분석/통찰

## Final Model List (6 valid, 15 skipped)

### Valid Models (tested, accuracy > 50%)
| Tag | Model | Size | Best Accuracy | Best TPS |
|---|---|---|---|---|
| Gemma-12B | google/gemma-4-12B-it | 22.3 GiB | 74.2% | 1.48/s |
| E4B | google/gemma-4-E4B-it | 14.9 GiB | 71.7% | 4.77/s |
| Gemma-26B | google/gemma-4-26B-A4B-it | 48.1 GiB | 71.7% | 2.09/s |
| Granite-8B | ibm-granite/granite-4.1-8b | 16.4 GiB | 67.5% | 1.44/s |
| E2B | google/gemma-4-E2B-it | 9.6 GiB | 62.5% | 10.15/s |
| EXAONE-1.2B | LGAI-EXAONE/EXAONE-4.0-1.2B | 2.4 GiB | 51.7% | 10.07/s |

### Removed (with reasons)
| Tag | Reason |
|---|---|
| Qwen3.5-9B | 13.3% acc, 99 errors. Mamba arch + V1 runner. |
| Qwen3-4B | 45.8% acc, 26 errors. Reasoning blocks break JSON. |
| Ministral-3B | Pixtral multimodal override. |
| Qwen3.6-MoE | Partial download (2/26 shards). |

## Experiments

### Phase 1: Prompt Optimization
| ID | Plan | Observation | Insight |
|---|---|---|---|
| P-E4B-001 | [plan](P-E4B-001.md) | [data](../observations/O-E4B-001.md) | [analysis](../insights/I-001.md) |

### Phase 2: Parameter Tuning
| ID | Plan | Observation | Insight |
|---|---|---|---|
| P-E4B-002 | [plan](P-E4B-002.md) | [data](../observations/O-E4B-002.md) | [analysis](../insights/I-002.md) |

### Phase 3: vLLM Acceleration
| ID | Plan | Observation | Insight |
|---|---|---|---|
| P-SYS-001 | [plan](P-SYS-001.md) | [data](../observations/O-SYS-001.md) | [analysis](../insights/I-003.md) |

### Phase 4: Per-Model Sweep
| ID | Plan | Observation | Insight |
|---|---|---|---|
| P-SYS-002 | [plan](P-SYS-002.md) | [data](../observations/O-SYS-002.md) | [analysis](../insights/I-004.md) |
| P-SYS-003 | — | [data](../observations/O-SYS-003.md) | [analysis](../insights/I-005.md) |

### Phase 5: Unified Benchmark
| ID | Observation | Insight |
|---|---|---|
| — | [data](../observations/O-SYS-004.md) | [analysis](../insights/I-006.md) |

## Key Files
| File | Description |
|---|---|
| `experiments/datasets/benchmark_v2.json` | 120 cases (4×3×2×2) |
| `experiments/prompt_variants/extract.fewshot_v3.prompt` | Active prompt |
| `experiments/results/unified_benchmark.json` | Final benchmark results |
| `experiments/results/model_inventory.json` | Model inventory (21 entries) |
