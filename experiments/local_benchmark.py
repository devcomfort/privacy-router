#!/usr/bin/env python3
"""Local model benchmark: speed (TTFT, TPOT, tok/s) + accuracy (Morph, Contextual).
Runs each model sequentially via vLLM, evaluates with fewshot_v2 prompt.
Uses instructor for structured output with retry logic.
"""

import concurrent.futures
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import instructor
from instructor.hooks import Hooks
from litellm import completion
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import Judge  # noqa: E402

os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["HF_HUB_OFFLINE"] = "1"

# ── Configuration ──
PORT = 8000
API_BASE = f"http://localhost:{PORT}/v1"
MAX_RETRIES = 3
# Per-model concurrency: E2B=32, E4B=24, EXAONE=32
MODEL_CONCURRENT = {
    "google/gemma-4-E2B-it": 32,
    "google/gemma-4-E4B-it": 24,
    "google/gemma-4-12B-it": 16,
    "LGAI-EXAONE/EXAONE-4.0-1.2B": 32,
}
CONCURRENT = 32  # default, overridden per-model
MODELS = [
    {"name": "google/gemma-4-E2B-it", "tag": "Gemma4-E2B"},
    {"name": "google/gemma-4-E4B-it", "tag": "Gemma4-E4B"},
    {"name": "google/gemma-4-12B-it", "tag": "Gemma4-12B"},
    {"name": "google/gemma-4-26B-A4B-it", "tag": "Gemma4-26B-MoE"},
    {"name": "google/diffusiongemma-26B-A4B-it", "tag": "DiffusionGemma-26B"},
    {"name": "LGAI-EXAONE/EXAONE-4.0-1.2B", "tag": "EXAONE-4.0-1.2B"},
    {"name": "LGAI-EXAONE/EXAONE-4.5-33B", "tag": "EXAONE-4.5-33B"},
    {"name": "LGAI-EXAONE/EXAONE-4.5-33B-FP8", "tag": "EXAONE-4.5-33B-FP8"},
    {"name": "mistralai/Ministral-3-3B-Instruct-2512", "tag": "Ministral-3B"},
    {"name": "ibm-granite/granite-4.1-8b", "tag": "Granite-4.1-8B"},
    {"name": "Qwen/Qwen3.5-9B", "tag": "Qwen3.5-9B"},
    {"name": "Qwen/Qwen3.6-35B-A3B", "tag": "Qwen3.6-35B-MoE"},
]

PROMPT_FILE = Path(__file__).resolve().parents[0] / "prompt_variants" / "extract.fewshot_v3.prompt"


# ── Structured output models (matching Extractor schema) ──
class ExtractionSensitivity(BaseModel):
    is_sensitive: bool = Field(description="Whether sensitive information was detected")
    rationale: str = Field(default="", description="Explanation of the assessment")


class ExtractionRecord(BaseModel):
    category: str = Field(description="SCREAMING_SNAKE_CASE tag (e.g., RESIDENT_REGISTRATION_NUMBER)")
    span: str = Field(description="Exact substring detected in the original text")
    is_essential: bool = Field(default=False, description="True if this record is essential to the query's meaning")


class ExtractionResult(BaseModel):
    """Structured output matching the Extractor's schema."""

    sensitivity: ExtractionSensitivity
    records: list[ExtractionRecord] = Field(default_factory=list)


# ── Test cases from benchmark_v2 dataset (120 cases) ──
_BENCH_V2_PATH = Path(__file__).resolve().parent / "datasets" / "benchmark_v2.json"
if _BENCH_V2_PATH.exists():
    with open(_BENCH_V2_PATH, encoding="utf-8") as _f:
        _bench = json.load(_f)
    CASES = [
        {
            "name": f"{c['language']}: {c['id']}",
            "text": c["text"],
            "action": c["expected_action"],
            "detection_type": c["detection_type"],
        }
        for c in _bench["cases"]
    ]
else:
    CASES = []
    print(f"WARNING: {_BENCH_V2_PATH} not found, no test cases loaded")

POLICY_NORMALIZE = {
    "allow": "allow",
    "block": "block",
    "selective_mask": "selective_mask",
}


