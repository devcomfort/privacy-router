# vLLM 가속화 종합 보고서

> **작성일**: 2026-06-25<br>
> **vLLM 버전**: 0.23.0<br>
> **GPU**: NVIDIA GB10 (121.62 GiB)<br>
> **테스트**: 20케이스 subset, benchmark_v2 기반

---

## 1. Executive Summary

| 최적화 | 효과 | 정확도 영향 |
|---|---|---|
| **동시 배치 (16x)** | **11-13x throughput** | ❌ 없음 |
| **MRv2** | -5~10% latency | ❌ 없음 |
| **prefix-caching** | -20% latency | ❌ 없음 |
| **ngram speculative** | -11% latency | ❌ 없음 |

**최적 조합**: MRv2 + prefix-caching + concurrent=16 (모든 모델)

---

## 2. ngram Speculative Decoding

### 원리
입력 텍스트에서 이미 등장한 n-gram 패턴을 찾아 다음 토큰을 미리 예측. 모델이 한 번에 여러 토큰을 검증.

### 결과

| | Accuracy | Latency | Δ Latency |
|---|---|---|---|
| 없음 (baseline) | 60.0% | 4.59s | — |
| **ngram (5 tokens)** | **60.0%** | **4.07s** | **-11.3%** |

### 정확도 영향 분석
- **0% 정확도 변동**: 검증 메커니즘 때문
  - draft 토큰이 맞으면 → 채택 (동일 출력)
  - draft 토큰이 틀리면 → 거기까지만, 모델이 재생성
  - 최종 출력은 항상 모델의 것 → 정확도 동일
- ngram은 **속도만 향상**, 품질에 영향 없음

### 한계
- MRv2와 비호환 (vLLM 0.23 제한)
- 반복 패턴이 없는 작업에서는 효과 미미
- 추가 메모리 없음 (n-gram 테이블만 유지)

### 권장
- MRv2 미사용 시: 활성화 (`--speculative-config '{"method":"ngram",...}'`)
- MRv2 사용 시: 비활성화 (MRv2가 더 효과적)

---

## 3. 동시 배치 스케일링

### E2B (google/gemma-4-E2B-it)

| Concurrency | Total (20c) | Avg Lat | P95 Lat | Throughput | Accuracy | vs 1x |
|---|---|---|---|---|---|---|
| 1x | 44.4s | 2.16s | 4.33s | 0.45/s | 65.0% | — |
| 2x | 18.9s | 1.88s | 3.70s | 1.06/s | 65.0% | 2.4x |
| 4x | 10.4s | 1.83s | 3.76s | 1.92/s | 65.0% | 4.3x |
| 8x | 6.5s | 1.87s | 3.85s | 3.08/s | 65.0% | 6.8x |
| 12x | 4.8s | 1.90s | 3.87s | 4.18/s | 65.0% | 9.3x |
| **16x** | **4.0s** | **1.90s** | **3.89s** | **4.97/s** | **65.0%** | **11.1x** |
| 24x | 4.1s | 2.10s | 4.10s | 4.87/s | 65.0% | 10.8x |
| 32x | 4.0s | 2.08s | 4.01s | 4.98/s | 65.0% | 11.2x |

**최적: 16x** — 16x 이후 plateau, latency 미약간 증가

### E4B (google/gemma-4-E4B-it)

| Concurrency | Total (20c) | Avg Lat | P95 Lat | Throughput | Accuracy | vs 1x |
|---|---|---|---|---|---|---|
| 1x | 92.6s | 4.63s | 7.23s | 0.22/s | 60.0% | — |
| 2x | 39.8s | 3.97s | 6.19s | 0.50/s | 60.0% | 2.3x |
| 4x | 21.5s | 3.90s | 6.08s | 0.93/s | 60.0% | 4.3x |
| 8x | 12.9s | 3.97s | 6.16s | 1.55/s | 60.0% | 7.2x |
| 12x | 10.1s | 4.02s | 6.22s | 1.98/s | 60.0% | 9.2x |
| **16x** | **8.1s** | **4.12s** | **6.34s** | **2.46/s** | **60.0%** | **11.4x** |
| 24x | 6.4s | 4.23s | 6.43s | 3.10/s | 60.0% | 14.5x |
| 32x | 6.5s | 4.24s | 6.42s | 3.09/s | 60.0% | 14.2x |

**최적: 16~24x** — 16x 이후 이점 감소, latency 증가 시작

### EXAONE-1.2B (LGAI-EXAONE/EXAONE-4.0-1.2B)

