# experiments/datasets/

합성 테스트 데이터셋 저장소.

## 파일

| 파일 | 설명 |
|---|---|
| `benchmark_v2.json` | 120케이스 메인 벤치마크 데이터셋 (v2.0.0) |

## 매트릭스 커버리지

- Sensitivity: L1 (Obviously Sensitive) ~ L4 (Not Sensitive)
- Context: personal, corporate, research
- Detection Type: morphological, contextual, none
- Language: KO, EN

## 생성 방법

`experiments/generate_dataset.py` 실행으로 재현 가능.
자세한 내용은 `experiments/DATA_SYNTHESIZE_METHOD.md` 참조.