def cleanup_vllm():
    """Kill all vLLM processes and wait for GPU memory to be freed."""
    print("  Cleaning up previous vLLM processes...")
    with contextlib.suppress(Exception):
        subprocess.run(["pkill", "-9", "-f", "vllm.entrypoints.openai.api_server"], capture_output=True, timeout=5)
    with contextlib.suppress(Exception):
        subprocess.run(["pkill", "-9", "-f", "VLLM::EngineCore"], capture_output=True, timeout=5)
    for _ in range(30):
        try:
            req = urllib.request.Request(f"{API_BASE}/models", headers={"Authorization": "Bearer dummy"})
            with urllib.request.urlopen(req, timeout=1) as _:
                pass
        except Exception:
            break
        time.sleep(2)
    # Wait for GPU memory to be freed (need ~80 GiB for large models)
    for i in range(60):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            used_str = result.stdout.strip().split()[0]
            if used_str == "[N/A]" or not used_str.isdigit():
                # nvidia-smi doesn't support memory query; just wait
                if i >= 6:
                    return
                time.sleep(5)
                continue
            used_mb = int(used_str)
            if used_mb < 1000:  # Less than 1 GiB used = clean
                print(f"  GPU memory freed: {used_mb} MiB used")
                return
            if i % 10 == 0:
                print(f"  Waiting for GPU memory: {used_mb} MiB still used...")
        except Exception:
            pass
        time.sleep(5)
    print("  Warning: GPU memory may not be fully freed")


def wait_for_server(proc, timeout_iter=300):
    """Wait for vLLM server to be ready. Detect crashes early."""
    print(f"Waiting for vLLM server on port {PORT}...")
    for _i in range(timeout_iter):
        # Check if vLLM process crashed
        if proc.poll() is not None:
            print(f"  vLLM process exited with code {proc.returncode}")
            return False
        try:
            req = urllib.request.Request(f"{API_BASE}/models", headers={"Authorization": "Bearer dummy"})
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    print("vLLM server is ready.")
                    return True
        except Exception:
            time.sleep(2)
    return False


def _process_single_case(case, prompt_template, client, judge, model_name):
    """Process a single test case. Returns result dict."""
    rendered = prompt_template.replace("{{text}}", case["text"])
    start_time = time.time()
    action = "ERROR"
    generated_text = ""
    ttft = None
    prompt_log = []
    actual_retries = 0

    hooks = Hooks()
    prompt_log_ref = prompt_log

    def _capture_kwargs(*args, **_kw):
        kwargs = args[0] if args else _kw
        msgs = kwargs.get("messages", [])
        prompt_log_ref.append(
            {
                "attempt": len(prompt_log_ref) + 1,
                "messages": [dict(m) for m in msgs],
            }
        )

    def _capture_response(*args, **_kw):
        response = args[0] if args else None
        if prompt_log_ref and response:
            try:
                content = response.choices[0].message.content
                prompt_log_ref[-1]["response"] = content[:500]
            except Exception:
                pass

    def _count_retry(*args, **_kw):
        nonlocal actual_retries
        error = args[0] if args else None
        attempt_number = args[1] if len(args) > 1 else _kw.get("attempt_number", 0)
        actual_retries = attempt_number
        if prompt_log_ref:
            prompt_log_ref[-1]["error"] = str(error)[:300]

    hooks.on("completion:kwargs", _capture_kwargs)
    hooks.on("completion:response", _capture_response)
    hooks.on("parse:error", _count_retry)

    try:
        resp = client.chat.completions.create(
            model=f"openai/{model_name}",
            messages=[{"role": "user", "content": rendered}],
            response_model=ExtractionResult,
            max_retries=MAX_RETRIES,
            temperature=0.2,
            top_p=1.0,
            max_tokens=1024,
            api_base=API_BASE,
            hooks=hooks,
        )
        sensitivity_dict = resp.sensitivity.model_dump()
        records_list = [r.model_dump() for r in resp.records]
        judgment = judge.classify(
            sensitivity=sensitivity_dict,
            records=records_list,
            text=case["text"],
        )
        action = POLICY_NORMALIZE.get(judgment.policy_action, judgment.policy_action)
        end_time = time.time()
        total_time = end_time - start_time
        ttft = total_time
        generated_text = resp.model_dump_json()
        est_tokens = len(generated_text) // 4
        tpot = total_time / max(1, est_tokens)
        tokens_per_sec = est_tokens / total_time if total_time > 0 else 0
    except Exception as e:
        end_time = time.time()
        total_time = end_time - start_time
        actual_retries = MAX_RETRIES
        if prompt_log:
            prompt_log[-1]["error"] = str(e)[:300]
        tpot = 0
        tokens_per_sec = 0

    expected = case["action"]
    is_correct = action == expected
    return {
        "case": case["name"],
        "detection_type": case["detection_type"],
        "language": "EN" if case["name"].startswith("EN:") else "KO",
        "is_correct": is_correct,
        "ttft_ms": (ttft or 0) * 1000,
        "tpot_ms": tpot * 1000,
        "tokens_per_sec": tokens_per_sec,
        "latency_s": total_time,
        "output_len": len(generated_text),
        "predicted_action": action,
        "expected_action": expected,
        "retries_used": actual_retries,
        "attempts": prompt_log,
        "structured_result": action != "ERROR",
    }


