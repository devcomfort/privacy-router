# experiments/logs/

실험 실행 로그 파일 저장소.

## 구분

| 패턴 | 설명 |
|---|---|
| `vllm_*.log` | 모델별 vLLM 서버 실행 로그 |
| `param_tuning*.log` | Optuna 하이퍼파라미터 튜닝 로그 |
| `tree_search*.log` | 프롬프트 트리 탐색 로그 |
| `full_run*.log` | 전체 실험 실행 로그 |
| `local_benchmark.log` | 로컬 벤치마크 실행 로그 (교정 파이프라인) |
| `vllm.log` | vLLM 통합 로그 |

## 보존 정책

로그는 실험 재현성 보존 목적으로 유지. 디스크 정리 시 `archive/`로 이동.
