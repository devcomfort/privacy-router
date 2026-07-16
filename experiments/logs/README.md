# experiments/logs/

실험 실행 로그 저장소.

## 현재 파일

| 파일 | 설명 |
|---|---|
| `local_benchmark.log` | 교정 파이프라인 (v2) 벤치마크 실행 로그 — E2B/E4B/12B 각 76% |

## 아카이브된 로그

이전 실행 로그 39개는 `archive/experiments-v1-logs/`로 이동됨:
- `vllm_*.log` (23개) — 종료된 vLLM 서버 로그
- `param_tuning*.log` (5개) — Optuna 튜닝 (results JSON으로 대체)
- `tree_search*.log` (2개) — 프롬프트 탐색
- `full_run*.log` (4개) — 올드 파이프라인 실행
- 기타 (5개) — 통합 로그, 테스트 등
