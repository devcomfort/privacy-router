# Qwen3.6 35B A3B — decision 모델 후보 리포트

**모델**: `QuantTrio/Qwen3.6-35B-A3B-AWQ` (AWQ 4-bit, MoE 활성 3B, 가중치 23.71 GiB)
**역할**: Gemma4 대비 저메모리·고속 후보
**측정**: GB10 단일 GPU, vLLM 0.25.1, `temperature=0`, `--max-model-len 8192`, `--gpu-memory-utilization 0.35`
**평가**: `detector-bench` 10케이스 / 기대 스팬 19개 재현율

## 결과 요약

| 설정 | decode | 추출 지연 | 정확도(hits/19) | 벤치 런 |
|---|---:|---:|---:|---|
| baseline (AWQ Marlin + CUDA graph) | 36.5 tok/s | 5.50 s | 10/19 | `detector-bench/20260903-184905.md` |
| + `--kv-cache-dtype fp8` | 36.7 tok/s | — | 미검 | — |
| + MTP `num_speculative_tokens=2` | **60.4 tok/s** (1.66×) | 4.50 s | 15/19 | `detector-bench/20260903-192315.md` |
| + MTP `num_speculative_tokens=3` | 61.9 tok/s (포화) | 6.12 s | 13/19 | `detector-bench/20260903-193032.md` |
| 설정 미기록 런 | — | 5.58 s | 18/19 | `detector-bench/20260903-203221.md` |

- `20260903-184756.md`(0/19, 12 ms)는 서버 무응답으로 판정된 **무효 런**이라 성능에 포함하지 않습니다.
- `203221` 런은 18/19를 기록했으나 산출물에 vLLM 설정이 기록돼 있지 않습니다. 재현 설정을 확인하기 전까지 기준 성능으로 채택하지 않습니다.
- 문서화된 기준 결론은 **MTP2가 최적**(15/19, 60.4 tok/s). MTP3는 스펙 큰이 포화되어 정확도가 오히려 하락(13/19).

## 메모리 소모

| 항목 | 값 |
|---|---:|
| 본 모델 가중치 | 23.71 GiB (AWQ 4-bit) |
| MTP | native — 체크포인트 내장, 추가 적재 0 |
| KV 캐시 | 6.18 GiB · 132,035 tok (자동 프로파일링) |
| GPU 총 적재 | 23.80 GiB |

## 결론

Gemma4 대비 **메모리 약 절반(23.8 vs 49.3 GiB)**, **KV 캐시 2배(132k vs 66k tok)**, **decode 소폭 우위(60.4 vs 48.4 tok/s)**. 다만 탐지 정확도가 낮다(기준 MTP2 15/19 vs Gemma4 18/19) — 안전 쿼리 오탐과 기관명·맥락 스팬 누락이 많아 decision 모델 교체는 추가 검증이 필요합니다. 상세 근거: `docs/dev/local-inference-speed-spike.md`.
