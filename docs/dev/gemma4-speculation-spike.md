# Gemma 4 26B A4B 가중치·Speculative Decoding 스파이크

**실험일**: 2026-09-04  
**호스트**: NVIDIA GB10, 121.6 GiB unified memory, aarch64  
**런타임**: vLLM 0.25.1, 단일 GPU, `temperature=0`, 256 output-token 속도 측정  
**품질 벤치**: `scripts/detector_bench.py`, 10개 케이스·기대 스팬 19개

## 1. 시도할 수 있는 Gemma 4 가중치

Google은 Gemma 4 26B A4B에 다음 계열을 제공합니다.

| 계열 | 대상 | 상태 |
|---|---|---|
| 원본 | `google/gemma-4-26B-A4B-it` | 로컬 캐시 완료, 약 49 GB |
| 공식 MTP assistant | `google/gemma-4-26B-A4B-it-assistant` | 다운로드 완료, MTP 시도 |
| 공식 QAT GGUF | `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` | 공식 배포 확인, 현재 스파이크에서는 미측정 |
| 공식 QAT safetensors | `google/gemma-4-26B-A4B-it-qat-q4_0-unquantized` | 공식 배포 확인, 현재 스파이크에서는 미측정 |
| 공식 QAT MTP assistant | `google/gemma-4-26B-A4B-it-qat-q4_0-unquantized-assistant` | 공식 배포 확인. QAT target과 동일 precision으로 짝지어야 함 |
| DFlash drafter | `z-lab/gemma-4-26B-A4B-it-DFlash` | 다운로드 완료, vLLM에서 시도 |

Google의 모델 카드는 QAT target과 speculative decoding assistant의 precision을 일치시켜야 한다고 명시합니다. 따라서 QAT target을 사용할 경우 일반 `gemma-4-26B-A4B-it-assistant`가 아니라 QAT assistant를 사용해야 합니다.

## 2. GB10 실측 결과

### 2.1 원본 Gemma 4 + vLLM

| 설정 | decode 속도 | detector 벤치 | 추출 지연 |
|---|---:|---:|---:|
| `--enforce-eager` + `--kv-cache-memory-bytes 4G` | 21.9 tok/s | 18/19 | 10.3 s/call |
| CUDA graph 허용(`--enforce-eager` 제거) | 23.8 tok/s | 18/19 | 9.5 s/call |
| CUDA graph + 공식 Gemma MTP assistant + V2 runner | **48.4 tok/s** | **18/19** | **5.4 s/call** |

MTP 설정:

```bash
VLLM_USE_V2_MODEL_RUNNER=1 \
uv run vllm serve google/gemma-4-26B-A4B-it \
  --served-model-name google/gemma-4-26b-local \
  --port 8011 --dtype bfloat16 \
  --kv-cache-memory-bytes 4G --gpu-memory-utilization 0.7 \
  --max-model-len 16384 --trust-remote-code \
  --limit-mm-per-prompt '{"image":0,"audio":0}' \
  --speculative-config '{"method":"mtp","model":"google/gemma-4-26B-A4B-it-assistant","num_speculative_tokens":2}'
```

**결과**: MTP 전환으로 baseline 대비 decode 약 **2.03배**, 추출 지연 약 **43% 감소**. 품질 벤치는 baseline과 동일한 18/19였습니다. MTP는 target이 native multi-token prediction을 지원하거나 별도 assistant를 제공할 때 사용하는 vLLM 경로입니다.

### 2.1.1 실제 detector 벤치 결과

MTP V2 설정으로 실행한 10개 케이스의 실제 결과입니다. `합격`은 기대 스팬을 모두 적중한 경우이며, `실패`는 누락된 스팬을 함께 표시합니다.

| 케이스 | 상태 | 지연 | 탐지 결과 |
|---|---|---:|---|
| `ko-rrn` | 합격 | 5.735 s | `RESIDENT_REGISTRATION_NUMBER=901212-1234567` |
| `ko-contact` | 합격 | 9.821 s | `NAME=김민수`, `PHONE=010-1234-5678`, `EMAIL=minsu.kim@example.invalid` |
| `ko-card` | 합격 | 3.870 s | `CARD_NUMBER=1234-5678-9012-3456` |
| `ko-business` | 합격 | 4.098 s | `BUSINESS_STRATEGY=삼성전자 차세대 AP 개발 건으로, TSMC 3nm 공정을 채택하기로 내부적으로 결정했다.` |
| `ko-research` | **실패 — 누락** | 6.115 s | `NAME=김동현`, `RESEARCH_CONCEPT=contextual distillation`; 누락: `광주과학기술원` |
| `en-pii` | 합격 | 11.314 s | `EMAIL`, `PHONE`, `NAME`, `ADDRESS` 모두 적중 |
| `en-secret` | 합격 | 6.258 s | `BUSINESS_STRATEGY=Acme Corp`, `FINANCIAL_TERM=$4.2M` |
| `en-safe` | 합격 | 0.406 s | 탐지 결과 없음 |
| `ko-safe` | 합격 | 0.404 s | 탐지 결과 없음 |
| `ko-address` | 합격 | 6.237 s | `NAME=홍길동`, `ADDRESS=서울특별시 강남구 테헤란로 123` |

