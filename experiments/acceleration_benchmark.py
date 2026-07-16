#!/usr/bin/env python3
"""vLLM acceleration benchmark: ngram accuracy, concurrent scaling, model comparison."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["HF_HUB_OFFLINE"] = "1"
from agents import Judge  # noqa: E402

PROMPT = Path("experiments/prompt_variants/extract.fewshot_v3.prompt").read_text()
DATA = json.loads(Path("experiments/datasets/benchmark_v2.json").read_text())["cases"][:20]
PORT = 8000


def kill_and_wait():
    """Kill all vLLM and wait for GPU to free."""
    for _ in range(5):
        subprocess.run(["pkill", "-9", "-f", "vllm"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "VLLM"], capture_output=True)
        time.sleep(3)
        r = subprocess.run(["pgrep", "-f", "vllm|VLLM"], capture_output=True, text=True)
        if not r.stdout.strip():
            time.sleep(2)
            return True
    return False


def start_vllm(model, extra_args=None, mrv2=False):
    """Start vLLM, wait for ready, return True/False."""
    kill_and_wait()
    cmd = [
        sys.executable,
        str(Path("experiments/vllm_wrapper.py")),
        "--model",
        model,
        "--port",
        str(PORT),
        "--gpu-memory-utilization",
        "0.65",
        "--max-model-len",
        "4096",
        "--trust-remote-code",
        "--enable-prefix-caching",
    ]
    if extra_args:
        cmd.extend(extra_args)
    env = os.environ.copy()
    if mrv2:
        env["VLLM_USE_V2_MODEL_RUNNER"] = "1"
    tag = model.split("/")[-1]
    with open(f"/tmp/vllm_bench_{tag}.log", "w") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    for _ in range(120):
        time.sleep(2)
        try:
            r = requests.get(f"http://localhost:{PORT}/v1/models", timeout=2)
            if r.status_code == 200:
                print(f"    vLLM ready ({model})")
                return True
        except Exception:
            pass
    print(f"    FAILED: {model}")
    proc.kill()
    kill_and_wait()
    return False


def run_case(case, model):
    rendered = PROMPT.replace("{{text}}", case["text"])
    t0 = time.time()
    try:
        r = requests.post(
            f"http://localhost:{PORT}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": rendered}],
                "temperature": 0.0,
                "max_tokens": 512,
            },
            timeout=60,
        )
        lat = time.time() - t0
        if r.status_code != 200:
            return "ERROR", lat, False
        content = r.json()["choices"][0]["message"]["content"]

        ext = json.loads(content)
        j = Judge().classify(sensitivity=ext.get("sensitivity", {}), records=ext.get("records", []), text=case["text"])
        # Judge now outputs allow/block/selective_mask directly
        return j.policy_action, lat, True
    except Exception:
        return "ERROR", time.time() - t0, False


def bench(model, conc, n=20):
    cases = DATA[:n]
    t0 = time.time()
    if conc == 1:
        results = [run_case(c, model) for c in cases]
    else:
        with ThreadPoolExecutor(max_workers=conc) as ex:
            futs = [ex.submit(run_case, c, model) for c in cases]
            results = [f.result() for f in futs]
    total = time.time() - t0
    lats = [r[1] for r in results]
    ok = sum(1 for i, c in enumerate(cases) if results[i][0] == c["expected_action"])
    return {
        "concurrency": conc,
        "n": n,
        "total_s": round(total, 1),
        "avg_lat": round(sum(lats) / len(lats), 2),
        "accuracy": round(ok / n * 100, 1),
        "throughput": round(n / total, 2),
    }


def main():
    R = {}
    m = "google/gemma-4-E4B-it"

    # TEST 1: ngram accuracy
    print("=" * 60)
    print("TEST 1: ngram speculative accuracy (20 cases)")
    print("=" * 60)

    print("\n  [1a] MRv2 + prefix-cache (no ngram)...")
    start_vllm(m, mrv2=True)
    R["no_ngram"] = bench(m, 1, 20)
    print(f"    Accuracy: {R['no_ngram']['accuracy']}%, Latency: {R['no_ngram']['avg_lat']}s")

    print("  [1b] ngram speculative (no MRv2)...")
    start_vllm(
        m,
        extra_args=[
            "--speculative-config",
            json.dumps({"method": "ngram", "prompt_lookup_max": 32, "num_speculative_tokens": 5}),
        ],
    )
    R["with_ngram"] = bench(m, 1, 20)
    print(f"    Accuracy: {R['with_ngram']['accuracy']}%, Latency: {R['with_ngram']['avg_lat']}s")

    # TEST 2: Concurrent scaling
    print("\n" + "=" * 60)
    print("TEST 2: Concurrent scaling (MRv2)")
    print("=" * 60)

    start_vllm(m, mrv2=True)
    for c in [1, 4, 8, 16]:
        print(f"\n  Concurrency={c}...")
        R[f"conc_{c}"] = bench(m, c, 20)
        s = R[f"conc_{c}"]
        print(
            f"    Total: {s['total_s']}s, Avg: {s['avg_lat']}s, Throughput: {s['throughput']}/s, Accuracy: {s['accuracy']}%"
        )

    # TEST 3: Model comparison
    print("\n" + "=" * 60)
    print("TEST 3: Model comparison (concurrent=4, MRv2)")
    print("=" * 60)

    for mn, tag in [
        ("google/gemma-4-E2B-it", "E2B"),
        ("google/gemma-4-E4B-it", "E4B"),
        ("LGAI-EXAONE/EXAONE-4.0-1.2B", "EXAONE"),
    ]:
        print(f"\n  {tag}...")
        if start_vllm(mn, mrv2=True):
            R[f"model_{tag}"] = bench(mn, 4, 20)
            s = R[f"model_{tag}"]
            print(f"    Accuracy: {s['accuracy']}%, Latency: {s['avg_lat']}s, Throughput: {s['throughput']}/s")

    kill_and_wait()

    # Save
    Path("experiments/results/acceleration_benchmark.json").write_text(json.dumps(R, indent=2))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print("\n1. ngram speculative:")
    n = R.get("no_ngram", {})
    w = R.get("with_ngram", {})
    print(f"   Without: {n.get('accuracy', '?')}% acc, {n.get('avg_lat', '?')}s lat")
    print(f"   With:    {w.get('accuracy', '?')}% acc, {w.get('avg_lat', '?')}s lat")
    if n and w:
        print(f"   Delta:   {w['accuracy'] - n['accuracy']:+.1f}% acc, {w['avg_lat'] - n['avg_lat']:+.2f}s lat")

    print("\n2. Concurrent scaling:")
    for c in [1, 4, 8, 16]:
        s = R.get(f"conc_{c}", {})
        print(f"   {c:2d}x: {s.get('total_s', '?')}s, {s.get('throughput', '?')}/s, {s.get('accuracy', '?')}% acc")

    print("\n3. Model comparison:")
    for _, tag in [("", "E2B"), ("", "E4B"), ("", "EXAONE")]:
        s = R.get(f"model_{tag}", {})
        if s and "accuracy" in s:
            print(f"   {tag:10s}: {s['accuracy']}% acc, {s['avg_lat']}s lat, {s['throughput']}/s")


if __name__ == "__main__":
    main()