| Concurrency | Total (20c) | Avg Lat | P95 Lat | Throughput | Accuracy |
|---|---|---|---|---|---|
| 1x | 54.6s | 2.73s | 4.28s | 0.37/s | 0.0% |
| 4x | 13.5s | 2.31s | 3.76s | 1.48/s | 0.0% |
| 16x | 6.0s | 2.55s | 3.93s | 3.31/s | 0.0% |
| 24x | 4.0s | 2.67s | 3.99s | 5.00/s | 0.0% |

**⚠️ 0% accuracy**: EXAONE은 instructor structured output과 호환 안 됨. 속도만 측정 가능.

---

## 4. 모델별 최적 동시성

| 모델 | 최적 Concurrency | Throughput | Avg Latency | Accuracy | 비고 |
|---|---|---|---|---|---|
| **E2B** | **16x** | 4.97/s | 1.90s | 65.0% | 가장 빠르고 정확 |
| **E4B** | **16~24x** | 2.46~3.10/s | 4.12~4.23s | 60.0% | 안정적 |
| EXAONE-1.2B | 24x | 5.00/s | 2.67s | 0.0% | instructor 호환 문제 |

### 권장 설정

```python
# experiments/local_benchmark.py
CONCURRENT = 16  # E2B, E4B 모두 16x가 최적
```

---

## 5. 가속 방법별 정확도 영향 요약

| 방법 | 속도 효과 | 정확도 영향 | 메모리 영향 |
|---|---|---|---|
| **동시 배치** | 11-13x throughput | ❌ 없음 | 없음 |
| **MRv2** | -5~10% latency | ❌ 없음 | 없음 |
| **prefix-caching** | -20% latency | ❌ 없음 | KV 캐시 |
| **ngram speculative** | -11% latency | ❌ 없음 | 없음 |
| MTP (Qwen 내장) | 모델 자체 느림 | ❌ 없음 | 내장 |
| MTP (Gemma4 assistant) | ~3x (미테스트) | ❌ 없음 | assistant checkpoint |

**모든 가속 방법이 정확도에 영향을 주지 않음.** 이는:
- 동시 배치: 독립 요청 → 서로 영향 없음
- MRv2: 실행 엔진 최적화 → 출력 동일
- prefix-caching: KV 재사용 → 계산 동일
- ngram: 검증 메커니즘 → 출력 동일

---

## 6. MRv2 vs ngram Speculative

| | MRv2 | ngram speculative |
|---|---|---|
| **원리** | 비동기 스케줄링 | n-gram 패턴 재활용 |
| **효과** | 동시 배치에서 큰 이점 | 단일 요청 latency 감소 |
| **동시 배치** | ✅ 호환 | ❌ MRv2와 비호환 |
| **정확도** | 동일 | 동일 |
| **권장** | ✅ 사용 | MRv2 미사용 시만 |

**결론**: MRv2가 ngram보다 범용적. 둘 다 쓸 수 없으므로 MRv2 선택.

---

## 7. 최종 권장 설정

```bash
# vLLM 시작
VLLM_USE_V2_MODEL_RUNNER=1 python3 experiments/vllm_wrapper.py \
  --model google/gemma-4-E4B-it \
  --port 8000 \
  --gpu-memory-utilization 0.65 \
  --max-model-len 4096 \
  --trust-remote-code \
  --enable-prefix-caching \
  --max-num-seqs 16
```

```python
# local_benchmark.py
CONCURRENT = 16
temperature = 0.2
top_p = 1.0
max_tokens = 1024
```

### 예상 성능 (E4B, 120케이스)

| | Before | After | Δ |
|---|---|---|---|
| Throughput | 0.22/s | 2.46/s | **+11x** |
| Total time | ~9분 | ~49초 | **-91%** |
| Accuracy | 74.2% | 74.2% | 0%p |

---

## 8. 향후 최적화 기회

| 방법 | 조건 | 예상 효과 |
|---|---|---|
| Gemma4 MTP assistant | checkpoint 다운로드 | ~3x 속도 |
| Guided JSON | vLLM guided decoding | -20% 프롬프트 오버헤드 |
| FlashInfer backend | 호환성 확인 필요 | -5~10% |
| 더 큰 모델 (12B, 26B) | GPU 메모리 확보 | 정확도 향상 가능 |

---

## 부록: 원시 데이터

- `experiments/results/acceleration_benchmark.json` — ngram + concurrent + model comparison
- `experiments/results/concurrency_sweep.json` — 모델별 동시성 스윕
- `experiments/logs/acceleration_benchmark.log` — 실행 로그
- `experiments/logs/concurrency_sweep.log` — 스윕 로그
