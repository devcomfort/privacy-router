#!/usr/bin/env python3
"""Unified benchmark: our benchmark_v2 + LegalCiteBench on all models.
gpu_utilization=0.48 (40% free), max_num_seqs=16-32."""

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

GPU_UTIL = 0.48
MAX_LEN = 4096
PORT = 8000

MODELS = [
    ("google/gemma-4-E2B-it", "E2B", 32, True),
    ("google/gemma-4-E4B-it", "E4B", 24, True),
    ("google/gemma-4-12B-it", "Gemma-12B", 16, True),
    ("google/gemma-4-26B-A4B-it", "Gemma-26B", 16, True),
    ("LGAI-EXAONE/EXAONE-4.0-1.2B", "EXAONE-1.2B", 32, True),
    ("ibm-granite/granite-4.1-8b", "Granite-8B", 16, True),
    ("Qwen/Qwen3-4B", "Qwen3-4B", 16, False),
    ("Qwen/Qwen3.5-9B", "Qwen3.5-9B", 16, False),
]

# ── Load datasets ──
OUR_BENCH = json.loads(Path("experiments/datasets/benchmark_v2.json").read_text())["cases"]
PROMPT = Path("experiments/prompt_variants/extract.fewshot_v3.prompt").read_text()

LEGAL_DIR = Path("experiments/benchmarks/LegalCiteBench/legal-citation-benchmark-clean/data")
LEGAL_FILES = [
    "cat1/cat1_citation_retrieval.jsonl",
    "cat2/cat2_citation_completeness.jsonl",
    "cat3/cat3_citation_verification.jsonl",
    "cat4/cat4-1_case_matching.jsonl",
    "cat4/cat4-2_case_verification.jsonl",
]
LEGAL = {}
for rel_path in LEGAL_FILES:
    fpath = LEGAL_DIR / rel_path
    if fpath.exists():
        cat_name = fpath.stem
        with open(fpath) as f:
            cases = [json.loads(line) for line in f]
        LEGAL[cat_name] = cases[:50]

# LegalCiteBench system prompts (from official repo)
SYSTEM_PROMPT_CITATION = """You are a legal research expert.
When asked a question, provide the relevant case citations or legal authorities directly.
Be direct and concise. Only list the citations or cases asked for."""

SYSTEM_PROMPT_VERIFY = """You are a legal research expert.
When asked whether a citation or case reference is correct:
- If it IS correct: Answer "Yes".
- If it is NOT correct: Answer "No", then provide the correct citation or case.
Be direct and concise."""

CITATION_QA_STYLES = {"1", "2", "4-1"}


def get_legal_system_prompt(qa_style):
    if str(qa_style) in CITATION_QA_STYLES:
        return SYSTEM_PROMPT_CITATION
    return SYSTEM_PROMPT_VERIFY


def kill_vllm():
    for _ in range(3):
        subprocess.run(["pkill", "-9", "-f", "vllm.entrypoints"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "VLLM::EngineCore"], capture_output=True)
        time.sleep(2)


def start_vllm(model, seqs, use_v2=True):
    kill_vllm()
    cmd = [
        sys.executable,
        str(Path("experiments/vllm_wrapper.py")),
        "--model",
        model,
        "--port",
        str(PORT),
        "--gpu-memory-utilization",
        str(GPU_UTIL),
        "--max-model-len",
        str(MAX_LEN),
        "--trust-remote-code",
        "--enable-prefix-caching",
        "--max-num-seqs",
        str(seqs),
    ]
    env = os.environ.copy()
    env["PATH"] = str(Path(".venv/bin").resolve()) + ":" + env.get("PATH", "")
    if use_v2:
        env["VLLM_USE_V2_MODEL_RUNNER"] = "1"
    else:
        env.pop("VLLM_USE_V2_MODEL_RUNNER", None)
    tag = model.split("/")[-1]
    with open(f"/tmp/vllm_bench_{tag}_{seqs}.log", "w") as logf:
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


