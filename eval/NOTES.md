# Model & Engine Notes

## EXAONE 4.0 1.2B

| Item | Value |
|------|-------|
| HuggingFace | `LGAI-EXAONE/EXAONE-4.0-1.2B` |
| GGUF | `LGAI-EXAONE/EXAONE-4.0-1.2B-GGUF` (Q4_K_M recommended) |
| Context Window | 4096 tokens |
| Architecture | `EXAONE4ForCausalLM` |

### Caveats
- **response_format**: MUST use `response_format={"type": "json_object"}` for valid JSON output
- **Prompt**: Use `extract.short.prompt` (compressed, ~1.2KB) — full prompt exceeds 4096 ctx
- **max_tokens**: Set ≤ 512 (prompt ~3500 tokens + response must fit in 4096)
- **Quantization**: Q4_K_M GGUF works on llama-server; BF16 safetensors on vLLM

### Engine Compatibility
| Engine | Status | Notes |
|--------|--------|-------|
| vLLM | ✅ | Needs `--gpu-memory-utilization 0.05` |
| llama-server | ✅ | CPU mode works; GPU requires CUDA image |
| SGLang | ❓ | Not tested (image too large) |

---

## Ministral 3B (Ministral-3-3B-Instruct-2512)

| Item | Value |
|------|-------|
| HuggingFace | `mistralai/Ministral-3-3B-Instruct-2512` |
| Context Window | 8192 tokens |
| Architecture | `Mistral3ForConditionalGeneration` |

### Caveats
- **vLLM**: `Mistral3ForConditionalGeneration` maps to `PixtralForConditionalGeneration` in vLLM nightly → crash. Monkey-patching `config.json` `architectures` to `MistralForCausalLM` does NOT work (vLLM registry overrides). Use OpenRouter or llama-server instead.
- **OpenRouter**: Works via `openrouter/mistralai/ministral-3b-2512`
- **Best for**: 맥락적 기밀사항 감지 (67.5% vs Gemma4 E4B 62.5%)

### Engine Compatibility
| Engine | Status | Notes |
|--------|--------|-------|
| vLLM | ❌ | Pixtral architecture mismatch |
| llama-server | ❓ | Not tested (no GGUF available) |
| OpenRouter | ✅ | Recommended path |
| SGLang | ❓ | Not tested |

---

## Gemma4 E4B (gemma-4-E4B-it)

| Item | Value |
|------|-------|
| HuggingFace | `google/gemma-4-E4B-it` |
| Size | 14.9 GB (BF16 safetensors) |
| Context Window | 8192 tokens |
| Architecture | `Gemma4ForConditionalGeneration` |

### Caveats
- **gpu-memory-utilization**: Use 0.15 minimum (14.9GB model weight)
- **Latency**: ~11.7s per request (large model for edge)
- **Default params optimal**: Optuna 20 trials found no improvement over defaults (temp=0.0, top_p=1.0)
- **Best overall**: 76.5% action accuracy, 100% sensitivity

### Engine Compatibility
| Engine | Status | Notes |
|--------|--------|-------|
| vLLM | ✅ | Recommended; `--enforce-eager` needed |
| llama-server | ❓ | No GGUF available |
| OpenRouter | ❌ | Not available |
| SGLang | ❓ | Not tested |

---

## Gemma4 E2B (gemma-4-E2B-it)

| Item | Value |
|------|-------|
| HuggingFace | `google/gemma-4-E2B-it` |
| Size | 9.5 GB (BF16 safetensors) |
| Context Window | 8192 tokens |
| Architecture | `Gemma4ForConditionalGeneration` |

### Caveats
- **gpu-memory-utilization**: Use 0.20 minimum (0.10 causes KV cache OOM)
- **Tuned params**: temp=0.25, top_p=0.75, json_mode=True, sys_msg=True → 40% (vs 30% baseline)
- **Weak**: 형채적 감지 16.7%, 맥락적 감지 10.0% — weakest model

### Engine Compatibility
| Engine | Status | Notes |
|--------|--------|-------|
| vLLM | ✅ | Needs `--gpu-memory-utilization 0.20` |
| llama-server | ❓ | No GGUF available |
| OpenRouter | ❌ | Not available |
| SGLang | ❓ | Not tested |

---

## Engine Summary

### vLLM (port 8000)
- Image: `vllm/vllm-openai:nightly`
- GPU required
- `--enforce-eager` for all models
- `--trust-remote-code` for Gemma4/EXAONE
- `--limit-mm-per-prompt '{"image":0,"audio":0}'` for Gemma4

### llama-server (port 8002)
- Image: `ghcr.io/ggml-org/llama.cpp:server`
- CPU mode works (GPU requires CUDA image — not available)
- GGUF models only
- `--ctx-size 4096 --threads 4`
- HF cache symlinks don't resolve in Docker → use `cp -L` to copy GGUF

### SGLang (port 8003)
- Image: `lmsysorg/sglang:latest`
- Not tested (Docker image ~15GB, pull failed)
- pip install fails on aarch64 (outlines-core build error)
- Use `--mem-fraction-static` instead of `--gpu-memory-utilization`
