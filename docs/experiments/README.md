# experiments 문서 인덱스

모델 평가·벤치 산출물 모음입니다. **어디서 시작할지** 아래 순서대로 보시면 됩니다.

## 1. 모델별 최종 리포트 (여기부터)

- [`gemma4-26b-a4b.md`](gemma4-26b-a4b.md) — Gemma 4 26B A4B decision 모델: 속도·정확도·메모리·MTP/DFlash/QAT
- [`qwen3.6-35b-a3b.md`](qwen3.6-35b-a3b.md) — Qwen3.6 35B A3B 후보: AWQ/MTP 실측과 Gemma4 대비 트레이드오프

## 2. detector-bench 원시 런 (2026-09-03~04)

[`detector-bench/`](detector-bench/README.md) — `detector_bench`가 생성한 케이스별 리포트(`<timestamp>.md`)와 원시 결과(`<timestamp>.results.json`). 런 인덱스는 하위 README 참조.

## 3. 레거시 eval 파이프라인 (2026-06~07)

초기 소모델 후보 탐색·프롬프트 튜닝 시대의 산출물입니다. **현행 Qwen/Gemma decision 모델 비교와 무관**하며, 아카이브 용도로만 남아 있습니다.

- `eval-report.md` — 6월 모델 선정(v1) + 프롬프트 최적화(v2) 보고서
- `tuning-report.md` — Optuna 파라미터 튜닝 보고서
- `eval-aggregated.json`, `ground-truth.json`, `ground-truth-improvements.json` — 집계·정답 데이터
- `results/placeholder-repair-gemma4-26b-20260712.json` — placeholder repair 평가(7/12)
- `results/exaone_1_2b_vllm/eval_20260719_214800.json` — **EXAONE 4.0 1.2B를 vLLM으로 돌린 7/19 단일 평가**. 당시 Extractor 후보로 검토한 초소형 모델 중 하나(민감도 64.7% / 액션 35.3%)로, 이후 decision 모델이 Gemma4 26B로 확정되면서 폐기된 실험입니다. 이름의 `1_2b`는 1.2B 파라미터를 뜻하며 "1.0 2B"가 아닙니다.

## 관련 개발 문서

- `docs/dev/gemma4-speculation-spike.md`, `docs/dev/local-inference-speed-spike.md` — 서빙 설정·speculative decoding 상세 실측