def extract_json(content):
    stripped = content.strip()
    stripped = re.sub(r"<think>.*?</think>\s*", "", stripped, flags=re.DOTALL).strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if m:
        stripped = m.group(1)
    elif not stripped.startswith("{"):
        m = re.search(r"\{.*\}", stripped, re.DOTALL)
        if m:
            stripped = m.group(0)
    return json.loads(stripped)


def run_our_bench(model, conc, n=120):
    """Our benchmark_v2: PII detection. Uses detection_type for morph/ctx."""
    cases = OUR_BENCH[:n]
    t0 = time.time()

    def run_case(case):
        rendered = PROMPT.replace("{{text}}", case["text"])
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
            if r.status_code != 200:
                return None, False
            content = r.json()["choices"][0]["message"]["content"]
            ext = extract_json(content)

            j = Judge().classify(
                sensitivity=ext.get("sensitivity", {}), records=ext.get("records", []), text=case["text"]
            )
            action = j.policy_action  # Judge now outputs allow/block/selective_mask directly
            return action, True
        except Exception:
            return None, False

    with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = [ex.submit(run_case, c) for c in cases]
        results = [f.result() for f in futs]

    total = time.time() - t0
    ok = sum(1 for i, c in enumerate(cases) if results[i][0] == c["expected_action"])
    errs = sum(1 for r in results if not r[1])

    # FIX: use detection_type, not sensitivity_type
    morph_cases = [i for i, c in enumerate(cases) if c.get("detection_type") == "morphological"]
    ctx_cases = [i for i, c in enumerate(cases) if c.get("detection_type") == "contextual"]
    morph_ok = sum(1 for i in morph_cases if results[i][0] == cases[i]["expected_action"])
    ctx_ok = sum(1 for i in ctx_cases if results[i][0] == cases[i]["expected_action"])

    return {
        "overall": round(ok / len(cases) * 100, 1),
        "morphological": round(morph_ok / len(morph_cases) * 100, 1) if morph_cases else 0,
        "contextual": round(ctx_ok / len(ctx_cases) * 100, 1) if ctx_cases else 0,
        "errors": errs,
        "tps": round(len(cases) / total, 2),
        "total_s": round(total, 1),
    }


def run_legal_bench(model, conc):
    """LegalCiteBench with proper system prompts and scoring."""
    results = {}

    for cat_name, cases in LEGAL.items():
        t0 = time.time()

        def run_case(case):
            qa_style = str(case.get("qa_style", ""))
            system_prompt = get_legal_system_prompt(qa_style)
            try:
                r = requests.post(
                    f"http://localhost:{PORT}/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": case["question"]},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 512,
                    },
                    timeout=60,
                )
                if r.status_code != 200:
                    return None, False
                return r.json()["choices"][0]["message"]["content"], True
            except Exception:
                return None, False

        with ThreadPoolExecutor(max_workers=conc) as ex:
            futs = [ex.submit(run_case, c) for c in cases]
            responses = [f.result() for f in futs]

        total = time.time() - t0
        ok = sum(1 for r in responses if r[1])

        # Scoring: qa_style-based (matching official eval)
        scores = []
        for i, (resp, success) in enumerate(responses):
            if not success:
                scores.append(0)
                continue
            gt = cases[i]["ground_truth"]
            qa = str(cases[i].get("qa_style", ""))

            if qa in ("1", "2"):
                # Citation retrieval/completion: substring match
                if isinstance(gt, list):
                    hit = any(str(g).lower() in resp.lower() for g in gt[:3])
                else:
                    hit = str(gt).lower() in resp.lower()
                scores.append(5 if hit else 0)
            elif qa == "3-fake":
                # Citation verification: detect error + correct
                gt_str = str(gt).lower()
                detected = "incorrect" in resp.lower() or "error" in resp.lower() or "wrong" in resp.lower()
                corrected = gt_str in resp.lower()
                scores.append(5 if detected and corrected else 2 if detected else 0)
            elif qa == "3-true":
                # Citation verification: confirm no error
                confirmed = "yes" in resp.lower()[:20] or "correct" in resp.lower() or "no error" in resp.lower()
                scores.append(5 if confirmed else 0)
            elif qa == "4-1":
                # Case matching
                if isinstance(gt, dict):
                    hit = any(str(v).lower() in resp.lower() for v in gt.values() if v)
                else:
                    hit = str(gt).lower() in resp.lower()
                scores.append(5 if hit else 0)
            elif qa == "4-2-true":
                confirmed = "yes" in resp.lower()[:20] or "correct" in resp.lower()
                scores.append(5 if confirmed else 0)
            elif qa == "4-2-fake":
                rejected = "no" in resp.lower()[:20] or "incorrect" in resp.lower() or "wrong" in resp.lower()
                gt_str = str(gt).lower() if not isinstance(gt, list) else str(gt[0]).lower() if gt else ""
                corrected = gt_str in resp.lower()
                scores.append(5 if rejected and corrected else 2 if rejected else 0)
            else:
                scores.append(0)

        avg_score = sum(scores) / len(scores) if scores else 0
        max_score = 5
        results[cat_name] = {
            "score_normalized": round(avg_score / max_score * 100, 1),
            "avg_score": round(avg_score, 2),
            "success_rate": round(ok / len(cases) * 100, 1),
            "tps": round(len(cases) / total, 2),
        }

    return results