**실행 집계**: 10개 중 9개 합격, 1개 실패. 기대 스팬 기준 `18/19`; 실패는 `ko-research`의 기관명 `광주과학기술원` 누락 한 건입니다. 안전 쿼리 2개에서는 오탐이 없었습니다.


### 2.2 Gemma 4 + DFlash

공식 DFlash model card의 vLLM 명령(`num_speculative_tokens=15`, `flash_attn` draft, `triton_attn` target, `max-num-batched-tokens=32768`)을 GB10에서 실행했습니다.

| 단계 | 결과 |
|---|---|
| 첫 시도 | `max_num_scheduled_tokens`가 음수가 되어 설정 검증 실패 |
| `--max-num-batched-tokens 32768` 재시도 | DFlash drafter 초기화 중 실패 |
| V2 runner 재시도 | 동일 실패 |
| 근본 원인 | `NotImplementedError: DFlash does not yet support mixed sliding/full attention via layer_types` |
| 실측 속도/정확도 | 실행 불가 — 측정값 없음 |

따라서 이번 환경에서 DFlash의 속도 우위(아래 출처의 B200 실험)는 재현하지 못했습니다. 이는 DFlash 아이디어의 정확도나 속도가 나쁘다는 결론이 아니라, 현재 설치된 vLLM 0.25.1의 Gemma 4 mixed sliding/full attention 지원 부족에 따른 **실행 불가**입니다. DFlash를 재현하려면 vLLM의 관련 SWA/Gemma4 패치가 포함된 최신 개발 버전 또는 해당 패치 브랜치가 필요합니다.

## 3. 결론

1. **현재 GB10에서 바로 쓸 수 있는 최선**: 원본 Gemma 4 + 공식 MTP assistant + `VLLM_USE_V2_MODEL_RUNNER=1`.
2. **실측**: 48.4 tok/s, 5.4 s/call, detector 18/19. 이전 Gemma4 baseline 23.8 tok/s, 9.5 s/call보다 유의미하게 빠릅니다.
3. **QAT**: 메모리를 줄일 수 있는 공식 선택지입니다. 다만 QAT target과 QAT assistant를 같은 precision으로 맞춰야 하며, 이 스파이크에서는 QAT 26B target을 새로 서빙하지 않았습니다.
4. **DFlash**: model card와 vLLM에 경로는 존재하지만, 현재 vLLM에서 Gemma4의 mixed attention 때문에 시작조차 되지 않았습니다. 패치 브랜치 확보 전에는 속도 수치를 주장할 수 없습니다.
5. **정확도 해석**: 10개 케이스는 방향성 확인용 소표본입니다. MTP는 greedy verification 경로이므로 MTP 자체가 detector 품질을 낮춘다고 볼 근거는 없지만, 실제 교체 전 더 큰 corpus와 반복 측정이 필요합니다.

## 4. 출처

- [Google Gemma 4 QAT 공식 모델 카드](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-unquantized-assistant) — QAT 계열, 모델 크기, 동일 precision assistant 호환 규칙
- [Google Gemma 4 공식 MTP assistant](https://huggingface.co/google/gemma-4-26B-A4B-it-assistant) — 원본 Gemma4 assistant checkpoint
- [vLLM MTP 문서](https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/) — Gemma4 assistant에 `method: mtp` 사용
- [vLLM Gemma4 MTP GB10 회귀 이슈 #48848](https://github.com/vllm-project/vllm/issues/48848) — vLLM 0.25.1의 `3840 × 5632` shape 오류와 `VLLM_USE_V2_MODEL_RUNNER=1` workaround
- [vLLM DFlash SWA 이슈 #40898](https://github.com/vllm-project/vllm/issues/40898) — mixed sliding/full attention 지원 패치와 현재 제한
- [Gemma4 DFlash vLLM PR #41703](https://github.com/vllm-project/vllm/pull/41703) — Gemma4 전용 DFlash 수정 및 B200 benchmark
- [Gemma4 DFlash model card](https://huggingface.co/z-lab/gemma-4-26B-A4B-it-DFlash) — vLLM/SGLang 실행 명령과 DFlash benchmark

## 5. 실험 산출물

- Gemma4 baseline: `var/detector-bench/20260903-202620/report.md`
- Gemma4 MTP V2: `var/detector-bench/20260904-000126/report.md`
- 이전 Gemma4/Qwen 로컬 설정 비교: `docs/dev/local-inference-speed-spike.md`
