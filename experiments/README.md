# Experiments

Privacy Router 실험 프레임워크. 모델 평가, 하이퍼파라미터 튜닝, 프롬프트 탐색을 수행.

## 디렉토리 구조

```
experiments/
├── datasets/              # 합성 테스트 데이터셋 (benchmark_v2.json: 120케이스)
├── logs/                  # 실행 로그 (vLLM, Optuna, 벤치마크)
├── prompt_variants/       # Extractor 프롬프트 변형 32개
├── responses/             # 프롬프트 응답 분석
├── results/               # 실험 결과 JSON + 대시보드 (viewer.html)
├── generate_dataset.py    # 데이터셋 생성기
├── local_benchmark.py     # 로컬 모델 벤치마크 (Extractor→Judge)
├── run_experiment.py      # Optuna 하이퍼파라미터 튜닝
├── optuna_tuning.py       # Optuna 튜닝 스크립트
├── tree_search.py         # 프롬프트 트리 탐색
├── vllm_wrapper.py        # vLLM SIGTERM 방지 래퍼
├── DATA_SYNTHESIZE_METHOD.md  # 데이터셋 생성 방법론
└── EXPERIMENT_VERSIONS.json   # 실험 버전 매니페스트
```

## 파이프라인 (v2 - 현재)

```
Extractor(LLM) → sensitivity/records[] → Judge(rule-based) → action
```

- Extractor: `is_sensitive` + `records[].category/span/is_essential` 출력
- Judge: `is_essential` 플래그로 action 결정 (essential→block, non-essential→selective_mask, 없음→allow)

## 빠른 시작

```bash
# 1. 데이터셋 생성
python3 experiments/generate_dataset.py

# 2. vLLM 서버 시작
python3 experiments/start_vllm.py --model gemma-4-E4B-it

# 3. 벤치마크 실행
python3 experiments/local_benchmark.py

# 4. 결과 확인
python3 -m http.server 8891 --directory experiments/results
# → http://localhost:8891/viewer.html
```

## Optuna 튜닝

```bash
# vLLM 서버와 함께 실행
python3 experiments/optuna_tuning.py --model gemma-4-E4B-it --trials 50

# 이미 실행 중인 vLLM 사용
python3 experiments/optuna_tuning.py --model gemma-4-E4B-it --trials 50 --no-vllm
```

### 검색 공간

| 파라미터 | 범위 | 비고 |
|---|---|---|
| prompt | fewshot_v2 (현재 고정) | Optuna로 탐색 완료 |
| temperature | 0.0 - 1.0 | step 0.1 |
| top_p | 0.7 - 1.0 | step 0.05 |
| max_tokens | 1024, 2048 | - |

### 최적 파라미터 (fewshot_v2)

- Temperature: 0.6
- Top P: 0.75
- Max Tokens: 2048
- Score: 0.878 (88.2% overall)

## 모델 목록 (12 official)

| 모델 | 파라미터 | 상태 |
|---|---|---|
| google/gemma-4-E2B-it | 2B | ✅ 벤치마크 완료 |
| google/gemma-4-E4B-it | 4B | ✅ 벤치마크 완료 |
| google/gemma-4-12B-it | 12B | ✅ 벤치마크 완료 |
| google/gemma-4-26B-A4B-it | 26B MoE | ⏳ 대기 |
| google/diffusiongemma-26B-A4B-it | 26B | ❌ 로딩 실패 |
| LGAI-EXAONE/EXAONE-4.0-1.2B | 1.2B | ⏳ 대기 |
| LGAI-EXAONE/EXAONE-4.5-33B | 33B | ❌ GPU 부족 |
| LGAI-EXAONE/EXAONE-4.5-33B-FP8 | 33B | ❌ GPU 부족 |
| mistralai/Ministral-3-3B-Instruct-2512 | 3B | ❌ Pixtral 충돌 |
| ibm-granite/granite-4.1-8b | 8B | ⏳ 대기 |
| Qwen/Qwen3.5-9B | 9B | ⏳ 대기 |
| Qwen/Qwen3.6-35B-A3B | 35B MoE | ❌ 로딩 실패 |

## 실험 버전

`EXPERIMENT_VERSIONS.json` 참조. 요약:

| 버전 | 상태 | 설명 |
|---|---|---|
| v1-old-pipeline | archived | 직접 action 출력 (48-68%) |
| v1-contaminated | archived | threeharm 프롬프트, 빈 데이터 |
| v2-corrected-pipeline | valid | Extractor→Judge (76%, 25케이스) |
| v3-benchmark-v2 | pending | 120케이스, 미실행 |

## GPU 설정

```bash
# vLLM 기본 설정
--gpu-memory-utilization 0.65 --max-model-len 4096 --trust-remote-code --enforce-eager
```

- GPU: NVIDIA (121.62 GiB), `gpu_memory_utilization=0.65`
- 26B+ 모델은 OOM 가능성 있음
- 좀비 VLLM::EngineCore 프로세스 주의 (`cleanup_vllm()`으로 정리)