all_results = {}

for model_id, tag, seqs, use_v2 in MODELS:
    runner = "V2" if use_v2 else "V1"
    print(f"\n{'=' * 60}")
    print(f"  {tag} ({model_id}) — gpu={GPU_UTIL}, seqs={seqs}, runner={runner}")
    print(f"{'=' * 60}")

    if not start_vllm(model_id, seqs, use_v2=use_v2):
        all_results[tag] = {"error": "failed_to_start"}
        print("  FAILED to start")
        continue

    print("  Running our benchmark (120 cases)...")
    our = run_our_bench(model_id, conc=seqs, n=120)
    print(f"    overall={our['overall']}%, morph={our['morphological']}%, ctx={our['contextual']}%, tps={our['tps']}/s")

    print(f"  Running LegalCiteBench ({sum(len(v) for v in LEGAL.values())} cases)...")
    legal = run_legal_bench(model_id, conc=seqs)
    for cat, res in legal.items():
        print(f"    {cat}: score={res['score_normalized']}%, avg={res['avg_score']}")

    all_results[tag] = {
        "model_id": model_id,
        "seqs": seqs,
        "gpu_util": GPU_UTIL,
        "our_benchmark": our,
        "legal_bench": legal,
    }

    Path("experiments/results/unified_benchmark.json").write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"  Saved {tag}")

kill_vllm()

# Final summary
print(f"\n{'=' * 90}")
print(f"UNIFIED BENCHMARK RESULTS (gpu={GPU_UTIL}, max_len={MAX_LEN})")
print(f"{'=' * 90}")
print(f"{'Tag':15s} {'Seqs':>5s} {'Overall':>8s} {'Morph':>7s} {'Ctx':>6s} {'TPS':>6s} {'Legal(avg)':>10s}")
print("-" * 80)
for tag, data in all_results.items():
    if "error" in data:
        print(f"{tag:15s}    —       —       —      —      — ✗ ({data['error']})")
        continue
    our = data["our_benchmark"]
    legal = data.get("legal_bench", {})
    legal_avg = round(sum(r["score_normalized"] for r in legal.values()) / len(legal), 1) if legal else 0
    print(
        f"{tag:15s} {data['seqs']:>5d} {our['overall']:>7.1f}% {our['morphological']:>6.1f}% {our['contextual']:>5.1f}% {our['tps']:>5.2f}/s {legal_avg:>9.1f}%"
    )

print("\nSaved: experiments/results/unified_benchmark.json")
