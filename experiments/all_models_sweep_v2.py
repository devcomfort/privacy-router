#!/usr/bin/env python3
"""Continue sweep: remaining models. Qwen=V1 runner, others=V2."""

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

# Remaining models: Qwen (V1 runner), Granite, Ministral, Qwen3-4B, Qwen3.6-MoE
MODELS = [
    # (repo_id, tag, disk_gib, [seqs], use_v2_runner)
    ("Qwen/Qwen3.5-9B", "Qwen3.5-9B", 18.0, [8, 12, 16, 24], False),
    ("Qwen/Qwen3-4B", "Qwen3-4B", 7.5, [16, 24, 32, 48], False),
    ("google/gemma-4-12B-it", "Gemma-12B", 22.3, [8, 12, 16, 24], True),
    ("LGAI-EXAONE/EXAONE-4.0-1.2B", "EXAONE-1.2B", 2.4, [16, 32, 48, 64], True),
    ("ibm-granite/granite-4.1-8b", "Granite-8B", 16.4, [8, 12, 16, 24], True),
    ("mistralai/Ministral-3-3B-Instruct-2512", "Ministral-3B", 8.7, [16, 24, 32, 48], True),
]

# Load partial results
partial_file = Path("experiments/results/all_models_sweep_partial.json")
all_results = json.loads(partial_file.read_text()) if partial_file.exists() else {}


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


def start_vllm(model, max_model_len, max_seqs, use_v2=True):
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
    env["PATH"] = str(Path(".venv/bin").resolve()) + ":" + env.get("PATH", "")
    if use_v2:
        env["VLLM_USE_V2_MODEL_RUNNER"] = "1"
    else:
        env.pop("VLLM_USE_V2_MODEL_RUNNER", None)
    tag = model.split("/")[-1]
    with open(f"/tmp/vllm_sweep2_{tag}_{max_seqs}.log", "w") as logf:
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


for model_id, tag, disk_gib, seqs_list, use_v2 in MODELS:
    if tag in all_results:
        prev = all_results[tag].get("results", [])
        all_clean = all("error" not in r and r.get("errors", 99) == 0 for r in prev)
        if all_clean and len(prev) >= len(seqs_list):
            print(f"\n  Skipping {tag} (already completed with valid results)")
            continue
        else:
            print(f"\n  Re-running {tag} (previous had errors)")
            all_results.pop(tag, None)

    runner = "V2" if use_v2 else "V1"
    print(f"\n{'=' * 60}")
    print(f"  {tag} ({model_id}) — {disk_gib:.1f} GiB, runner={runner}")
    print(f"  seqs: {seqs_list}")
    print(f"{'=' * 60}")

    results = []
    baseline_acc = None

    for seqs in seqs_list:
        label = f"seqs={seqs}"
        print(f"\n  [{label}]")
        if not start_vllm(model_id, 4096, seqs, use_v2=use_v2):
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

    # Incremental save
    partial_file.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"\n  Saved {tag} results incrementally")

    valid = [
        r for r in results if "error" not in r and r.get("errors", 99) == 0 and r["acc"] >= (baseline_acc or 0) - 5
    ]
    if valid:
        best = max(valid, key=lambda r: r["tps"])
        print(f"  BEST {tag}: seqs={best['seqs']} → tps={best['tps']}/s, acc={best['acc']}%")
    else:
        print(f"  {tag}: NO VALID CONFIG")

kill_vllm()

# Final save
out = Path("experiments/results/all_models_sweep.json")
out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
print(f"\nSaved: {out}")

# Summary
print("\n" + "=" * 80)
print("ALL MODELS SUMMARY (gpu=0.87, max_model_len=4096)")
print("=" * 80)
print(f"{'Tag':20s} {'Disk':>6s} {'Seqs':>5s} {'TPS':>7s} {'Acc':>6s} {'Lat':>6s} {'Status'}")
print("-" * 80)
for tag, data in all_results.items():
    valid = [
        r
        for r in data["results"]
        if "error" not in r and r.get("errors", 99) == 0 and r["acc"] >= (data.get("baseline_acc") or 0) - 5
    ]
    if valid:
        best = max(valid, key=lambda r: r["tps"])
        print(
            f"{tag:20s} {data['disk_gib']:5.1f}G {best['seqs']:>5d} {best['tps']:>6.2f}/s {best['acc']:>5.1f}% {best['avg_lat']:>5.1f}s ✓"
        )
    else:
        errors = [r for r in data["results"] if "error" in r]
        reason = errors[0]["error"] if errors else "acc drop"
        print(f"{tag:20s} {data['disk_gib']:5.1f}G    —       —      —      — ✗ ({reason})")
