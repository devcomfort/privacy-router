# 로컬 추론 속도 스파이크 (GB10, 2026-09-03)

GB10(DGX Spark, 121 GB 통합 메모리)에서 vLLM 0.25.1로 decision 모델 후보를 서빙하고,
양자화 가중치와 서빙 설정 변형이 속도와 탐지 정확도에 미치는 영향을 실측한 기록입니다.
정확도는 detector_bench의 10케이스 기대 스팬 재현율(19개 스팬)로 측정했으며, 리포트는 `docs/experiments/detector-bench/`에 보존했습니다.

## 실험 설정

공통: `--max-model-len 16384`(gemma4) / `8192`(qwen36), 단건 스트림 디코드, temperature 0,
warm 상태 3회 평균. GPU 가용 메모리 약 91 GB(ollama 상주 모델 evict 후).

## Gemma 4 26B A4B (bf16, 프로덕션 decision 모델)

`google/gemma-4-26B-A4B-it` (가중치 49 GB, 활성 4B MoE), served name `google/gemma-4-26b-local`.

| 설정 | decode tok/s | 탐지 벤치 | 추출 지연/call |
|---|---:|---:|---:|
| A — 공식 compose 재현(`--enforce-eager`, `--kv-cache-memory-bytes 4G`, util 0.7) | 21.9 | 18/19 | 10.3s |
| B — CUDA graph + torch.compile 허용(A에서 `--enforce-eager` 제거) | 23.7 (+8%) | 18/19 | 9.5s |

- MTP 가중치가 없어 speculative decoding 변형 불가 (config에 `mtp_*` 필드 없음).
- 정확도는 OpenRouter `gemma-4-26b-a4b-it` 실측(18/19, 6–8s)과 동일. 로컬은 지연이 약 1.3–1.5배 길다.
- `--enforce-eager` 제거는 안정성 리스크 없이 소폭 이득. 단 첫 기동에 torch.compile 수 분이 추가된다.

## Qwen3.6-35B-A3B (AWQ 4-bit, MoE 활성 3B)

`QuantTrio/Qwen3.6-35B-A3B-AWQ` (25.4 GB, 완전 캐시), bf16 원본(71.9 GB)은 캐시 미완·메모리 초과로 제외.

| 설정 | decode tok/s | 탐지 벤치 | 추출 지연/call |
|---|---:|---:|---:|
| baseline (AWQ Marlin + CUDA graph) | 36.5 | 10/19 | 5.5s |
| + `--kv-cache-dtype fp8` | 36.7 (이득 없음) | 미검 | - |
| + `--speculative-config '{"method":"mtp","num_speculative_tokens":2}'` | 60.4 (1.66×) | 15/19 | 4.5s |
| + `num_speculative_tokens:3` | 61.9 (포화) | 13/19 | 6.1s |

- MTP speculative decoding은 검증 기반이라 손실 없이 속도만 개선한다. 2토크가 최적.
- fp8 KV cache는 8K 컨텍스트에서 이득이 확인되지 않았다.
- 첫 기동은 FlashInfer autotune으로 약 15분, 이후 torch.compile 캐시 재사용으로 약 5분.

## 결론

- 속도 레버는 모델별로 다르다: Qwen3.6 AWQ는 **MTP 스펙 디코딩(1.7×)**, Gemma4는 **CUDA graph(1.08×)**가 유효.
- 탐지 정확도는 gemma-4-26b-a4b 계열이 명확히 우위(18/19). Qwen3.6 AWQ는 안전 쿼리 오탐과 누락이 많아 decision 모델 교체는 추가 검증 필요.
- OpenRouter gpt-oss-120b(Cerebras 고정 포함)는 reasoning 토큰 때문에 이 워크로드에서 지연·비용 모두 불리(`docs/experiments/detector-bench/20260903-185856.md` 참조).

## 재현

```bash
# Gemma4 B 설정
uv run vllm serve google/gemma-4-26B-A4B-it \
  --served-model-name google/gemma-4-26b-local \
  --port 8011 --dtype bfloat16 --kv-cache-memory-bytes 4G \
  --gpu-memory-utilization 0.7 --max-model-len 16384 --trust-remote-code \
  --limit-mm-per-prompt '{"image":0,"audio":0}'
# 탐지 벤치 실행: detector_bench 도구는 아카이브됨 — 결과 리포트는 docs/experiments/detector-bench/ 참조

# Qwen3.6 MTP2 설정
uv run vllm serve QuantTrio/Qwen3.6-35B-A3B-AWQ \
  --port 8012 --max-model-len 8192 --gpu-memory-utilization 0.35 \
  --speculative-config '{"method":"mtp","num_speculative_tokens":2}'
# 탐지 벤치 실행: detector_bench 도구는 아카이브됨 — 결과 리포트는 docs/experiments/detector-bench/ 참조
```

실험 리포트·원시 결과: `docs/experiments/detector-bench/` (원본 gitignored `var/detector-bench/`)
