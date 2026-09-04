# Gemma 4 26B A4B — decision 모델 리포트

**모델**: `google/gemma-4-26B-A4B-it` (bf16, MoE 활성 4B, 가중치 48.07 GiB)
**역할**: Privacy Router Extractor/Judge decision 모델(프로덕션 기준선)
**측정**: GB10 단일 GPU, vLLM 0.25.1, `temperature=0`, `--max-model-len 16384`
**평가**: `detector-bench` 10케이스 / 기대 스팬 19개 재현율

## 결과 요약

| 설정 | decode | 추출 지연 | 정확도(hits/19) | 벤치 런 |
|---|---:|---:|---:|---|
| `--enforce-eager` + KV 4G | 21.9 tok/s | 10.25 s | 18/19 | `detector-bench/20260903-194907.md` |
| CUDA graph 허용 (baseline) | 23.8 tok/s | 9.53 s | 18/19 | `detector-bench/20260903-200218.md` |
| CUDA graph (재현) | 23.8 tok/s | 9.53 s | 18/19 | `detector-bench/20260903-202620.md` |
| CUDA graph + 공식 MTP assistant + V2 runner | **48.4 tok/s** | **5.43 s** | 18/19 | `detector-bench/20260904-000126.md` |

정확도는 4개 설정 모두 18/19로 동일. 유일한 실패는 `ko-research`의 기관명 `광주과학기술원` 누락이며 전 설정 공통(모델 고유의 사전 한계). 안전 쿼리 2개에서 오탐 없음.

## 메모리 소모

| 항목 | 값 |
|---|---:|
| 본 모델 가중치 | 48.07 GiB |
| MTP assistant | 0.78 GiB (별도 적재) |
| KV 캐시 | 4.00 GiB · 66,397 tok (`--kv-cache-memory-bytes 4G` 수동) |
| GPU 총 적재 | 48.54 GiB (baseline) → 49.33 GiB (MTP) |

## Speculative decoding / 양자화

- **MTP(공식 assistant)**: baseline 대비 decode 2.03×, 추출 지연 43% 단축. vLLM 0.25.1의 V1 runner 회귀 때문에 `VLLM_USE_V2_MODEL_RUNNER=1` 필요([이슈 #48848](https://github.com/vllm-project/vllm/issues/48848)).
- **DFlash** (`z-lab/gemma-4-26B-A4B-it-DFlash`, drafter 0.80 GiB): 현재 vLLM에서 Gemma4 mixed sliding/full attention 미지원으로 기동 실패([#40898](https://github.com/vllm-project/vllm/issues/40898)). 속도·정확도 미측정.
- **QAT**: 공식 GGUF/safetensors + QAT assistant 존재(동일 precision 필수). 이번 스파이크에서는 미서빙.

## 결론

프로덕션 decision 모델 기준선은 Gemma4 + 공식 MTP assistant + V2 runner(48.4 tok/s, 5.4 s/call, 18/19)입니다.

## 참고한 로그·산출물

| 항목 | 경로 |
|---|---|
| detector-bench 리포트 (케이스별 지연·탐지) | `docs/experiments/detector-bench/2026090{3,4}-*.md` — 기준 런: `20260903-194907`, `-200218`, `-202620`, `20260904-000126` |
| detector-bench 원시 결과 | `docs/experiments/detector-bench/*.results.json` (동일 timestamp) |
| vLLM 기동 로그 (가중치/KV/CUDA graph 수치) | `hub` 프로세스 로그: `final-gemma4`(baseline), `gemma4-mtp-v2`(MTP V2) — `Checkpoint size`, `Model loading took`, `GPU KV cache size`, `Graph capturing ... took` 라인 |
| 벤치 하네스 | `scripts/detector_bench.py` (2026-09-04 제거됨 — 산출물만 아카이브) |
