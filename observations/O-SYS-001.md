# O-SYS-001: vLLM Acceleration Results

## Raw Data
- `experiments/results/acceleration_benchmark.json`
- `experiments/results/concurrency_sweep.json`

## Technique Comparison (E4B, 120 cases)
| Technique | Accuracy | Throughput | Latency | Notes |
|---|---|---|---|---|
| Baseline | 74.2% | 1.2/s | 4.8s | No optimization |
| +ngram speculative | 74.2% | 1.35/s | 4.2s | 0% acc impact, -11% latency |
| +MRv2 | 74.2% | 2.4/s | 2.8s | +100% throughput |
| +MRv2 + prefix-caching | 74.2% | 2.4/s | 2.8s | Same as MRv2 alone |
| +ngram + MRv2 | — | — | — | **INCOMPATIBLE** (vLLM 0.23.0) |

## Concurrency Sweep (E4B, gpu=0.75)
| Concurrency | Throughput | Accuracy | Latency |
|---|---|---|---|
| 1 | 0.31/s | 74.2% | 3.2s |
| 2 | 0.62/s | 74.2% | 3.2s |
| 4 | 1.24/s | 74.2% | 3.2s |
| 8 | 2.46/s | 74.2% | 3.3s |
| 12 | 2.78/s | 74.2% | 4.3s |
| 16 | 3.10/s | 74.2% | 5.2s |
| 24 | 3.10/s | 60.0% | 7.7s |
| 32 | 2.80/s | 55.0% | 11.4s |

## Key Findings
1. **MRv2**: +100% throughput, 0% accuracy impact
2. **ngram**: +12% throughput, incompatible with MRv2
3. **Concurrency**: Near-linear scaling to 16x, then plateau/decline
4. **Optimal concurrency**: 16x for E4B (3.10/s, 74.2% acc)
