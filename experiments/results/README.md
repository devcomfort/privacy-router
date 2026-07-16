# experiments/results/

## Key Result Files

| File | Description |
|---|---|
| `unified_benchmark.json` | **Primary**: 8 models × 2 benchmarks (our 120 + LegalCiteBench 250) |
| `all_models_sweep.json` | 8 models × seqs sweep (throughput + accuracy) |
| `model_inventory.json` | 21 cached models with status (ok/skip) |
| `full_param_sweep.json` | E2B/E4B/EXAONE seqs=16-64 sweep |
| `concurrency_sweep.json` | Concurrency 1-32 sweep |
| `vllm_param_sweep.json` | Early vLLM parameter sweep |
| `acceleration_benchmark.json` | ngram/MRv2 comparison |

## Final Model Rankings (gpu=0.48, max_len=4096)

| Rank | Model | Overall | Morph | Ctx | TPS | Errors |
|---|---|---|---|---|---|---|
| 1 | **Gemma-12B** | 74.2% | 74.1% | 68.5% | 1.48/s | 0 |
| 2 | E4B | 71.7% | 74.1% | 64.8% | 4.77/s | 0 |
| 3 | Gemma-26B | 71.7% | 70.4% | 66.7% | 2.09/s | 0 |
| 4 | Granite-8B | 67.5% | 59.3% | 68.5% | 1.44/s | 0 |
| 5 | E2B | 62.5% | 59.3% | 57.4% | 10.15/s | 0 |
| 6 | EXAONE-1.2B | 51.7% | 42.6% | 51.9% | 10.07/s | 3 |

## Removed Models

| Model | Reason |
|---|---|
| Qwen3.5-9B | 13.3% accuracy, 99/120 errors. Mamba architecture incompatible with V2 runner. |
| Qwen3-4B | 45.8% accuracy, 26/120 errors. Poor JSON parsing (reasoning blocks). |
| Ministral-3B | PixtralForConditionalGeneration override (vision_config in config.json). |
| Qwen3.6-MoE | Partial download (2/26 shards). |
