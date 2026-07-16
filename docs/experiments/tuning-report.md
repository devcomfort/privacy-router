# Model Tuning Report — Privacy Router Extractor

**Date**: 2026-06-18
**Models**: EXAONE 4.0 1.2B, Ministral 3B, Gemma4 E4B, Gemma4 E2B
**Engines**: vLLM, llama-server, OpenRouter

## Executive Summary

Gemma4 E4B on vLLM achieves the best overall accuracy (76.5%) with perfect specificity (0% false positives). However, **형태적 기밀사항 감지(83.3%)가 맥락적 기밀사항 감지(62.5%)보다 20.8%p 우수**합니다. Ministral 3B는 맥락적 감지에서 Gemma4 E4B보다 우수(67.5% vs 62.5%)하며, 지연 시간이 5배 낮습니다(2.4s vs 11.7s).

## Baseline Results (5 trials × 17 cases)

| Model | Engine | 전체% | 형태적% | 맥락적% | FalseP% | Latency |
|-------|--------|-------|---------|---------|---------|---------|
| Gemma4 E4B (4B) | vLLM | **76.5%** | 83.3% | 62.5% | 0% | 11.71s |
| Ministral 3B (3B) | OpenRouter | 71.8% | 63.3% | **67.5%** | 0% | 2.37s |
| EXAONE 1.2B (1.2B) | vLLM | 42.4% | 53.3% | 12.5% | 0% | 1.39s |
| EXAONE 1.2B (1.2B) | llama | 35.3% | 50.0% | 0.0% | 0% | 1.73s |
| Gemma4 E2B (2B) | vLLM | 28.2% | 16.7% | 10.0% | 0% | 2.15s |

**형태적 (Pattern-based)**: PII (주민등록번호, 전화번호, 이메일, 실명) — 패턴 기반 감지
**맥락적 (Context-based)**: 사업비밀, 연구아이디어, 전략, 예산, 내부URL — 맥락 기반 감지
**FalseP**: 비민감 케이스에서의 위양성 비율 (0% = 완벽한 특이도)

## Optuna Tuning Results (20 trials × 10 cases)

| Model | Baseline | Tuned | Δ | Best Params |
|-------|----------|-------|---|-------------|
| Gemma4 E4B vLLM | 70% | 70% | — | temp=0.0, top_p=1.0 (default) |
| EXAONE 1.2B vLLM | 50% | **60%** | +10% | temp=0.5, top_p=0.75 |
| Gemma4 E2B vLLM | 30% | **40%** | +10% | temp=0.25, top_p=0.75, json_mode=True, sys_msg=True |

### Key Findings
1. **Gemma4 E4B**: Default parameters already optimal. No improvement from tuning.
2. **EXAONE 1.2B**: Higher temperature (0.5) helps — some randomness aids reasoning in small models.
3. **Gemma4 E2B**: JSON mode + system message significantly improve structured output compliance.

## Cross-Engine Comparison: EXAONE 1.2B

| Metric | vLLM | llama-server | Difference |
|--------|------|-------------|------------|
| Action Accuracy | 42.4% | 35.3% | +7.1% |
| Sensitivity | 47.1% | 58.8% | -11.7% |
| Latency | 1.39s | 1.73s | -0.34s |

**Statistical test**: Paired t-test on 17 cases
- t-statistic: 0.728
- **Not statistically significant** (p ≥ 0.05, critical value ±2.145 for df=16)
- Conclusion: No significant difference between vLLM and llama-server for EXAONE 1.2B.

## Accuracy by Tag (Best Model: Gemma4 E4B vLLM)

| Tag | Accuracy | n | Notes |
|-----|----------|---|-------|
| none (non-sensitive) | 100% | 3 | Perfect false-positive avoidance |
| interrogation | 100% | 2 | Strong verb heuristic |
| identity | 83% | 6 | PII well-detected |
| creation | 80% | 5 | Good verb heuristic |
| competitive | 60% | 10 | Weakest — business secrets hard |
| statement | 67% | 3 | Budget/strategy statements challenging |

## Multi-Turn Evaluation (Gemma4 E4B vLLM)

| Conversation | Sensitivity | Action Accuracy | Turns |
|---|---|---|---|
| adversarial_rephrase | 100% | 33% | 3 |
| adversarial_context_switch | 100% | 67% | 3 |
| adversarial_false_positive | 67% | 33% | 3 |
| **Average** | **89%** | **44%** | — |

Multi-turn is significantly harder than single-turn (44% vs 76.5%). Adversarial evasion techniques reduce action accuracy but sensitivity detection remains strong (89%).
| consultation | 33% | 3 | Research consultation weakest |
| safety | 100% | 1 | Internal URLs detected |

## Engine-Specific Issues

### vLLM
- **Ministral 3B**: `Mistral3ForConditionalGeneration` architecture maps to `PixtralForConditionalGeneration` in vLLM nightly. Monkey-patching config.json `architectures` to `MistralForCausalLM` doesn't help — vLLM model registry overrides. Use OpenRouter or llama-server instead.
- **Gemma4 E2B**: Requires gpu-memory-utilization ≥ 0.20 (KV cache memory)
- **EXAONE 1.2B**: Requires `response_format=json_object` for valid JSON output
- **Gemma4 E4B**: 14.6GB model weight → 11.7s latency per request

### llama-server
- **CPU-only**: Docker image lacks CUDA support (ghcr.io/ggml-org/llama.cpp:server)
- **EXAONE 1.2B GGUF**: Q4_K_M quantization works, but lower accuracy than vLLM BF16
- **Symlink issue**: HF cache symlinks don't resolve in Docker — need `cp -L` to copy GGUF

### SGLang
- **Docker image**: ~15GB, too large to pull in session
- **Not tested**: Requires manual image pull

## Recommendations

1. **Production**: Use Gemma4 E4B on vLLM for best accuracy (76.5%)
2. **Cost-sensitive**: Use Ministral 3B on OpenRouter for 71.8% at 1/5 the latency
3. **Edge/On-device**: Use EXAONE 1.2B on vLLM with tuned params (temp=0.5, top_p=0.75)
4. **Prompt improvement**: Focus on `competitive` and `consultation` cases — weakest areas
5. **Engine choice**: No statistically significant difference between vLLM and llama-server

## Files

- `scripts/eval_runner.py` — Unified eval runner
- `scripts/tune_params.py` — Optuna tuner
- `docker-compose.engines.yml` — Multi-engine Docker setup
- `agents/extractor/extract.short.prompt` — Compressed prompt for ≤2B models
- `test_data/` — 15 multi-turn test conversations
- `docs/experiments/results/` — Per-model eval JSON
- `docs/developments/results/tuning/` — Optuna tuning JSON
