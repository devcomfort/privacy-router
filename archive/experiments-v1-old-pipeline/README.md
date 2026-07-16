# archive/experiments-v1-old-pipeline/

올드 파이프라인 (v1) 벤치마크 결과 아카이브.

## 파이프라인 차이

| | v1 (old) | v2 (current) |
|---|---|---|
| Extractor 출력 | `action` 직접 출력 | `sensitivity` + `records[]` |
| Judge | 없음 (Extractor가 직접 action) | 규칙 기반 (is_essential → action) |
| 문제 | 프롬프트-스키마 불일치로 E2B 48% | 교정 후 76% |

## 파일

| 파일 | 설명 |
|---|---|
| `local_benchmark_v1_old_pipeline.json` | 7모델 × 25케이스 요약 |
| `local_benchmark_details_v1_old_pipeline.json` | 상세 결과 (1.4MB) |

## 결과 범위

- Gemma4-E2B: 48% → v2에서 76%로 개선
- Gemma4-E4B: 44% → 76%
- EXAONE-1.2B: 68% (올드 파이프라인 최고)
