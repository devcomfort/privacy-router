# 트러블슈팅 가이드

Privacy Router를 개발·평가하며 만난 주요 이슈와 해결 기록입니다.

---

## 목차

1. [rye sync 실패 — PyTorch/vLLM 인덱스 충돌](#1-rye-sync-실패--pytorchvllm-인덱스-충돌)
2. [llama.cpp GGUF 모델 정확도 17.6% — 전부 allow 반환](#2-llamacpp-gguf-모델-정확도-176--전부-allow-반환)
3. [EXAONE 4.5 33B — vLLM nightly 빌드 필요](#3-exaone-45-33b--vllm-nightly-빌드-필요)
4. [EXAONE 4.5 — 채팅 템플릿 문제로 로컬 경로 우회](#4-exaone-45--채팅-템플릿-문제로-로컬-경로-우회)
5. [GPU OOM — 모델별 gpu-memory-utilization 튜닝](#5-gpu-oom--모델별-gpu-memory-utilization-튜닝)
6. [Docker 빌드 실패 — COPY .env](#6-docker-빌드-실패--copy-env)
7. [SQLModel + SQLAlchemy 2.0 Relationship 비호환](#7-sqlmodel--sqlalchemy-20-relationship-비호환)
8. [EXAONE 4.5 정확도 35.3% — is_essential 오분류](#8-exaone-45-정확도-353--is_essential-오분류)

---

## 1. rye sync 실패 — PyTorch/vLLM 인덱스 충돌

**증상:** `rye sync` 실행 시 의존성 해석 오류로 실패합니다.

**원인:** `pyproject.toml`에 PyTorch, vLLM 커스텀 pip 인덱스를 추가한 적이 있습니다. 이 인덱스들이 PyPI와 다른 버전 번호의 패키지를 제공하면서 rye의 resolver가 충돌했습니다.

**해결:** 커스텀 인덱스를 모두 제거하고 PyPI만 사용하도록 변경했습니다. 호환 가능한 버전을 직접 고정합니다.

```toml
# 수정 전
[[tool.rye.sources]]
name = "pytorch"
url = "https://download.pytorch.org/whl/cu124"

[[tool.rye.sources]]
name = "vllm"
url = "https://wheels.vllm.ai/nightly"

# 수정 후 — 인덱스 제거, 버전 고정
dependencies = [
    "transformers>=5.10.0",
    "torch>=2.11.0",
    "torchvision>=0.26.0",
    ...
]
```

**수정 파일:** `pyproject.toml`, `requirements.lock`, `requirements-dev.lock`

---

## 2. llama.cpp GGUF 모델 정확도 17.6% — 전부 allow 반환

**증상:** llama-server(llama.cpp)로 서빙한 양자화 모델 전부가 17.6% 정확도를 기록했습니다. 비민감 케이스 3개만 통과하고, 나머지 14개 민감 케이스는 모두 `allow`를 반환했습니다.

| 모델 | 양자화 | 정확도 |
|---|---|---|
| Gemma 4 E2B | Q4_K_M | 17.6% |
| Gemma 4 E2B | Q8_0 | 17.6% |
| Gemma 4 E4B | Q4_K_M | 17.6% |
| EXAONE 1.2B | Q4_K_M | 17.6% |
| EXAONE 1.2B | Q8_0 | 17.6% |

**원인:** 두 가지가 겹쳤습니다.

1. **모델 용량 한계:** 1.2B~4B 파라미터 모델에 4비트(Q4_K_M)까지 양자화하면, extract.prompt가 요구하는 복합 추론(3-harm test, 맥락 분석, 한국어 처리)을 따라가지 못합니다.

2. **llama.cpp chat template 불일치:** llama-server가 자체적으로 chat template을 씌우는데, EXAONE 등 일부 모델은 학습 시 사용한 포맷과 달라서 system prompt를 무시하고 기본값("민감 정보 없음")을 출력했습니다.

**해결:** llama.cpp GGUF 대신 vLLM + BF16 전정밀도로 전환했습니다.

| 모델 | 양자화 | 정확도 | 엔진 |
|---|---|---|---|
| Gemma 4 E2B | BF16 | 64.7% | vLLM |
| Gemma 4 E4B | BF16 | 70.6% | vLLM |
| Gemma 4 12B | BF16 | 82.4% | vLLM |

17.6% → 64~82%로 정확도가 오른 것이 양자화 성능 저하가 원인이었음을 확인시켜줍니다.

**수정 파일:** `scripts/run_local_eval.sh`, `scripts/eval_all.py`

---

## 3. EXAONE 4.5 33B — vLLM nightly 빌드 필요

**증상:** PyPI의 안정 vLLM으로 `LGAI-EXAONE/EXAONE-4.5-33B-FP8`을 로드하면 unsupported architecture 오류가 발생합니다.

**원인:** EXAONE 4.5는 `EXAONEForCausalLM`이라는 커스텀 아키텍처를 사용합니다. 이 클래스는 vLLM nightly 빌드에만 등록되어 있고, 안정 릴리스에는 포함되지 않습니다.

**해결:** nightly 인덱스에서 vLLM을 설치합니다.

```bash
pip install vllm --extra-index-url https://wheels.vllm.ai/nightly
```

**검증:** 아래 명령이 성공하면 정상입니다.

```bash
python -c "from vllm.model_executor.models import EXAONEForCausalLM"
```

---

## 4. EXAONE 4.5 — 채팅 템플릿 문제로 로컬 경로 우회

**증상:** vLLM이 HuggingFace에서 EXAONE 4.5를 로드하지만 출력이 깨지거나 비어 있습니다.

**원인:** HuggingFace 레포의 `tokenizer_config.json`에 EXAONE 고유 형식의 `chat_template`이 들어 있습니다. vLLM이 이 템플릿을 자동 적용하면서, 우리가 보내는 OpenAI 호환 메시지(system → user)와 충돌해 프롬프트가 이중 래핑됩니다.

**해결:** 모델 파일을 로컬로 복사한 뒤 `tokenizer_config.json`에서 `chat_template` 필드를 제거했습니다.

```bash
cp -r ~/.cache/huggingface/hub/models--LGAI-EXAONE--EXAONE-4.5-33B-FP8 /tmp/exaone45-fp8-fixed
# /tmp/exaone45-fp8-fixed/tokenizer_config.json 편집 — chat_template 제거
```

`eval_all.py`에서 로컬 경로를 참조합니다:

```python
"exaone-4.5-33b-fp8": {
    "model": "openai//tmp/exaone45-fp8-fixed",
    "api_base": "http://localhost:8000/v1",
    ...
}
```

**수정 파일:** `/tmp/exaone45-fp8-fixed/tokenizer_config.json`, `scripts/eval_all.py`

---

## 5. GPU OOM — 모델별 gpu-memory-utilization 튜닝

**증상:** vLLM이 특정 모델 로딩 시 `torch.cuda.OutOfMemoryError`로 크래시됩니다.

**원인:** vLLM 기본값(`--gpu-memory-utilization 0.9`)이 GPU 메모리의 90%를 KV cache에 예약합니다. 모델 가중치까지 합산하면 VRAM을 초과합니다.

**해결:** 모델 크기에 따라 `--gpu-memory-utilization`을 개별 지정했습니다.

| 모델 | 파라미터 | gpu-memory-utilization |
|---|---|---|
| Gemma 4 E2B | 2B | 0.3 |
| Gemma 4 E4B | 4B | 0.4 |
| EXAONE 4.5 33B | 33B | 0.6 |

`--max-model-len 32768`을 추가해 context length를 제한하고 KV cache 메모리 부담을 줄였습니다.

**수정 파일:** `scripts/run_local_eval.sh`, `scripts/start_vllm.sh`

---

## 6. Docker 빌드 실패 — COPY .env

**증상:** `docker compose build` 시 `"/.env" not found` 오류로 실패합니다.

**원인:** Dockerfile에 `COPY .env ./`가 있었습니다. `.env`는 `.gitignore`에 포함되어 빌드 컨텍스트에 존재하지 않기 때문에 빌드가 실패합니다.

**해결:** 해당 줄을 제거했습니다. 환경 변수는 빌드 타임이 아니라 런타임에 `docker-compose.yml`의 `env_file: .env`로 주입합니다.

```dockerfile
# 수정 전
COPY .env ./
COPY . ./

# 수정 후
COPY . ./
```

**수정 파일:** `Dockerfile`

---

## 7. SQLModel + SQLAlchemy 2.0 Relationship 비호환

**증상:** 서버 시작 시 `InvalidRequestError` 또는 `TypeError: issubclass()` 오류로 크래시합니다.

**원인:** SQLModel의 `list["Model"]` 타입 어노테이션으로 정의한 Relationship이 SQLAlchemy 2.0의 mapper 설정과 충돌합니다. SQLAlchemy 2.0은 문자열 기반 `back_populates`를 요구하는데, SQLModel의 `Field(sa_relationship=...)` 방식이 이를 지원하지 않습니다.

**해결:** 모든 Relationship 선언을 제거했습니다. 코드베이스 전체에서 ORM relationship navigation을 사용하는 곳이 없었고(모든 쿼리가 명시적 `.where()` 사용), 사실상 dead code였습니다.

```python
# 수정 전
class AgentConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    logs: list["UsageLog"] = Relationship(back_populates="agent_config")

# 수정 후
class AgentConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
```

**수정 파일:** `db/models.py`

---

## 8. EXAONE 4.5 정확도 35.3% — is_essential 오분류

**증상:** EXAONE 4.5 33B FP8는 PII 탐지는 잘 하지만 종합 정확도가 35.3%에 그쳤습니다. `is_essential` 필드를 오분류해 라우터가 `mask_and_send` 대신 `prompt_user`를 선택하거나, 그 반대가 발생합니다.

**예시** (`PII 포함(creation)` 케이스):

- 입력: "주민등록번호 901212-1234567을 포함한 이메일을 작성해줘."
- 기대: `mask_and_send` — creation 맥락이므로 마스킹 후 전송
- EXAONE 출력: `prompt_user` — 핵심 목적으로 판단해 사용자 확인 요청

추출된 레코드 자체는 정확하지만, 주민등록번호의 `is_essential`이 `true`로 잘못 설정됩니다(`false`여야 함).

**원인:** `is_essential`은 민감 정보가 요청의 *부수적 요소*인지(마스킹 후 진행), *핵심 목적*인지(사용자 확인)를 맥락적으로 판단해야 합니다. EXAONE 4.5는 이 미묘한 판단에서 보수적으로 기울어, 마스킹이 적절한 경우에도 prompt_user를 기본값으로 선택합니다.

**현황:** 부분적으로만 완화됨. PII 추출은 가능하지만 라우팅 결정에는 더 강한 모델이 필요합니다. 프로덕션에서는 EXAONE 4.5를 추출 전용으로 쓰고, judge 모델(예: Gemini 3.1 Flash Lite)을 별도로 두는 구조를 권장합니다.

---

## 모델 성능 요약

| 모델 | 파라미터 | 엔진 | 양자화 | 정확도 | 평균 시간 |
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

**결론:** 로컬 배포에서는 BF16 전정밀도 + vLLM이 필수입니다. llama.cpp GGUF 양자화 모델은 이 프롬프트의 복잡도에 부적합합니다. 프로덕션에서는 OpenRouter의 Gemma 4 26B 또는 Gemini 3.1 Flash Lite가 저비용으로 100% 정확도를 제공합니다.
