# O-SYS-004: Unified Benchmark Results

## Config
- gpu_utilization: 0.48 (40% free target)
- max_model_len: 4096
- max_num_seqs: 16-32 (model-dependent)
- Benchmarks: our benchmark_v2 (120 cases) + LegalCiteBench (250 cases)

## Our Benchmark Results

| Model | Overall | Morphological | Contextual | TPS | Errors |
|---|---|---|---|---|---|
| Gemma-12B | 74.2% | 74.1% | 68.5% | 1.48/s | 0 |
| E4B | 71.7% | 74.1% | 64.8% | 4.77/s | 0 |
| Gemma-26B | 71.7% | 70.4% | 66.7% | 2.09/s | 0 |
| Granite-8B | 67.5% | 59.3% | 68.5% | 1.44/s | 0 |
| E2B | 62.5% | 59.3% | 57.4% | 10.15/s | 0 |
| EXAONE-1.2B | 51.7% | 42.6% | 51.9% | 10.07/s | 3 |
| Qwen3-4B | 45.8% | 50.0% | 29.6% | 0.51/s | 26 |
| Qwen3.5-9B | 13.3% | 3.7% | 5.6% | 0.18/s | 99 |

## LegalCiteBench Results (heuristic scoring)

| Model | cat3 | cat4-1 | cat4-2 | Avg |
|---|---|---|---|---|
| E4B | 62.0% | 16.0% | 70.0% | 29.6% |
| Granite-8B | 62.8% | 14.0% | 66.4% | 28.6% |
| E2B | 62.8% | 6.0% | 69.2% | 27.6% |
| Gemma-12B | 58.0% | 10.0% | 58.0% | 25.2% |
| EXAONE-1.2B | 62.8% | 6.0% | 57.2% | 25.2% |
| Gemma-26B | 60.0% | 12.0% | 42.0% | 22.8% |

## Removed Models

| Model | Reason |
|---|---|
| Qwen3.5-9B | 13.3% acc, 99 errors. Mamba arch + V1 runner. |
| Qwen3-4B | 45.8% acc, 26 errors. Reasoning blocks break JSON. |
