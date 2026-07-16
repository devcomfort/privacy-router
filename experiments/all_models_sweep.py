#!/usr/bin/env python3
"""Full sweep: 10 vLLM-compatible models × seqs grid. gpu=0.87, len=4096."""

import json
import os
import re
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

# All 10 vLLM-compatible models × seqs grid
MODELS = [
    # (repo_id, tag, disk_gib, [seqs_to_test])
    ("google/gemma-4-E2B-it", "E2B", 9.6, [16, 32, 48, 64]),
    ("google/gemma-4-E4B-it", "E4B", 14.9, [16, 24, 32, 48]),
    ("google/gemma-4-12B-it", "Gemma-12B", 22.3, [8, 12, 16, 24]),
    ("google/gemma-4-26B-A4B-it", "Gemma-26B", 48.1, [4, 8, 12, 16]),
    ("LGAI-EXAONE/EXAONE-4.0-1.2B", "EXAONE-1.2B", 2.4, [16, 32, 48, 64]),
    ("Qwen/Qwen3.5-9B", "Qwen3.5-9B", 18.0, [8, 12, 16, 24]),
    ("Qwen/Qwen3-4B", "Qwen3-4B", 7.5, [16, 24, 32, 48]),
    ("Qwen/Qwen3.6-35B-A3B", "Qwen3.6-MoE", 2.2, [8, 12, 16, 24]),
    ("ibm-granite/granite-4.1-8b", "Granite-8B", 16.4, [8, 12, 16, 24]),
    ("mistralai/Ministral-3-3B-Instruct-2512", "Ministral-3B", 8.7, [16, 24, 32, 48]),
]


def kill_vllm():
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


def start_vllm(model, max_model_len, max_seqs):
    kill_vllm()
    cmd = [
        sys.executable,
        str(Path("experiments/vllm_wrapper.py")),
        "--model",
        model,
        "--port",
        str(PORT),
        "--gpu-memory-utilization",
        "0.87",
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
    with open(f"/tmp/vllm_sweep_{tag}_{max_seqs}.log", "w") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    for _ in range(300):
        time.sleep(2)
        if _ % 30 == 0:
            print(f"    waiting... ({_ * 2}s)")
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
                "max_tokens": 1024,
            },
            timeout=120,
        )
        lat = time.time() - t0
        if r.status_code != 200:
            return "ERROR", lat, False
        content = r.json()["choices"][0]["message"]["content"]
        # Robust JSON extraction: handle reasoning blocks, code fences, bare JSON
        stripped = content.strip()
        # 1. Remove <think>...</think> blocks (Qwen reasoning)
        stripped = re.sub(r"<think>.*?</think>\s*", "", stripped, flags=re.DOTALL).strip()
        # 2. Extract from ```json ... ``` code block
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
        if m:
            stripped = m.group(1)
        elif not stripped.startswith("{"):
            # 3. Find first bare JSON object
            m = re.search(r"\{.*\}", stripped, re.DOTALL)
            if m:
                stripped = m.group(0)

        ext = json.loads(stripped)
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


all_results = {}

for model_id, tag, disk_gib, seqs_list in MODELS:
    print(f"\n{'=' * 60}")
    print(f"  {tag} ({model_id}) — {disk_gib:.1f} GiB")
    print(f"  seqs: {seqs_list}")
    print(f"{'=' * 60}")

    results = []
    baseline_acc = None

    for seqs in seqs_list:
        label = f"seqs={seqs}"
        print(f"\n  [{label}]")
        if not start_vllm(model_id, 4096, seqs):
            results.append({"label": label, "seqs": seqs, "error": "failed"})
            print("    FAILED")
            continue
        s = bench(model_id, conc=seqs, n=20)
        s.update({"label": label, "seqs": seqs})
        results.append(s)
        if baseline_acc is None:
            baseline_acc = s["acc"]
        ok = "✓" if s["acc"] >= baseline_acc - 5 else "⚠"
        print(f"    {ok} acc={s['acc']}%, tps={s['tps']}/s, lat={s['avg_lat']}s, errs={s['errors']}")

    all_results[tag] = {"model_id": model_id, "disk_gib": disk_gib, "results": results, "baseline_acc": baseline_acc}

    valid = [r for r in results if "error" not in r and r["acc"] >= (baseline_acc or 0) - 5]
    if valid:
        best = max(valid, key=lambda r: r["tps"])
        print(f"\n  BEST {tag}: seqs={best['seqs']} → tps={best['tps']}/s, acc={best['acc']}%")
    else:
        print(f"\n  {tag}: NO VALID CONFIG")

kill_vllm()

# Save
out = Path("experiments/results/all_models_sweep.json")
out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
print(f"\nSaved: {out}")

# Summary table
print("\n" + "=" * 80)
print("ALL MODELS SUMMARY (gpu=0.87, max_model_len=4096, N=20)")
print("=" * 80)
print(f"{'Tag':20s} {'Disk':>6s} {'Seqs':>5s} {'TPS':>7s} {'Acc':>6s} {'Lat':>6s} {'Status'}")
print("-" * 80)
for tag, data in all_results.items():
    valid = [r for r in data["results"] if "error" not in r and r["acc"] >= (data["baseline_acc"] or 0) - 5]
    if valid:
        best = max(valid, key=lambda r: r["tps"])
        print(
            f"{tag:20s} {data['disk_gib']:5.1f}G {best['seqs']:>5d} {best['tps']:>6.2f}/s {best['acc']:>5.1f}% {best['avg_lat']:>5.1f}s ✓"
        )
    else:
        err = data["results"][0] if data["results"] else {}
        reason = err.get("error", "acc drop")
        print(f"{tag:20s} {data['disk_gib']:5.1f}G    —       —      —      — ✗ ({reason})")
