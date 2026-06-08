# Troubleshooting Guide

This document records every significant issue encountered during the Privacy Router project — model loading, inference engine, dependency, and infrastructure problems — along with root causes, solutions, and the files modified.

---

## Table of Contents

1. [rye sync fails: PyTorch/vLLM index conflicts](#1-rye-sync-fails-pytorchvllm-index-conflicts)
2. [llama.cpp GGUF models produce 17.6% accuracy (all `allow`)](#2-llamacpp-gguf-models-produce-176-accuracy-all-allow)
3. [EXAONE 4.5 33B requires vLLM nightly build](#3-exaone-45-33b-requires-vllm-nightly-build)
4. [EXAONE 4.5 local path workaround for chat template](#4-exaone-45-local-path-workaround-for-chat-template)
5. [GPU OOM: per-model memory utilization tuning](#5-gpu-oom-per-model-memory-utilization-tuning)
6. [Docker build failure: COPY .env](#6-docker-build-failure-copy-env)
7. [SQLModel + SQLAlchemy 2.0 Relationship incompatibility](#7-sqlmodel--sqlalchemy-20-relationship-incompatibility)
8. [EXAONE 4.5 low accuracy: `is_load_bearing` misclassification](#8-exaone-45-low-accuracy-is_load_bearing-misclassification)

---

## 1. rye sync fails: PyTorch/vLLM index conflicts

**Symptom:** `rye sync` fails with dependency resolution errors when PyTorch or vLLM custom package indexes are defined in `pyproject.toml`.

**Root Cause:** The `pyproject.toml` contained custom `[[tool.rye.sources]]` entries pointing to PyTorch and vLLM pip indexes. These indexes serve packages with version numbers that conflict with the versions available on PyPI, causing `rye`'s resolver to enter an inconsistent state.

**Solution:** Remove all custom PyTorch/vLLM index entries from `pyproject.toml`. Use PyPI-only resolution. Pin compatible versions directly:

```toml
# Before (broken)
[[tool.rye.sources]]
name = "pytorch"
url = "https://download.pytorch.org/whl/cu124"

[[tool.rye.sources]]
name = "vllm"
url = "https://wheels.vllm.ai/nightly"

# After (working)
dependencies = [
    "transformers>=5.10.0",
    "torch>=2.11.0",
    "torchvision>=0.26.0",
    ...
]
```

**Files modified:** `pyproject.toml`, `requirements.lock`, `requirements-dev.lock`
**Commit:** `a959964`

---

## 2. llama.cpp GGUF models produce 17.6% accuracy (all `allow`)

**Symptom:** All quantized models served via `llama-server` (llama.cpp) score 17.6% accuracy — they only pass the 3 non-sensitive "allow" cases and fail every sensitive case by returning `allow` instead of detecting PII/business secrets.

| Model | Quantization | Accuracy | Serving |
|---|---|---|---|
| Gemma 4 E2B | Q4_K_M | 17.6% | llama-server |
| Gemma 4 E2B | Q8_0 | 17.6% | llama-server |
| Gemma 4 E4B | Q4_K_M | 17.6% | llama-server |
| EXAONE 1.2B | Q4_K_M | 17.6% | llama-server |
| EXAONE 1.2B | Q8_0 | 17.6% | llama-server |

**Root Cause:** Two compounding factors:

1. **Model capacity:** At 1.2B–4B parameters with aggressive quantization (Q4_K_M = 4-bit), these models lack the reasoning capacity to follow the complex `extract.prompt` instructions. The prompt requires multi-step reasoning (three-harm test, contextual analysis, Korean language understanding) that exceeds what quantized small models can do.

2. **llama.cpp chat template handling:** `llama-server` applies its own chat template wrapping. For some models (especially EXAONE), the template format doesn't match the model's training format, causing the model to ignore the system prompt entirely and default to "no sensitive information detected."

**Solution:** Switch from llama.cpp GGUF quantized models to vLLM with full-precision (BF16) weights. Same models at full precision:

| Model | Quantization | Accuracy | Serving |
|---|---|---|---|
| Gemma 4 E2B | BF16 | 64.7% | vLLM |
| Gemma 4 E4B | BF16 | 70.6% | vLLM |
| Gemma 4 12B | BF16 | 82.4% | vLLM |

The jump from 17.6% → 64–82% confirms the issue was quantization degradation, not prompt design.

**Files modified:** `scripts/run_local_eval.sh` (rewrote model mapping from llama-server to vLLM), `scripts/eval_all.py` (updated model configs)
**Commit:** `7a3ea98`

---

## 3. EXAONE 4.5 33B requires vLLM nightly build

**Symptom:** `vllm` (stable release from PyPI) fails to load `LGAI-EXAONE/EXAONE-4.5-33B-FP8` with errors about unsupported architecture or missing model class.

**Root Cause:** EXAONE 4.5 uses a custom transformer architecture (`EXAONEForCausalLM`) that was only added to vLLM in nightly builds. The stable release doesn't include the model class registration for EXAONE 4.5.

**Solution:** Install vLLM from the nightly wheel index:

```bash
pip install vllm --extra-index-url https://wheels.vllm.ai/nightly
```

Or build from source:

```bash
pip install git+https://github.com/vllm-project/vllm.git
```

**Files modified:** None (runtime dependency install)
**Verification:** After install, `python -c "from vllm.model_executor.models import EXAONEForCausalLM"` should succeed.

---

## 4. EXAONE 4.5 local path workaround for chat template

**Symptom:** vLLM loads EXAONE 4.5 from HuggingFace (`LGAI-EXAONE/EXAONE-4.5-33B-FP8`) but produces garbled or empty outputs. The model doesn't follow the extraction prompt.

**Root Cause:** The HuggingFace repo's `tokenizer_config.json` contains a chat template that wraps messages in EXAONE's proprietary format. vLLM applies this template automatically, but the template is incompatible with the OpenAI-compatible API format we use (system message → user message flow). The model receives a doubly-wrapped prompt.

**Solution:** Create a local copy of the model files with a corrected `tokenizer_config.json` that either:
- Removes the custom `chat_template` field (lets vLLM use its default)
- Replaces it with a standard Jinja2 template matching the model's training format

```bash
# Copy model locally
cp -r ~/.cache/huggingface/hub/models--LGAI-EXAONE--EXAONE-4.5-33B-FP8 /tmp/exaone45-fp8-fixed

# Edit /tmp/exaone45-fp8-fixed/tokenizer_config.json
# Remove or fix the "chat_template" field
```

Then reference the local path in `eval_all.py`:

```python
"exaone-4.5-33b-fp8": {
    "model": "openai//tmp/exaone45-fp8-fixed",
    "api_base": "http://localhost:8000/v1",
    ...
}
```

**Files modified:** `/tmp/exaone45-fp8-fixed/tokenizer_config.json` (local model copy), `scripts/eval_all.py`
**Commit:** `3e6ab56`

---

## 5. GPU OOM: per-model memory utilization tuning

**Symptom:** vLLM crashes with `torch.cuda.OutOfMemoryError` when loading certain models, especially on a single GPU with limited VRAM.

**Root Cause:** vLLM's default `--gpu-memory-utilization 0.9` reserves 90% of GPU memory for the KV cache. Combined with model weights, this exceeds available VRAM for larger models.

**Solution:** Set `--gpu-memory-utilization` per model based on its size:

| Model | Params | GPU Memory Util | Rationale |
|---|---|---|---|
| Gemma 4 E2B | 2B | 0.3 | Small model, leave room for KV cache |
| Gemma 4 E4B | 4B | 0.4 | Medium model |
| EXAONE 4.5 33B | 33B | 0.6 | Large FP8 model, needs most of VRAM |

```bash
# In scripts/run_local_eval.sh
GPU_MODELS=(
    "gemma-4-e2b-bf16|google/gemma-4-E2B-it|--gpu-memory-utilization 0.3"
    "gemma-4-e4b-bf16|google/gemma-4-E4B-it|--gpu-memory-utilization 0.4"
    "exaone-4.5-33b-fp8|LGAI-EXAONE/EXAONE-4.5-33B-FP8|--gpu-memory-utilization 0.6"
)
```

Also add `--max-model-len 32768` to cap context length and reduce KV cache memory pressure.

**Files modified:** `scripts/run_local_eval.sh`, `scripts/start_vllm.sh`
**Commit:** `7a3ea98`

---

## 6. Docker build failure: COPY .env

**Symptom:** `docker compose build` fails with:

```
ERROR: failed to solve: failed to compute cache key: "/.env" not found
```

**Root Cause:** The `Dockerfile` contained `COPY .env ./` which attempted to copy the `.env` file into the build context. Since `.env` is gitignored and not present in the build context, the build fails.

**Solution:** Remove `COPY .env ./` from `Dockerfile`. Environment variables are injected at runtime via `env_file: .env` in `docker-compose.yml`, not at build time.

```dockerfile
# Before (broken)
COPY .env ./
COPY . ./

# After (working)
COPY . ./
```

**Files modified:** `Dockerfile`
**Commit:** `a2d6999`

---

## 7. SQLModel + SQLAlchemy 2.0 Relationship incompatibility

**Symptom:** Server startup crashes with:

```
sqlalchemy.exc.InvalidRequestError: When initializing mapper mapped class ... could not
locate a configure-time resolution for attribute ...
```

Or:

```
TypeError: issubclass() arg 1 must be a class
```

**Root Cause:** SQLModel's `list["Model"]` type annotation for relationships is incompatible with SQLAlchemy 2.0's mapper configuration. SQLAlchemy 2.0 requires explicit `relationship()` calls with string-based `back_populates`, but SQLModel's `Field(sa_relationship=...)` approach conflicts with the `list["Model"]` type hint.

**Solution:** Remove all `Relationship` declarations from the SQLModel classes. Since no code in the codebase actually uses the ORM relationship navigation (all queries use explicit `.where()` clauses), the relationships were dead code.

```python
# Before (broken)
class AgentConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    logs: list["UsageLog"] = Relationship(back_populates="agent_config")

# After (working)
class AgentConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # Relationships removed — queries use explicit .where() joins
```

**Files modified:** `db/models.py`
**Commit:** `cb594e9`

---

## 8. EXAONE 4.5 low accuracy: `is_load_bearing` misclassification

**Symptom:** EXAONE 4.5 33B FP8 achieves only 35.3% accuracy despite correctly detecting PII. The model identifies records but misclassifies the `is_load_bearing` field, causing the router to choose `block` instead of `selective_mask` (or vice versa).

**Example from eval data** (`PII 포함(creation)` case):
- Input: "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."
- Expected: `selective_mask` (creation context — mask PII and send)
- EXAONE 4.5 output: `block` (incorrect — treated as load-bearing interrogation)
- Extracted records are correct, but `is_load_bearing: false` on the resident registration number (should be `true`)

**Root Cause:** EXAONE 4.5 has weaker instruction-following for nuanced contextual judgment. The `is_load_bearing` field requires the model to understand whether the sensitive information is *incidental* (mask and continue) or *central to the request's purpose* (prompt user). EXAONE 4.5 defaults to conservative classification (block/prompt_user) even when the context suggests masking is appropriate.

**Current Status:** Partially mitigated. The extraction accuracy is acceptable for PII detection, but the routing decision requires a stronger model. For production use, EXAONE 4.5 should be paired with a separate judge model (e.g., Gemini 3.1 Flash Lite) for routing decisions.

**Files modified:** No code changes — this is a model capability limitation.
**Recommendation:** Use EXAONE 4.5 for extraction only, not for end-to-end classify+route.

---

## Summary: Model Performance by Serving Stack

| Model | Params | Serving | Quant | Accuracy | Avg Time |
|---|---|---|---|---|---|
| Gemma 4 E2B | 2B | llama-server | Q4_K_M | 17.6% | 0.6s |
| Gemma 4 E2B | 2B | llama-server | Q8_0 | 17.6% | 0.7s |
| Gemma 4 E4B | 4B | llama-server | Q4_K_M | 17.6% | 0.7s |
| EXAONE 1.2B | 1.2B | llama-server | Q4_K_M | 17.6% | 0.7s |
| EXAONE 1.2B | 1.2B | llama-server | Q8_0 | 17.6% | 0.7s |
| Gemma 4 E2B | 2B | vLLM | BF16 | 64.7% | 5.4s |
| Gemma 4 E4B | 4B | vLLM | BF16 | 70.6% | 8.3s |
| Gemma 4 12B | 12B | vLLM nightly | BF16 | 82.4% | 25.1s |
| EXAONE 4.5 33B | 33B | vLLM nightly | FP8 | 35.3% | 12.7s |
| Gemma 4 26B-A4B | 26B MoE | OpenRouter | — | 100.0% | 5.0s |
| Gemini 3.1 Flash Lite | — | OpenRouter | — | 100.0% | 1.9s |

**Key Takeaway:** For local deployment, vLLM with BF16 precision is mandatory. Quantized GGUF models via llama.cpp are unsuitable for this prompt's complexity. For production, OpenRouter-hosted Gemma 4 26B or Gemini 3.1 Flash Lite provide 100% accuracy at low cost.
