#!/usr/bin/env python3
"""Per-model concurrency sweep to find optimal concurrency level."""

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


def kill_vllm():
    for _ in range(5):
        subprocess.run(["pkill", "-9", "-f", "vllm"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "VLLM"], capture_output=True)
        time.sleep(3)
        r = subprocess.run(["pgrep", "-f", "vllm|VLLM"], capture_output=True, text=True)
        if not r.stdout.strip():
            time.sleep(2)
            return True
    return False


def start_vllm(model):
    kill_vllm()
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
        "--max-num-seqs",
        "32",
    ]
    env = os.environ.copy()
    env["VLLM_USE_V2_MODEL_RUNNER"] = "1"
    with open(f"/tmp/vllm_sweep_{model.split('/')[-1]}.log", "w") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    for _ in range(120):
        time.sleep(2)
        try:
            r = requests.get(f"http://localhost:{PORT}/v1/models", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
    proc.kill()
    kill_vllm()
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
        "conc": conc,
        "n": n,
        "total_s": round(total, 1),
        "avg_lat": round(sum(lats) / len(lats), 2),
        "p50_lat": round(sorted(lats)[len(lats) // 2], 2),
        "p95_lat": round(sorted(lats)[int(len(lats) * 0.95)], 2),
        "acc": round(ok / n * 100, 1),
        "tps": round(n / total, 2),
    }


def sweep_model(model, tag, conc_levels):
    print(f"\n{'=' * 50}")
    print(f"  Sweeping {tag}")
    print(f"{'=' * 50}")
    if not start_vllm(model):
        return {"error": "failed to start"}
    results = []
    for c in conc_levels:
        s = bench(model, c, 20)
        results.append(s)
        print(
            f"  {c:2d}x: total={s['total_s']:5.1f}s, avg_lat={s['avg_lat']:.2f}s, "
            f"p95={s['p95_lat']:.2f}s, tps={s['tps']:.2f}/s, acc={s['acc']}%"
        )
    # Find optimal (max throughput with accuracy >= baseline)
    baseline_acc = next((r["acc"] for r in results if r["conc"] == 1), 0)
    valid = [r for r in results if r["acc"] >= baseline_acc - 5]  # allow 5% margin
    optimal = max(valid, key=lambda r: r["tps"]) if valid else results[0]
    return {"tag": tag, "results": results, "optimal": optimal}


def main():
    CONC_LEVELS = [1, 2, 4, 8, 12, 16, 24, 32]
    MODELS = [
        ("google/gemma-4-E2B-it", "E2B"),
        ("google/gemma-4-E4B-it", "E4B"),
        ("LGAI-EXAONE/EXAONE-4.0-1.2B", "EXAONE-1.2B"),
    ]

    all_results = {}
    for model, tag in MODELS:
        all_results[tag] = sweep_model(model, tag, CONC_LEVELS)

    kill_vllm()

    # Save
    out = Path("experiments/results/concurrency_sweep.json")
    out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"\nSaved: {out}")

    # Summary
    print("\n" + "=" * 60)
    print("OPTIMAL CONCURRENCY PER MODEL")
    print("=" * 60)
    for tag, data in all_results.items():
        if "error" in data:
            print(f"  {tag}: FAILED")
            continue
        opt = data["optimal"]
        print(
            f"  {tag:15s}: conc={opt['conc']:2d}x, throughput={opt['tps']:.2f}/s, "
            f"avg_lat={opt['avg_lat']:.2f}s, accuracy={opt['acc']}%"
        )


if __name__ == "__main__":
    main()
