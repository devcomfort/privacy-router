# Detector benchmark 리포트 아카이브

`detector_bench`로 생성한 PII/비밀 탐지 벤치의 요약 리포트(`<timestamp>.md`)와 원시 결과(`<timestamp>.results.json`)를 보존한 곳입니다. 고가치 실험 증거라 gitignored인 `var/detector-bench/`에서 Git 추적 영역인 여기로 **이동**했습니다.

- 리포트 포맷: 10개 케이스, 기대 스팬 19개, 기대 스팬 재현율(hits/19) 및 케이스별 지연·탐지 엔티티.
- 인용 문서: `docs/dev/gemma4-speculation-spike.md`, `docs/dev/local-inference-speed-spike.md`.

## 런 인덱스

| timestamp | detector / config | 인용 |
|---|---|---|
| 20260903-164542 | presidio, lfm, opf, llm | — |
| 20260903-171712 | presidio, lfm, opf, llm-ollama, llm-openrouter | — |
| 20260903-172646 | presidio, lfm, opf, ollama(qwen3:1.7b), openrouter(gemma-4-26b-a4b-it) | — |
| 20260903-180200 | gpt-oss-120b (openrouter) | — |
| 20260903-184756 | qwen36 AWQ (local vLLM) | speed-spike |
| 20260903-184905 | qwen36 AWQ (local vLLM) | speed-spike |
| 20260903-185856 | gpt-oss-120b openrouter + cerebras | speed-spike |
| 20260903-192315 | qwen36 AWQ (local vLLM) | speed-spike |
| 20260903-193032 | qwen36 AWQ (local vLLM) | speed-spike |
| 20260903-194907 | gemma4 (local vLLM) | speed-spike |
| 20260903-200218 | gemma4 (local vLLM) | speed-spike |
| 20260903-202620 | gemma4 baseline (CUDA graph) | speculation-spike |
| 20260903-203221 | qwen36 AWQ (local vLLM) | speed-spike |
| 20260904-000126 | gemma4 + 공식 MTP assistant + V2 runner | speculation-spike |
