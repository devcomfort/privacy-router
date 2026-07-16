# experiments/prompt_variants/

Extractor 프롬프트 변형 모음 (32개).

## 명명 규칙

`extract.<techniques>.prompt`

### 기법 조합

| 기법 | 설명 |
|---|---|
| `fewshot` | Few-shot 예시 포함 |
| `cot` | Chain-of-Thought 추론 |
| `role` | 역할 부여 ("as a genius expert") |
| `conservative` | 보수적 판별 (민감 우선) |
| `selfcheck` | 자기 검증 단계 |
| `evidence` | 근거 인용 요구 |
| `multistep` | 다단계 분석 |

## 활성 프롬프트

- **`extract.fewshot_v2.prompt`** — 현재 최적 프롬프트 (Optuna best, 88.2%)

## 사용 위치

- `experiments/local_benchmark.py` → `PROMPT_FILE`
- `experiments/run_experiment.py` → Optuna 튜닝
- `agents/extractor/` → 프로덕션 (별도 관리)
