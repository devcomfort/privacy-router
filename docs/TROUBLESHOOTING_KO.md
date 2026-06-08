# 트러블슈팅 가이드

이 문서는 Privacy Router 프로젝트 진행 중 발생한 주요 문제 — 모델 로딩, 추론 엔진, 의존성, 인프라 이슈 — 와 근본 원인, 해결 방법, 수정된 파일을 기록합니다.

---

## 목차

1. [rye sync 실패: PyTorch/vLLM 인덱스 충돌](#1-rye-sync-실패-pytorchvllm-인덱스-충돌)
2. [llama.cpp GGUF 모델 17.6% 정확도 (전부 `allow` 반환)](#2-llamacpp-gguf-모델-176-정확도-전부-allow-반환)
3. [EXAONE 4.5 33B: vLLM nightly 빌드 필요](#3-exaone-45-33b-vllm-nightly-빌드-필요)
4. [EXAONE 4.5 로컬 경로 우회 (채팅 템플릿 문제)](#4-exaone-45-로컬-경로-우회-채팅-템플릿-문제)
5. [GPU OOM: 모델별 메모리 사용량 튜닝](#5-gpu-oom-모델별-메모리-사용량-튜닝)
6. [Docker 빌드 실패: COPY .env](#6-docker-빌드-실패-copy-env)
7. [SQLModel + SQLAlchemy 2.0 Relationship 비호환성](#7-sqlmodel--sqlalchemy-20-relationship-비호환성)
8. [EXAONE 4.5 낮은 정확도: `is_load_bearing` 오분류](#8-exaone-45-낮은-정확도-is_load_bearing-오분류)

---

## 1. rye sync 실패: PyTorch/vLLM 인덱스 충돌

**증상:** `pyproject.toml`에 PyTorch 또는 vLLM 커스텀 패키지 인덱스가 정의되어 있으면 `rye sync`가 의존성 해석 오류로 실패합니다.

**근본 원인:** `pyproject.toml`에 PyTorch/vLLM pip 인덱스를 가리키는 `[[tool.rye.sources]]` 항목이 존재했습니다. 이 인덱스들은 PyPI에서 제공하는 버전과 충돌하는 버전 번호의 패키지를 제공하여 `rye`의 의존성 해석기가 불일치 상태에 빠집니다.

**해결:** `pyproject.toml`에서 모든 PyTorch/vLLM 커스텀 인덱스 항목을 제거합니다. PyPI 전용 해석을 사용하고 호환 가능한 버전을 직접 고정합니다:

```toml
# 수정 전 (실패)
[[tool.rye.sources]]
name = "pytorch"
url = "https://download.pytorch.org/whl/cu124"

[[tool.rye.sources]]
name = "vllm"
url = "https://wheels.vllm.ai/nightly"

# 수정 후 (정상)
dependencies = [
    "transformers>=5.10.0",
    "torch>=2.11.0",
    "torchvision>=0.26.0",
    ...
]
```

**수정 파일:** `pyproject.toml`, `requirements.lock`, `requirements-dev.lock`
**커밋:** `a959964`

---

## 2. llama.cpp GGUF 모델 17.6% 정확도 (전부 `allow` 반환)

**증상:** `llama-server`(llama.cpp)로 서빙하는 모든 양자화 모델이 17.6% 정확도를 기록합니다. 민감하지 않은 3개의 "allow" 케이스만 통과하고, 모든 민감 케이스에서 PII/사업비밀을 감지하지 못하고 `allow`를 반환합니다.

| 모델 | 양자화 | 정확도 | 서빙 방식 |
|---|---|---|---|
| Gemma 4 E2B | Q4_K_M | 17.6% | llama-server |
| Gemma 4 E2B | Q8_0 | 17.6% | llama-server |
| Gemma 4 E4B | Q4_K_M | 17.6% | llama-server |
| EXAONE 1.2B | Q4_K_M | 17.6% | llama-server |
| EXAONE 1.2B | Q8_0 | 17.6% | llama-server |

**근본 원인:** 두 가지 요인이 복합적으로 작용했습니다:

1. **모델 용량 부족:** 1.2B~4B 파라미터 모델에 공격적 양자화(Q4_K_M = 4비트)를 적용하면, 복잡한 `extract.prompt` 지시를 따를 추론 능력이 부족합니다. 이 프롬프트는 다단계 추론(3가지 유해성 테스트, 맥락적 분석, 한국어 이해)을 요구하며, 양자화된 소형 모델의 한계를 초과합니다.

2. **llama.cpp 채팅 템플릿 처리 문제:** `llama-server`는 자체 채팅 템플릿 래핑을 적용합니다. 일부 모델(특히 EXAONE)의 경우 템플릿 형식이 모델의 학습 형식과 일치하지 않아, 모델이 시스템 프롬프트를 완전히 무시하고 "민감 정보 없음"을 기본값으로 반환합니다.

**해결:** llama.cpp GGUF 양자화 모델에서 vLLM + 전정밀도(BF16) 가중치로 전환합니다. 동일 모델의 전정밀도 결과:

| 모델 | 양자화 | 정확도 | 서빙 방식 |
|---|---|---|---|
| Gemma 4 E2B | BF16 | 64.7% | vLLM |
| Gemma 4 E4B | BF16 | 70.6% | vLLM |
| Gemma 4 12B | BF16 | 82.4% | vLLM |

17.6% → 64~82%로의 정확도 향상은 양자화 성능 저하가 원인이었음을 확인시켜줍니다.

**수정 파일:** `scripts/run_local_eval.sh` (모델 매핑을 llama-server에서 vLLM으로 재작성), `scripts/eval_all.py` (모델 설정 업데이트)
**커밋:** `7a3ea98`

---

## 3. EXAONE 4.5 33B: vLLM nightly 빌드 필요

**증상:** `vllm`(PyPI 안정 릴리스)이 `LGAI-EXAONE/EXAONE-4.5-33B-FP8` 로딩 시 지원되지 않는 아키텍처 또는 누락된 모델 클래스 오류로 실패합니다.

**근본 원인:** EXAONE 4.5는 커스텀 트랜스포머 아키텍처(`EXAONEForCausalLM`)를 사용하며, 이 아키텍처는 vLLM nightly 빌드에만 포함됩니다. 안정 릴리스에는 EXAONE 4.5용 모델 클래스 등록이 없습니다.

**해결:** nightly 휠 인덱스에서 vLLM을 설치합니다:

```bash
pip install vllm --extra-index-url https://wheels.vllm.ai/nightly
```

또는 소스에서 빌드:

```bash
pip install git+https://github.com/vllm-project/vllm.git
```

**수정 파일:** 없음 (런타임 의존성 설치)
**검증:** 설치 후 `python -c "from vllm.model_executor.models import EXAONEForCausalLM"`이 성공해야 합니다.

---

## 4. EXAONE 4.5 로컬 경로 우회 (채팅 템플릿 문제)

**증상:** vLLM이 HuggingFace에서 EXAONE 4.5를 로드(`LGAI-EXAONE/EXAONE-4.5-33B-FP8`)하지만, 출력이 깨지거나 비어 있습니다. 모델이 추출 프롬프트를 따르지 않습니다.

**근본 원인:** HuggingFace 레포의 `tokenizer_config.json`에 EXAONE 고유 형식으로 메시지를 감싸는 커스텀 `chat_template`이 포함되어 있습니다. vLLM이 이 템플릿을 자동으로 적용하지만, 우리가 사용하는 OpenAI 호환 API 형식(시스템 메시지 → 사용자 메시지 흐름)과 비호환됩니다. 모델이 이중 래핑된 프롬프트를 수신하게 됩니다.

**해결:** 올바른 `tokenizer_config.json`으로 모델 파일의 로컬 복사본을 생성합니다:

```bash
# 모델 로컬 복사
cp -r ~/.cache/huggingface/hub/models--LGAI-EXAONE--EXAONE-4.5-33B-FP8 /tmp/exaone45-fp8-fixed

# /tmp/exaone45-fp8-fixed/tokenizer_config.json 편집
# "chat_template" 필드 제거 또는 수정
```

`eval_all.py`에서 로컬 경로를 참조합니다:

```python
"exaone-4.5-33b-fp8": {
    "model": "openai//tmp/exaone45-fp8-fixed",
    "api_base": "http://localhost:8000/v1",
    ...
}
```

**수정 파일:** `/tmp/exaone45-fp8-fixed/tokenizer_config.json` (로컬 모델 복사본), `scripts/eval_all.py`
**커밋:** `3e6ab56`

---

## 5. GPU OOM: 모델별 메모리 사용량 튜닝

**증상:** vLLM이 특정 모델 로딩 시 `torch.cuda.OutOfMemoryError`로 크래시됩니다. 특히 VRAM이 제한된 단일 GPU에서 발생합니다.

**근본 원인:** vLLM의 기본값 `--gpu-memory-utilization 0.9`는 GPU 메모리의 90%를 KV 캐시에 예약합니다. 모델 가중치와 합산하면 사용 가능한 VRAM을 초과합니다.

**해결:** 모델 크기에 따라 `--gpu-memory-utilization`을 개별 설정합니다:

| 모델 | 파라미터 | GPU 메모리 활용 | 근거 |
|---|---|---|---|
| Gemma 4 E2B | 2B | 0.3 | 소형 모델, KV 캐시 공간 확보 |
| Gemma 4 E4B | 4B | 0.4 | 중형 모델 |
| EXAONE 4.5 33B | 33B | 0.6 | 대형 FP8 모델, VRAM 대부분 필요 |

```bash
# scripts/run_local_eval.sh에서
GPU_MODELS=(
    "gemma-4-e2b-bf16|google/gemma-4-E2B-it|--gpu-memory-utilization 0.3"
    "gemma-4-e4b-bf16|google/gemma-4-E4B-it|--gpu-memory-utilization 0.4"
    "exaone-4.5-33b-fp8|LGAI-EXAONE/EXAONE-4.5-33B-FP8|--gpu-memory-utilization 0.6"
)
```

또한 `--max-model-len 32768`을 추가하여 컨텍스트 길이를 제한하고 KV 캐시 메모리 부담을 줄입니다.

**수정 파일:** `scripts/run_local_eval.sh`, `scripts/start_vllm.sh`
**커밋:** `7a3ea98`

---

## 6. Docker 빌드 실패: COPY .env

**증상:** `docker compose build` 시 다음 오류 발생:

```
ERROR: failed to solve: failed to compute cache key: "/.env" not found
```

**근본 원인:** `Dockerfile`에 `COPY .env ./`가 포함되어 있어 `.env` 파일을 빌드 컨텍스트로 복사하려고 시도합니다. `.env`는 gitignore되어 있고 빌드 컨텍스트에 존재하지 않으므로 빌드가 실패합니다.

**해결:** `Dockerfile`에서 `COPY .env ./`를 제거합니다. 환경 변수는 빌드 타임이 아닌 런타임에 `docker-compose.yml`의 `env_file: .env`를 통해 주입됩니다:

```dockerfile
# 수정 전 (실패)
COPY .env ./
COPY . ./

# 수정 후 (정상)
COPY . ./
```

**수정 파일:** `Dockerfile`
**커밋:** `a2d6999`

---

## 7. SQLModel + SQLAlchemy 2.0 Relationship 비호환성

**증상:** 서버 시작 시 다음과 같은 오류로 크래시:

```
sqlalchemy.exc.InvalidRequestError: When initializing mapper mapped class ... could not
locate a configure-time resolution for attribute ...
```

또는:

```
TypeError: issubclass() arg 1 must be a class
```

**근본 원인:** SQLModel의 `list["Model"]` 타입 어노테이션을 사용한 관계 정의가 SQLAlchemy 2.0의 매퍼 설정과 비호환됩니다. SQLAlchemy 2.0은 문자열 기반 `back_populates`를 사용한 명시적 `relationship()` 호출을 요구하지만, SQLModel의 `Field(sa_relationship=...)` 방식이 `list["Model"]` 타입 힌트와 충돌합니다.

**해결:** SQLModel 클래스에서 모든 `Relationship` 선언을 제거합니다. 코드베이스의 어떤 코드도 ORM 관계 내비게이션을 사용하지 않으므로(모든 쿼리가 명시적 `.where()` 절을 사용), 관계는 죽은 코드였습니다:

```python
# 수정 전 (실패)
class AgentConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    logs: list["UsageLog"] = Relationship(back_populates="agent_config")

# 수정 후 (정상)
class AgentConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # 관계 제거 — 쿼리는 명시적 .where() 조인 사용
```

**수정 파일:** `db/models.py`
**커밋:** `cb594e9`

---

## 8. EXAONE 4.5 낮은 정확도: `is_load_bearing` 오분류

**증상:** EXAONE 4.5 33B FP8가 PII를 정확히 탐지함에도 불구하고 35.3% 정확도만 기록합니다. 모델은 레코드를 식별하지만 `is_load_bearing` 필드를 오분류하여, 라우터가 `selective_mask` 대신 `block`(또는 그 반대)을 선택합니다.

**평가 데이터 예시** (`PII 포함(creation)` 케이스):
- 입력: "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."
- 기대: `selective_mask` (creation 맥락 — PII를 마스킹하고 전송)
- EXAONE 4.5 출력: `block` (오답 — 부하 유발 질의로 판단)
- 추출된 레코드는 정확하지만, 주민등록번호의 `is_load_bearing: false`가 잘못 설정됨 (`true`여야 함)

**근본 원인:** EXAONE 4.5는 미묘한 맥락적 판단에 대한 지시 따르기 능력이 약합니다. `is_load_bearing` 필드는 민감 정보가 요청의 목적에 *부수적인지*(마스킹 후 계속) 또는 *핵심적인지*(사용자에게 확인)를 이해해야 합니다. EXAONE 4.5는 맥락이 마스킹을 제안할 때도 보수적 분류(block/prompt_user)를 기본값으로 선택합니다.

**현재 상태:** 부분적으로 완화됨. PII 탐지 정확도는 수용 가능하지만, 라우팅 결정에는 더 강력한 모델이 필요합니다. 프로덕션 사용 시 EXAONE 4.5를 별도의 judge 모델(예: Gemini 3.1 Flash Lite)과 페어링하여 사용해야 합니다.

**수정 파일:** 없음 — 모델 능력 한계입니다.
**권장사항:** EXAONE 4.5는 추출 전용으로만 사용하고, end-to-end classify+route에는 사용하지 마세요.

---

## 요약: 서빙 스택별 모델 성능

| 모델 | 파라미터 | 서빙 | 양자화 | 정확도 | 평균 시간 |
|---|---|---|---|---|---|
| Gemma 4 E2B | 2B | llama-server | Q4_K_M | 17.6% | 0.6s |
| Gemma 4 E2B | 2B | llama-server | Q8_0 | 17.6% | 0.7s |
| Gemma 4 E4B | 4B | llama-server | Q4_K_M | 17.6% | 0.7s |
| EXAONE 1.2B | 1.2B | llama-server | Q4_K_M | 17.6% | 0.7s |
| EXAONE 1.2B | 1.2B | llama-server | Q8_0 | 17.6% | 0.7s |
| Gemma 4 E2B | 2B | vLLM | BF16 | 64.7% | 5.4s |
| Gemma 4 E4B | 4B | vLLM | BF16 | 70.6% | 8.3s |
| Gemma 4 12B | 12B | vLLM nightly | BF16 | 82.4% | 25.1s |
| EXAONE 4.5 33B | 33B | vLLM nightly | FP8 | 35.3% | 12.7s |
| Gemma 4 26B-A4B | 26B MoE | OpenRouter | — | 100.0% | 5.0s |
| Gemini 3.1 Flash Lite | — | OpenRouter | — | 100.0% | 1.9s |

**핵심 교훈:** 로컬 배포에서는 BF16 전정밀도의 vLLM이 필수입니다. llama.cpp를 통한 양자화 GGUF 모델은 이 프롬프트의 복잡도에 부적합합니다. 프로덕션에서는 OpenRouter 호스팅의 Gemma 4 26B 또는 Gemini 3.1 Flash Lite가 저비용으로 100% 정확도를 제공합니다.