def evaluate_model(model_name: str, prompt_template: str, n_trials=1, concurrency=1):
    print(f"\n--- Evaluating {model_name} ---")

    client = instructor.from_litellm(
        completion,
        mode=instructor.Mode.JSON,
    )
    judge = Judge()
    results = []

    for trial in range(n_trials):
        print(f"  Trial {trial + 1}/{n_trials}")
        t0_all = time.time()
        if concurrency > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {
                    executor.submit(_process_single_case, case, prompt_template, client, judge, model_name): case
                    for case in CASES
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        case = futures[future]
                        print(f"    Error on {case['name']}: {type(e).__name__}: {str(e)[:80]}")
        else:
            for case in CASES:
                results.append(_process_single_case(case, prompt_template, client, judge, model_name))
        elapsed_all = time.time() - t0_all
        print(f"  Cases done in {elapsed_all:.1f}s ({elapsed_all / len(CASES):.1f}s/case)")

    if not results:
        return None

    def agg_by_type(filter_type):
        subset = [r for r in results if r["detection_type"] == filter_type]
        if not subset:
            return 0
        return sum(1 for r in subset if r["is_correct"]) / len(subset) * 100

    def agg_by_lang(lang):
        subset = [r for r in results if r["language"] == lang]
        if not subset:
            return 0
        return sum(1 for r in subset if r["is_correct"]) / len(subset) * 100

    morph_pct = agg_by_type("morphological")
    ctx_pct = agg_by_type("contextual")
    ko_pct = agg_by_lang("KO")
    en_pct = agg_by_lang("EN")
    overall_pct = sum(1 for r in results if r["is_correct"]) / len(results) * 100

    avg_ttft = sum(r["ttft_ms"] for r in results) / len(results)
    avg_tpot = sum(r["tpot_ms"] for r in results) / len(results)
    avg_tps = sum(r["tokens_per_sec"] for r in results) / len(results)
    avg_lat = sum(r["latency_s"] for r in results) / len(results)
    avg_retries = sum(r["retries_used"] for r in results) / len(results)
    structured_rate = sum(1 for r in results if r["structured_result"]) / len(results) * 100

    return {
        "overall_pct": overall_pct,
        "morph_pct": morph_pct,
        "ctx_pct": ctx_pct,
        "ko_pct": ko_pct,
        "en_pct": en_pct,
        "avg_ttft_ms": avg_ttft,
        "avg_tpot_ms": avg_tpot,
        "avg_tps": avg_tps,
        "avg_latency_s": avg_lat,
        "avg_retries": avg_retries,
        "structured_rate_pct": structured_rate,
        "n_cases": len(results),
        "details": results,
    }


RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
SCHEMA_VERSION = "v2-extractor-judge"


def _save_incremental(results: dict):
    """Save current results incrementally (after each model).
    Uses run_id in filename to avoid contamination from old runs.
    """
    base = Path(__file__).resolve().parent / "results"
    base.mkdir(exist_ok=True)

    summary_path = base / f"local_benchmark_{RUN_ID}.json"
    detail_path = base / f"local_benchmark_{RUN_ID}_details.json"

    slim = {}
    for tag, s in results.items():
        slim[tag] = {k: v for k, v in s.items() if k != "details"}

    payload = {
        "run_id": RUN_ID,
        "schema_version": SCHEMA_VERSION,
        "pipeline": "extractor_judge",
        "prompt_file": str(PROMPT_FILE.name),
        "n_cases": len(CASES),
        "timestamp": datetime.now().isoformat(),
        "models": slim,
    }
    detail_payload = {**payload, "models": results}

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_payload, f, indent=2, ensure_ascii=False)

    # Symlink to "latest"
    latest = base / "local_benchmark_latest.json"
    latest_detail = base / "local_benchmark_latest_details.json"
    latest.unlink(missing_ok=True)
    latest_detail.unlink(missing_ok=True)
    latest.symlink_to(summary_path.name)
    latest_detail.symlink_to(detail_path.name)

    print(f"  [Saved] {len(results)} models → {summary_path.name}")


