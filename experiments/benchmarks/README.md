# experiments/benchmarks/

## Benchmarks Used

### benchmark_v2.json (Primary)
- **Source**: Custom-generated (experiments/generate_dataset.py)
- **Cases**: 120 (4 sensitivity × 3 context × 2 type × 2 lang)
- **Metrics**: overall accuracy, morphological accuracy, contextual accuracy
- **Status**: Active

### LegalCiteBench (Secondary)
- **Source**: https://github.com/Sijia711/LegalCiteBench
- **Cases**: 250 sampled (50 per category)
- **Categories**: cat1 (citation retrieval), cat2 (citation completeness), cat3 (citation verification), cat4-1 (case matching), cat4-2 (case verification)
- **Metrics**: heuristic substring scoring (not official LLM-judge)
- **Status**: Active, secondary robustness signal
- **Note**: cat1/cat2 score 0% for local models (closed-book task, expected)

## Usage
```bash
# Run unified benchmark
rye run python experiments/unified_benchmark.py
```
