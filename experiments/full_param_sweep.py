#!/usr/bin/env python3
"""Per-model exhaustive vLLM parameter sweep. gpu=1.0 fixed."""

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
    with open(f"/tmp/vllm_full_{tag}_{max_model_len}_{max_seqs}.log", "w") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    for _ in range(300):  # 10 min timeout
        time.sleep(2)
        if _ % 30 == 0:
            print(f"    waiting for vLLM... ({_ * 2}s)")
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


# ── Model configs: (model_id, tag, max_model_len options, max_num_seqs options) ──
MODEL_CONFIGS = [
    ("google/gemma-4-E2B-it", "E2B", [4096], [16, 32, 48, 64]),
    ("google/gemma-4-E4B-it", "E4B", [4096], [16, 24, 32, 48]),
    ("LGAI-EXAONE/EXAONE-4.0-1.2B", "EXAONE", [4096], [16, 32, 48, 64]),
]

all_results = {}

for model, tag, len_opts, seq_opts in MODEL_CONFIGS:
    print(f"\n{'=' * 60}")
    print(f"  {tag} — gpu=1.0, exhaustive sweep")
    print(f"  lens={len_opts}, seqs={seq_opts}")
    print(f"{'=' * 60}")

    results = []
    baseline_acc = None

    for ml in len_opts:
        for ms in seq_opts:
            label = f"len={ml}_seqs={ms}"
            print(f"\n  [{label}]")
            if not start_vllm(model, ml, ms):
                results.append({"label": label, "len": ml, "seqs": ms, "error": "failed"})
                print("    FAILED (OOM?)")
                continue
            s = bench(model, conc=ms, n=20)
            s.update({"label": label, "len": ml, "seqs": ms})
            results.append(s)
            if baseline_acc is None:
                baseline_acc = s["acc"]
            ok = "✓" if s["acc"] >= baseline_acc - 5 else "⚠"
            print(
                f"    {ok} acc={s['acc']}%, tps={s['tps']}/s, lat={s['avg_lat']}s, total={s['total_s']}s, errs={s['errors']}"
            )

    all_results[tag] = {"results": results, "baseline_acc": baseline_acc}

    # Find best
    valid = [r for r in results if "error" not in r and r["acc"] >= baseline_acc - 5]
    if valid:
        best = max(valid, key=lambda r: r["tps"])
        print(f"\n  BEST {tag}: {best['label']} → tps={best['tps']}/s, acc={best['acc']}%, lat={best['avg_lat']}s")

kill_vllm()

# Save
out = Path("experiments/results/full_param_sweep.json")
out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
print(f"\nSaved: {out}")

# Summary
print("\n" + "=" * 70)
print("OPTIMAL CONFIGS (gpu=1.0)")
print("=" * 70)
for tag, data in all_results.items():
    valid = [r for r in data["results"] if "error" not in r and r["acc"] >= data["baseline_acc"] - 5]
    if valid:
        best = max(valid, key=lambda r: r["tps"])
        print(
            f"  {tag:10s}: len={best['len']}, seqs={best['seqs']}, tps={best['tps']}/s, acc={best['acc']}%, lat={best['avg_lat']}s"
        )
    else:
        print(f"  {tag:10s}: ALL FAILED")
