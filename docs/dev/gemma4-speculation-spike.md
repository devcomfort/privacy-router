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
| 공식 MTP assistant | `google/gemma-4-26B-A4B-it-assistant` | 다운로드 완료 (디스크 0.78 GiB), MTP 실측 |
| 공식 QAT GGUF | `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` | 공식 배포 확인, 현재 스파이크에서는 미측정 |
| 공식 QAT safetensors | `google/gemma-4-26B-A4B-it-qat-q4_0-unquantized` | 공식 배포 확인, 현재 스파이크에서는 미측정 |
| 공식 QAT MTP assistant | `google/gemma-4-26B-A4B-it-qat-q4_0-unquantized-assistant` | 공식 배포 확인. QAT target과 동일 precision으로 짝지어야 함 |
| DFlash drafter | `z-lab/gemma-4-26B-A4B-it-DFlash` | 다운로드 완료 (디스크 0.80 GiB), vLLM 실행 실 |

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

### 2.1.2 MTP V2 vs baseline 케이스별 비교

동일 입력 10개 케이스를 MTP V2(`var/detector-bench/20260904-000126/report.md`)와 baseline(`var/detector-bench/20260903-202620/report.md`)으로 각각 실행한 결과입니다.

| 케이스 | 평가 | MTP V2 지연 | baseline 지연 | 단축 | 비고 |
|---|---|---:|---:|---:|---|
| `ko-rrn` | 합격 | 5.735 s | 8.214 s | 30% | 동일 정확도 |
| `ko-contact` | 합격 | 9.821 s | 16.471 s | 40% | 동일 정확도 |
| `ko-card` | 합격 | 3.870 s | 6.966 s | 44% | 동일 정확도 |
| `ko-business` | 합격 | 4.098 s | 7.629 s | 46% | 동일 정확도 |
| `ko-research` | 실패 | 6.115 s | 11.503 s | 47% | 둘 다 `광주과학기술원` 누락 |
| `en-pii` | 합격 | 11.314 s | 20.464 s | 45% | 동일 정확도 |
| `en-secret` | 합격 | 6.258 s | 11.804 s | 47% | MTP는 `FINANCIAL_TERM`, baseline은 `FINANCIAL_DATA`로 라벨 차이만 있음 |
| `en-safe` | 합격 | 0.406 s | 0.584 s | 30% | 안전 쿼리, 오탐 없음 |
| `ko-safe` | 합격 | 0.404 s | 0.591 s | 32% | 안전 쿼리, 오탐 없음 |
| `ko-address` | 합격 | 6.237 s | 11.111 s | 44% | 동일 정확도 |
| 평균 | — | 5.426 s | 9.534 s | 43% | 양쪽 모두 18/19 |

MTP V2는 baseline 대비 **평균 43% 빠른 추출 지연**을 보였고, 정확도는 같은 18/19(10개 중 9개 합격, 안전 쿼리 2개에서 오탐 없음)를 유지했습니다. `ko-research` 실패는 MTP 도입과 무관하게 양쪽 모두 동일하게 발생하는 사전 한계입니다. `en-secret` 한 건은 스팬 적중은 같고 카테고리 라벨(`FINANCIAL_TERM` vs `FINANCIAL_DATA`)만 다르므로 합격으로 봅니다.



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

### 2.3 옵션별 메모리 소모 (본 모델 / MTP / KV 캐시)

아래 수치는 각 vLLM 기동 로그에서 직접 추출했습니다. `Checkpoint size`는 디스크 가중치, `Model loading took`은 target+draft 합산 GPU 상주량, `Available/reserved KV`는 KV 캐시, `Graph capturing ... took`은 CUDA graph 실측 상주량입니다.