def main():
    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
    benchmark_results = {}

    for m in MODELS:
        for attempt in range(3):  # Retry up to 3 times per model
            print(f"\n{'=' * 50}")
            print(f" Starting vLLM for {m['name']} (attempt {attempt + 1}/3)...")
            print(f"{'=' * 50}")

            wrapper = Path(__file__).resolve().parent / "vllm_wrapper.py"
            conc = MODEL_CONCURRENT.get(m["name"], CONCURRENT)
            vllm_cmd = [
                "python3",
                str(wrapper),
                "--model",
                m["name"],
                "--port",
                str(PORT),
                "--gpu-memory-utilization",
                "0.87",
                "--max-model-len",
                "4096",
                "--trust-remote-code",
                "--enable-prefix-caching",
                "--max-num-seqs",
                str(conc),
            ]
            vllm_env = os.environ.copy()
            vllm_env["VLLM_USE_V2_MODEL_RUNNER"] = "1"
            log_path = f"experiments/results/vllm_{m['tag']}.log"
            with open(log_path, "w") as log_file:
                proc = subprocess.Popen(
                    vllm_cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=vllm_env,
                )

            if not wait_for_server(proc, timeout_iter=300):
                print(f"Failed to start vLLM for {m['name']}. Attempt {attempt + 1}/3.")
                proc.kill()
                proc.wait(timeout=10)
                cleanup_vllm()
                if attempt < 2:
                    continue  # Retry
                else:
                    break  # Give up after 3 attempts

            try:
                stats = evaluate_model(m["name"], prompt_template, n_trials=1, concurrency=conc)
                if stats:
                    benchmark_results[m["tag"]] = stats
                    print(
                        f"  Overall: {stats['overall_pct']:.1f}% | Morph: {stats['morph_pct']:.1f}% | Ctx: {stats['ctx_pct']:.1f}%"
                    )
                    print(f"  KO: {stats['ko_pct']:.1f}% | EN: {stats['en_pct']:.1f}%")
                    print(
                        f"  TTFT: {stats['avg_ttft_ms']:.0f}ms | TPOT: {stats['avg_tpot_ms']:.1f}ms | {stats['avg_tps']:.1f} tok/s"
                    )
                    print(f"  Retries: {stats['avg_retries']:.1f} | Structured: {stats['structured_rate_pct']:.0f}%")
                    # Incremental save after each model
                    _save_incremental(benchmark_results)
            finally:
                print("Shutting down vLLM...")
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=10)
                cleanup_vllm()
            break  # Success, move to next model

    # Final save
    _save_incremental(benchmark_results)

    # Print summary table
    print(
        f"\n{'Model':<22} | {'Overall':>8} | {'Morph':>6} | {'Ctx':>6} | {'KO':>6} | {'EN':>6} | {'TTFT':>7} | {'TPOT':>7} | {'tok/s':>7} | {'Latency':>8} | {'Retry':>5} | {'Struct':>6}"
    )
    print("-" * 130)
    for tag, s in benchmark_results.items():
        print(
            f"{tag:<22} | {s['overall_pct']:>7.1f}% | {s['morph_pct']:>5.1f}% | {s['ctx_pct']:>5.1f}% | {s['ko_pct']:>5.1f}% | {s['en_pct']:>5.1f}% | {s['avg_ttft_ms']:>6.0f}ms | {s['avg_tpot_ms']:>6.1f}ms | {s['avg_tps']:>6.1f} | {s['avg_latency_s']:>7.2f}s | {s['avg_retries']:>5.1f} | {s['structured_rate_pct']:>5.0f}%"
        )


if __name__ == "__main__":
    main()
