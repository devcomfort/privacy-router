#!/usr/bin/env python3
"""Per-model vLLM parameter sweep for throughput optimization."""

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
    """Kill running vLLM processes (ignores zombies)."""
    for _ in range(3):
        subprocess.run(["pkill", "-9", "-f", "vllm.entrypoints"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "VLLM::EngineCore"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "vllm_wrapper"], capture_output=True)
        time.sleep(3)
        r = subprocess.run(["ps", "-eo", "pid,stat,cmd"], capture_output=True, text=True)
        alive = [
            line
            for line in r.stdout.split("\n")
            if ("vllm" in line.lower() or "VLLM" in line) and len(line.split()) > 1 and "Z" not in line.split()[1]
        ]
        if not alive:
            time.sleep(2)
            return


def start_vllm(model, gpu_util, max_model_len, max_seqs):
    kill_vllm()
    cmd = [
        sys.executable,
        str(Path("experiments/vllm_wrapper.py")),
        "--model",
        model,
        "--port",
        str(PORT),
        "--gpu-memory-utilization",
        str(gpu_util),
        "--max-model-len",
        str(max_model_len),
        "--trust-remote-code",
        "--enable-prefix-caching",
        "--max-num-seqs",
        str(max_seqs),
    ]
    env = os.environ.copy()
    env["VLLM_USE_V2_MODEL_RUNNER"] = "1"
    tag = model.split("/")[-1]
    with open(f"/tmp/vllm_psweep_{tag}_{gpu_util}_{max_model_len}_{max_seqs}.log", "w") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    for _ in range(120):
        time.sleep(2)
        try:
            r = requests.get(f"http://localhost:{PORT}/v1/models", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
    print(f"    FAILED: {model} gpu={gpu_util} len={max_model_len} seqs={max_seqs}")
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
    with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = [ex.submit(run_case, c, model) for c in cases]
        results = [f.result() for f in futs]
    total = time.time() - t0
    lats = [r[1] for r in results]
    ok = sum(1 for i, c in enumerate(cases) if results[i][0] == c["expected_action"])
    errs = sum(1 for r in results if not r[2])
    return {
        "total_s": round(total, 1),
        "avg_lat": round(sum(lats) / len(lats), 2),
        "acc": round(ok / n * 100, 1),
        "tps": round(n / total, 2),
        "errors": errs,
    }


def sweep_model(model, tag):
    print(f"\n{'=' * 60}")
    print(f"  Parameter sweep: {tag}")
    print(f"{'=' * 60}")

    configs = [
        (0.65, 4096, 16, "baseline"),
        (0.65, 4096, 24, "seqs=24"),
        (0.65, 4096, 32, "seqs=32"),
        (0.75, 4096, 16, "gpu=0.75"),
        (0.75, 4096, 24, "gpu=0.75+seqs=24"),
        (0.75, 4096, 32, "gpu=0.75+seqs=32"),
        (0.85, 4096, 16, "gpu=0.85"),
        (0.85, 4096, 24, "gpu=0.85+seqs=24"),
        (0.85, 4096, 32, "gpu=0.85+seqs=32"),
        (0.65, 2048, 16, "len=2048"),
        (0.65, 2048, 24, "len=2048+seqs=24"),
        (0.75, 2048, 24, "len=2048+gpu=0.75+seqs=24"),
        (0.85, 2048, 32, "len=2048+gpu=0.85+seqs=32"),
    ]

    results = []
    baseline_acc = None

    for gpu_util, max_len, max_seqs, label in configs:
        print(f"\n  [{label}] gpu={gpu_util}, len={max_len}, seqs={max_seqs}")
        if not start_vllm(model, gpu_util, max_len, max_seqs):
            results.append({"label": label, "gpu": gpu_util, "len": max_len, "seqs": max_seqs, "error": "failed"})
            continue
        s = bench(model, conc=max_seqs, n=20)
        s.update({"label": label, "gpu": gpu_util, "len": max_len, "seqs": max_seqs})
        results.append(s)
        if baseline_acc is None:
            baseline_acc = s["acc"]
        acc_ok = "✓" if s["acc"] >= baseline_acc - 5 else "⚠"
        print(f"    {acc_ok} acc={s['acc']}%, tps={s['tps']}/s, lat={s['avg_lat']}s, total={s['total_s']}s")

    kill_vllm()
    return results, baseline_acc


def main():
    all_results = {}
    for model, tag in [("google/gemma-4-E2B-it", "E2B"), ("google/gemma-4-E4B-it", "E4B")]:
        results, baseline_acc = sweep_model(model, tag)
        all_results[tag] = {"results": results, "baseline_acc": baseline_acc}
        valid = [r for r in results if "error" not in r and r["acc"] >= baseline_acc - 5]
        if valid:
            best = max(valid, key=lambda r: r["tps"])
            print(f"\n  BEST {tag}: {best['label']} → tps={best['tps']}/s, acc={best['acc']}%, lat={best['avg_lat']}s")

    Path("experiments/results/vllm_param_sweep.json").write_text(json.dumps(all_results, indent=2))
    print("\nSaved: experiments/results/vllm_param_sweep.json")

    print("\n" + "=" * 70)
    print("BEST CONFIG PER MODEL")
    print("=" * 70)
    for tag, data in all_results.items():
        valid = [r for r in data["results"] if "error" not in r and r["acc"] >= data["baseline_acc"] - 5]
        if valid:
            best = max(valid, key=lambda r: r["tps"])
            print(
                f"  {tag:10s}: gpu={best['gpu']}, len={best['len']}, seqs={best['seqs']}, "
                f"tps={best['tps']}/s, acc={best['acc']}%, lat={best['avg_lat']}s"
            )


if __name__ == "__main__":
    main()