| 옵션 | 본 모델 가중치 | MTP / drafter | KV 캐시 | CUDA graph | GPU 총 적재 |
|---|---:|---:|---:|---:|---:|
| Gemma4 baseline (bf16) | 48.07 GiB | — | 4.00 GiB (66,397 tok) | 0.90 GiB | 48.54 GiB |
| Gemma4 + MTP V2 | 48.07 GiB | 0.78 GiB | 4.00 GiB (66,397 tok) | 1.27 GiB | 49.33 GiB |
| Qwen3.6-35B-A3B AWQ + MTP | 23.71 GiB | 내장 (추가 0) | 6.18 GiB (132,035 tok) | 1.60 GiB | 23.80 GiB |
| Gemma4 + DFlash | 48.07 GiB | 0.80 GiB | 미측정 | 미측정 | 기동 실패 |

**관찰**:
- **Gemma4 MTP**는 별도 assistant(0.78 GiB)를 GPU에 추가 적재해 총 적재가 48.54 → 49.33 GiB(+0.79 GiB)로 늘고, CUDA graph도 0.90 → 1.27 GiB로 증가합니다. KV 캐시는 `--kv-cache-memory-bytes 4G`로 수동 고정해 baseline과 동일합니다.
- **Qwen3.6 MTP**는 native MTP head가 체크포인트에 내장되어 있어 **추가 가중치 다운로드·적재가 0**입니다. AWQ 4-bit라 본 모델이 23.71 GiB로 Gemma4(bf16)의 절반 이하이고, `--gpu-memory-utilization 0.35` 자동 프로파일링이라 남는 메모리로 KV 캐시 6.18 GiB(132,035 tok)를 확보합니다.
- **DFlash** drafter는 0.80 GiB로 용량은 작지만, 위 2.2의 `NotImplementedError`로 target과 함께 GPU에 올려 KV를 배분하기 전 단계에서 실패해 측정 불가입니다.
- GB10 통합 메모리 121.6 GiB 기준, 세 실행 옵션 모두 단일 GPU에서 여유 있게 동작합니다(초기 free memory 98.9~101.7 GiB 관측).

## 3. 결론

1. **현재 GB10에서 바로 쓸 수 있는 최선**: 원본 Gemma 4 + 공식 MTP assistant + `VLLM_USE_V2_MODEL_RUNNER=1`.
2. **실측**: 48.4 tok/s, 5.4 s/call, detector 18/19. 이전 Gemma4 baseline 23.8 tok/s, 9.5 s/call보다 유의미하게 빠릅니다.
3. **QAT**: 메모리를 줄일 수 있는 공식 선택지입니다. 다만 QAT target과 QAT assistant를 같은 precision으로 맞춰야 하며, 이 스파이크에서는 QAT 26B target을 새로 서빙하지 않았습니다.
4. **DFlash**: model card와 vLLM에 경로는 존재하지만, 현재 vLLM에서 Gemma4의 mixed attention 때문에 시작조차 되지 않았습니다. 패치 브랜치 확보 전에는 속도 수치를 주장할 수 없습니다.
5. **정확도 해석**: 10개 케이스는 방향성 확인용 소표본입니다. MTP는 greedy verification 경로이므로 MTP 자체가 detector 품질을 낮춘다고 볼 근거는 없지만, 실제 교체 전 더 큰 corpus와 반복 측정이 필요합니다.
6. **메모리**: Gemma4는 bf16 본 모델 48.07 GiB에 MTP assistant 0.78 GiB가 더해져 GPU 총 적재 49.33 GiB입니다. Qwen3.6 AWQ는 4-bit라 본 모델 23.71 GiB에 native MTP라 추가 적재가 0이라, Gemma4 대비 약 절반의 메모리로 더 큰 KV 캐시(132,035 vs 66,397 tok)를 확보합니다. 단 Qwen3.6의 탐지 정확도는 15/19로 Gemma4(18/19)보다 낮습니다(상세: `docs/dev/local-inference-speed-spike.md`).

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
- 메모리 수치 출처: 각 vLLM 기동 로그의 `Checkpoint size`, `Model loading took`, `GPU KV cache size`, `Graph capturing ... took` 라인 (`hub` 프로세스 `gemma4-mtp-v2`, `final-gemma4`, `final-qwen36`).
