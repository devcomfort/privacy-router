# 아키텍처

## 파이프라인

Privacy Router는 외부 LLM API에 도달하기 전에 에이전트가 생성한 모든 프롬프트를 가로채는 온디바이스 **Extractor → Judge → Router** 파이프라인입니다.

```text
에이전트 프롬프트
    ↓
┌─────────────────────────────────────────────────────────────┐
│  Extractor (facade, precision="default"|"high")             │
│  ├── ExtractorCore: Socratic 민감도 탐지                     │
│  │   → 자유 형식 SCREAMING_CASE 카테고리                    │
│  │   → 최소 entity span (조사·부사 제외)                    │
│  │   → is_required.value (마스킹 후 외부 처리 가능 여부)    │
│  └── Critic: 후검토 (precision="high"일 때만)               │
│      → 1단계에서 놓친 span 탐지                             │
│      → 빈 텍스트에도 실행                                   │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  질의 집계 + Judge (규칙 기반, LLM 호출 없음)                │
│  표준 정책 결정:                                             │
│    → 민감하지 않음:                   allow                 │
│    → 모든 span이 필수가 아님:          selective_mask        │
│    → 필수 span 또는 안전한 span 없음:   block                 │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
                   ┌───────┴───────┐
                   ↓               ↓
              외부 API        로컬 API
              (원문/마스킹)   (차단 경로)
                   ↓
              마스킹 응답 복원
```

![Privacy Router 보호 흐름: 안전한 프롬프트는 원문으로 외부 모델에 전달하고, 마스킹 가능한 프롬프트는 자리표시자로 치환한 뒤 복원하며, 필수 값 또는 안전한 span이 없는 프롬프트는 로컬에 남긴다.](../../assets/generated/privacy-router-consumer-flow.svg)

## 런타임 모델 바인딩

파이프라인은 이름이 붙은 컴포넌트마다 모델을 하나씩 두지 않고, 다음 세 가지 런타임 역할에 모델을 바인딩합니다.

| 런타임 역할 | 현재 모델 | 신뢰 경계 | 사용 위치 |
|---|---|---|---|
| 판정 모델(Decision Model) | Gemma 4 26B (`openai/google/gemma-4-26b-local`) | 로컬 전용 | ExtractorCore와 선택적 고정밀 Critic; 민감도, span, 카테고리, 중첩 `is_required` 반환 |
| 로컬 모델(Local Model) | Gemma 4 26B (동일 endpoint) | 로컬 전용 | 정확한 민감 값이 필요한 요청의 생성 |
| 외부 모델(External Model) | OpenRouter Gemma 4 26B (`openrouter/google/gemma-4-26b-a4b-it`) | 외부 | 민감하지 않은 요청 또는 검증된 마스킹 요청의 생성 |

`Judge`는 규칙 기반 정책 코드이고 `Router`는 결정적 실행 코드입니다. 둘 다 LLM 바인딩을 갖지 않습니다. `Extractor`, `Critic`, `Judge`라는 컴포넌트 이름은 유지하지만, 서로 독립적으로 선택하는 모델 역할은 아닙니다.

## 컴포넌트 아키텍처

탐지기 패키지와 기존 Judge/Router 호환 파이프라인은 필수 여부(requiredness) 전환 기간 동안 함께 존재합니다.

```text
agents/extractor/
├── __init__.py       # 패키지 공개 API
├── schemas.py        # 공통 Pydantic 계약
├── parser.py         # 후보 타입과 공통 parser helper
├── normalizer.py     # offset 조정과 uid 발급
├── registry.py       # PrivacyExtractor와 DetectorRegistry
├── llm/
│   ├── __init__.py   # LLM 공개 API
│   ├── extractor.py
│   ├── parser.py
│   └── llm_extract.prompt
├── presidio/
│   ├── __init__.py   # Presidio 공개 API
│   ├── extractor.py
│   └── parser.py
├── opf/
│   ├── __init__.py   # OPF 공개 API
│   ├── extractor.py
│   └── parser.py
└── lfm/
    ├── __init__.py   # LFM 공개 API
    ├── extractor.py
    └── parser.py
```

각 백엔드 패키지는 자체 `__init__.py`를 통해 extractor와 parser를 공개하며, `agents.extractor.__init__`은 전체 공개 API를 다시 내보냅니다.

```text
Judge (규칙 기반) — Router가 주입
Router — 정책과 실행 경로의 매핑
```

## 탐지기 계약(구현된 탐지 계층)

백엔드와 무관한 탐지기 계약은 `agents/extractor`에 구현되어 있습니다. 현재
`ExtractorCore`/`Extractor` 경로는 기존 Judge와 Router를 위한 호환 계층으로
남아 있으며, 필수 여부 전환이 완료될 때까지 함께 사용합니다. 탐지기 계층은
LLM, Presidio, OpenAI Privacy Filter(OPF), LFM2.5의 출력을 하나의 개인정보
entity 형식으로 정규화합니다. 탐지는 정책 판단, 마스킹, 마스킹 해제 또는
영속화를 수행하지 않습니다.

```text
탐지기 adapter
  → 정확한 span과 offset 검증
  → kind와 tag 정규화
  → occurrence별 uid 발급
  → PrivacyEntity 반환
```

`PrivacyEntity` 필드:

| 필드 | 의미 |
|---|---|
| `id: UUID` | entity record의 내부 식별자 |
| `kind: "contextual" \| "structural"` | 값이 개인정보와 관련된 이유 |
| `tag: str` | `EMAIL`, `API_KEY` 같은 표준 짧은 라벨 |
| `uid: str` | `secrets`로 생성한 128비트 무작위 occurrence token |
| `span: str` | 입력에서 탐지된 정확한 민감 부분 문자열 |
| `offsets: tuple[int, int]` | 0부터 시작하는 유니코드 code-point 기준 `(start, end)`; end는 제외 |
| `reason: str \| None` | 탐지기가 제공한 선택적 설명 |
| `confidence: float \| None` | `[0, 1]` 범위의 선택적 탐지 점수 |
| `native_label: str \| None` | 정규화 전 백엔드 라벨 |
| `native_metadata` | recognizer 식별자를 포함한 백엔드별 metadata |
| `detection_method` | `regex`, `ner`, `token_classifier`, `llm`, `hybrid` 중 하나 |
| `is_required` | 중첩 평가. `value`는 `true`, `false`, `null`이고 모든 상태에 `reason`이 필요 |

외부에 표시할 식별자는 저장하지 않고 계산합니다.

```python
@property
def identifier(self) -> str:
    return f"{self.tag}#{self.uid}"
```

`uid`는 `span`의 암호학적 hash가 아닌 불투명한 무작위 token입니다. normalizer는
유지되는 각 occurrence에 새 값을 발급하고 현재 extraction result 안에서 충돌을
확인하며, 같은 값이라는 이유만으로 동일한 occurrence를 합치지 않습니다.

여러 recognizer가 같은 범위나 겹치는 범위를 보고하더라도 유효한 supplied offset은
권위 있는 근거로 취급합니다. 유지되는 각 evidence item은 자체 `uid`를 받습니다.
유효한 offset이 없는 후보만 span의 아직 사용하지 않은 정확한 occurrence에
할당됩니다.

`DetectorRunProvenance`는 entity가 아니라 result 수준에 저장합니다.
`detector_type`으로 구분되는 union이며, 모든 run에는 구현 버전을 포함한 완전한
kebab-case `detector_id`가 필요합니다.

```text
llm:     privacy-router-llm-extractor-v1-0-0
presidio: microsoft-presidio-analyzer-v2-2-358
opf:     openai-privacy-filter-v1-0-0
lfm:     liquidai-lfm2-5-encoder-350m-pii-detector-v1-0-0
```

각 run은 `run_id`, `status`(`complete`, `partial`, `failed`),
`external_opt_in`, adapter 버전, 백엔드별 모델·설정 revision을 기록합니다.
LLM run은 모델과 prompt revision을 추가로 기록할 수 있고, Presidio run은 설정된
recognizer 목록을 기록하며, LFM run은 decoder revision을 기록할 수 있습니다.

Presidio의 한 analyzer run은 여러 recognizer의 entity를 만들 수 있습니다. 따라서
run 수준 provenance에는 설정된 recognizer 목록을 보존하고, 각 entity의
`native_metadata`에는 제공된 `recognizer_name`과 `recognizer_identifier`를 보존합니다.

`DetectionResult.detector_runs`는 entity가 0개이거나 탐지에 실패한 경우에도 채워집니다.
entity의 `run_id`는 해당 entity를 만든 정확한 run을 가리킵니다. 이를 통해
정상적인 미탐지 결과와 실패한 run을 구분해 감사할 수 있으며, 모든 entity에
provenance를 반복 저장하지 않아도 됩니다.

OPF, Presidio, LFM은 LLM extractor와 같은 evidence를 제공하지 않으므로 `reason`과
`confidence`는 계속 선택적입니다.

`DetectionResult`는 `detector_runs`, entity 목록, `complete`/`partial`/`failed`
상태, 진단 정보를 포함합니다. `uid → value`를 별도로 복사해 저장하지 않습니다.
result는 consumer가 소유한 helper 또는 storage adapter를 통해
`identifier → span` mapping을 파생합니다. raw span은 신뢰된 로컬 탐지기에 들어갈
수 있지만 telemetry에는 절대 들어가면 안 됩니다. LLM extractor는 기본적으로
로컬 전용이며, raw input을 외부 모델에 보내려면 요청마다 명시적인 opt-in이
필요하고 해당 run에 기록해야 합니다. 그렇지 않으면 fail closed합니다.

## 필수 여부 이름 전환

활성 호환 파이프라인을 탐지기 계약에 맞춥니다. `ExtractionRecord`, prompt, Judge,
Middle-Man, Masker, 영속화 계층, API metadata의 필드명을 기존 이름에서
`is_required`로 바꿉니다. canonical 형태는
`Requiredness(value: bool | null, reason: str)`입니다. `value=true`는 정확한 값이
답변 또는 처리에 필요해 로컬에 남겨야 함을 뜻하고, `value=false`는 값을 마스킹한
뒤 외부 처리할 수 있음을 뜻합니다. `archive/` 아래 historical evaluation
artifact는 원래 schema를 유지하며 migration하지 않습니다.

원문과 offset은 HTMX fragment 렌더링 경로에만 전달합니다. 공개 JSON payload와
`redact_extraction_records`는 raw span과 offset을 계속 제외합니다. 브라우저는
fragment의 검증된 offset으로 마스킹 대상(`is_required.value=false`)을 입력 위에
표시하고 record block과 연결합니다. 양쪽에 hover 또는 keyboard focus가 들어오면
대응 요소를 함께 강조하며, 원문 값은 API JSON metadata로 반환하지 않습니다.

외부에 표시할 entity 식별자는 저장하지 않고 계산합니다.

```python
@property
def identifier(self) -> str:
    return f"{self.tag}#{self.uid}"
```

## 후속 전환 결정

초기 탐지기 adapter는 구현되어 있습니다. 기존 파이프라인을 교체하기 전에 다음
결정을 고정해야 합니다.

1. 표준 `tag` vocabulary와 백엔드별 native-label mapping
2. 탐지기 간 merge 및 overlap 규칙. 같은 run에서 동일 offset이 중복되어도 normalizer는 별도 evidence로 보존
3. `partial` 및 `failed` result의 실패 동작. 이를 정상적인 미탐지 결과로 해석하면 안 됨
4. consumer가 소유하는 `uid → span` 저장 경계
5. LLM 신뢰 정책. 기본은 로컬 전용이며, 외부 모델의 raw-input extraction은 명시적 opt-in일 때만 허용하고 그 외에는 fail closed

## 선택적 탐지기 설치

기본 설치에는 LiteLLM 기반 LLM extractor가 포함됩니다. 규칙·모델 기반 탐지기
extra는 다음과 같이 설치합니다.

```bash
uv sync --extra privacy-detectors --extra local-inference
```

`privacy-detectors`는 immutable git revision
`f7f00ca7fb869683eb732c010299d901457f19c3`의 `presidio-analyzer`와 OpenAI
Privacy Filter 패키지를 설치합니다. `local-inference`는 LFM2.5에 필요한
Transformers/PyTorch runtime을 제공합니다. LFM adapter는 model file과 decoder
helper를 revision `b8c9cf3d2d6ae52501b35a27ba46f271449c9ce2`에 고정하며,
`trust_remote_code=True`는 해당 고정 revision에 대해서만 활성화합니다.

## 로컬 HTMX 데모

Svelte `/demo` route는 제거되었습니다. FastAPI가 `GET /demo`에서
`server/templates/demo.html`을 제공하고, vendored HTMX runtime은
`/demo-assets/htmx.min.js`에서 제공합니다.

```text
POST /api/demo/key       → dev 모드 브라우저 key fragment
POST /api/demo/router    → 인증된 단일 router HTML/JSON result
POST /api/demo/run-all   → 인증된 8개 로컬 router batch
```

Demo는 생성한 `pr-*` key를 브라우저 `sessionStorage`에 저장하고, 보호된 두 demo
endpoint에 bearer header로 전송합니다. `dev`는 기본적으로 `127.0.0.1`에
bind하며, `privacy-router dev --host 0.0.0.0`을 사용하면 명시적으로 선택한
개발 보안 상태에서 listener와 dev key 발급 범위를 넓힙니다. 인증된 `serve`
상태에서는 자동 demo-key 발급을 제공하지 않습니다.

하이라이트된 span과 record block은 안정적인 로컬 식별자를 공유합니다. 양쪽은
hover 또는 keyboard focus에서 함께 강조되고, 색상만으로 의미를 전달하지 않도록
텍스트 기반 마스킹 라벨도 표시합니다.

## Middle-Man 아키텍처

Middle-Man Agent는 파이프라인을 조정하고 사용자 상호작용을 관리합니다.

```text
agents/router/
├── middle_man.py      # Middle-Man Agent (의사결정 로직)
├── cache.py           # SQLite key-value cache
├── router.py          # Router (정책 → 실행 경로)
└── schemas.py         # schema 정의
```

### 의사결정 흐름

```python
def process_with_middle_man(text, metadata):
    # 1. cache 확인과 함께 extraction
    extraction = extract_with_cache(text, metadata.cache_strategy)

    # 2. Middle-Man 결정
    if not extraction.is_sensitive:
        return auto_process(text, extraction)

    if metadata.auto_mask:
        if all_confident(extraction, metadata.masking_threshold):
            return auto_process(text, extraction)
        else:
            return ask_user(text, extraction)
    else:
        return ask_user(text, extraction)
```

### 캐시 전략

| 전략 | 설명 | DB 작업 |
|---|---|---|
| `auto` | 기본값. HIT이면 사용하고 MISS이면 실행 후 저장 | SELECT / INSERT |
| `bypass` | 항상 다시 실행하고 저장하지 않음 | 없음 |
| `refresh` | 다시 실행하고 cache를 덮어씀 | UPSERT |
| `delete` | 삭제한 뒤 다시 실행하고 저장하지 않음 | DELETE |

캐시에는 LLM 응답이 아니라 **추출 결과만** 저장합니다.
캐시 키는 입력 텍스트를 4KB chunk로 나누고 병렬 hash한 뒤 결합하여 다시 hash한 값입니다.

## 응답 형식

### 사례 1: 자동 처리(기본)

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
  "privacy_router": {
    "status": "completed",
    "is_sensitive": true,
    "extraction_records": [...],
    "policy_action": "selective_mask",
    "masking_applied": true,
    "cached": false
  }
}
```

### 사례 2: 사용자 입력 필요

공개 JSON의 `span`은 원문이 아니라 자리표시자이며, raw span과 offset은 포함하지 않습니다.

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": null}, "finish_reason": "requires_action"}],
  "privacy_router": {
    "status": "needs_input",
    "question": "민감한 데이터가 감지되었습니다. 어떻게 처리할까요?",
    "is_sensitive": true,
    "record_count": 2,
    "required_count": 1,
    "extraction_records": [
      {"index": 0, "category": "UNPUBLISHED_RESEARCH_CONCEPT", "span": "<research-concept>", "is_required": {"value": true, "reason": "응답의 핵심 연구 내용"}, "confidence": 0.95},
      {"index": 1, "category": "INTERNAL_PROJECT_NAME", "span": "<internal-project-name>", "is_required": {"value": false, "reason": "이름을 가려도 요청 의미 유지"}, "confidence": 0.90}
    ],
    "default_action": "block"
  },
  "options": [
    {"id": "auto", "label": "자동", "description": "시스템 결정을 따름"},
    {"id": "mask_all", "label": "모두 마스킹", "description": "모든 민감 데이터를 마스킹"},
    {"id": "mask_maskable", "label": "마스킹 가능한 값", "description": "is_required.value=false인 값만 마스킹"},
    {"id": "block", "label": "로컬 처리", "description": "외부 API 대신 로컬 모델 사용"},
    {"id": "custom", "label": "사용자 지정", "description": "record별 선택"}
  ],
  "default_option": "auto"
}
```

### 사례 3: 사용자 선택 후 재요청

```json
{
  "model": "privacy-router",
  "messages": [
    {"role": "user", "content": "원문..."},
    {"role": "assistant", "content": null, "privacy_router": {"status": "needs_input", "...": "..."}},
    {"role": "user", "content": null, "privacy_router": {
      "selected_option": "custom",
      "overrides": [
        {"record_index": 0, "is_required": {"value": true, "reason": "원문 값이 답변에 필요함"}},
        {"record_index": 2, "remove": true}
      ]
    }}
  ]
}
```

## API와 MCP 비교

| 항목 | API(OpenAI 호환) | MCP Server |
|---|---|---|
| 진입점 | `server/api/routes/proxy.py` | `server/mcp/tools.py` |
| 호출자 | 외부 client | AI agent |
| Middle-Man | pipeline 내부 자동 실행 | agent가 `review()`/`decide()`를 직접 호출 |
| 사용자 prompt | `status: needs_input` 응답 후 client가 질문 | agent가 직접 질문 |
| 상태 | 무상태(client가 context 관리) | 무상태(agent가 context 관리) |
| Cache | `cache_strategy` metadata | `no_cache` flag |

## API 사용 예시

```python
# 기본 모드(빠름, LLM 1회 호출)
extractor = Extractor()
result = extractor.extract("개인 식별자 검토")

# 고정밀 모드(Critic 포함, LLM 2회 호출)
extractor = Extractor(precision="high")
result = extractor.extract("개인 식별자 검토")

# 의존성 주입(테스트용)
extractor = Extractor(core=my_core, critic=my_critic)
```

## 탐지 표면

### 형태 기반

PII, 전화번호, 이메일, 실명처럼 패턴으로 탐지할 수 있는 값입니다.

- 정확도: 83.3%(Gemma4 E4B)

### 맥락 기반

사업 비밀, 연구 아이디어, 전략, 예산, 내부 URL처럼 문맥 이해가 필요한 값입니다.

- 정확도: 62.5%(Gemma4 E4B)

`kind`는 값을 찾은 방법이 아니라 해당 값이 개인정보와 관련된 성질을 설명합니다.
Structural entity는 정규식, NER model 또는 token classifier로 탐지할 수 있고,
contextual entity는 일반적으로 LLM 또는 다른 문맥 인식 탐지기로 탐지합니다.
실제로 사용한 방법은 `detection_method`가 별도로 기록합니다.

## 프롬프트

| 파일 | 위치 | 목적 |
|---|---|---|
| `extractor.prompt` | `agents/extractor/extract.prompt` | 기본 extraction(Socratic, 298줄) |
| `extractor.short.prompt` | `agents/extractor/extract.short.prompt` | 2B 이하 모델(24줄) |
| `extractor.socratic.prompt` | `agents/extractor/extract.socratic.prompt` | Socratic CoT(131줄) |
| `extractor.fixed.prompt` | `agents/extractor/extract.fixed.prompt` | 고정 카테고리(232줄) |
| `critic.prompt` | `agents/extractor/critic.prompt` | 2차 비평(92줄) |
| `llm_extract.prompt` | `agents/extractor/llm/llm_extract.prompt` | 새 LiteLLM extractor 출력 계약 |
| `judge.prompt` | `agents/judge/classify.prompt` | 분류·정책 참고용 |

## 모델 선택

```text
모델 크기   → 프롬프트
─────────────────────────────
≤ 2B         → extract.short.prompt
3B ~ 4B      → extract.prompt (기본)
> 4B         → extract.prompt 또는 extract.socratic.prompt
```

## 컴포넌트

| 컴포넌트 | 파일 | 설명 |
|---|---|---|
| Extractor | `agents/extractor/extractor.py` | 현재 호환 facade |
| ExtractorCore | `agents/extractor/extractor_core.py` | 현재 호환 extraction 로직 |
| LLMExtractor | `agents/extractor/llm/extractor.py` | LiteLLM 기반 구조화 탐지기 |
| PresidioExtractor | `agents/extractor/presidio/extractor.py` | Presidio 탐지기 adapter |
| OPFExtractor | `agents/extractor/opf/extractor.py` | OpenAI Privacy Filter adapter |
| LFMExtractor | `agents/extractor/lfm/extractor.py` | LFM2.5 PII 탐지기 adapter |
| 탐지기 parser | `agents/extractor/{llm,presidio,opf,lfm}/parser.py` | native payload 변환 |
| Normalizer | `agents/extractor/normalizer.py` | offset 조정과 token 발급 |
| 탐지기 registry | `agents/extractor/registry.py` | 이름 기반 탐지기 dispatch |
| Critic | `agents/extractor/critic.py` | 현재 호환 후검토 |
| Judge | `agents/judge/judge.py` | 규칙 기반 정책 결정 |
| Router | `agents/router/router.py` | 파이프라인 조정 |
| MiddleMan | `agents/router/middle_man.py` | 사용자 상호작용 조정 |
| Masker | `agents/masker/masker.py` | span → 자리표시자 치환 |
| Cache | `agents/router/cache.py` | chat_id 기반 상태 관리 |

## 기술 스택

| 계층 | 기술 |
|---|---|
| 백엔드 | FastAPI + SQLModel |
| 데이터베이스 | SQLite(개발) / PostgreSQL(운영) |
| 모델 | 로컬·외부 모델 항목을 저장하는 SQLite registry |
| 프론트엔드 | SvelteKit(SSG) + FastAPI가 제공하는 HTMX 데모 |
| 암호화 | Fernet(AES-128-CBC + HMAC-SHA256) |
| 통합 | OpenAI 호환 API + MCP Server |

## 테스트

테스트는 두 종류의 suite로 나눕니다.

### 단위 테스트(mock 기반)

- **위치**: `tests/core/`, `tests/sanity/`, `server/tests/`
- **목적**: 코드 구조와 로직 검증
- **방법**: `@patch`로 LLM 호출을 mock
- **대상**: 파이프라인 경로, validation 로직, masking/hydration, 정책 결정, 오류 처리
- **실행**: `python3 -m pytest tests/core/ tests/sanity/ server/tests/ -v`
- **소요 시간**: 약 30초

### 평가 suite(실제 LLM 호출)

- **위치**: `scripts/eval_runner.py`, `scripts/eval_all.py`
- **목적**: LLM 출력 품질 검증
- **방법**: 실제 LLM 호출을 N≥5회 반복
- **대상**: 민감도 탐지율, 정책 결정 정확도, 형태·맥락 탐지, JSON 출력
- **실행**: `python3 scripts/eval_runner.py --model gemma4-e4b-openrouter --trials 5`
- **소요 시간**: 수 분에서 수십 분

### 분리하는 이유

mock 없이 실행한 테스트의 실패는 코드 오류와 LLM 출력 변동을 구분할 수 없습니다.

## 관련 문서

- [탐지](../user/detection.md) — Socratic 민감도 탐지 framework와 예시
- [질의 집계 사양](query-aggregation-spec.md) — span evidence, 질의 수준 변수, fail-closed routing 불변식
- [데이터 흐름](data-flow.md) — 데이터 형식, 정책 action, masking/hydration 경계
- [Fail-closed routing](fail-closed-routing.md) — 고정 실행 경로, retry, 안전한 오류, streaming 중단
- [Database ERD](database-erd.md) — SQLite schema
- [Config 파일](config-files.md) — YAML과 DB 설정 구조
- [Integration 아키텍처](integration-architecture.md) — Hermes Agent, OpenCode, LiteLLM 통합
- [보안](../user/security.md) — threat model과 암호화

## 변경 이력

- 2026-09-01 — 아키텍처 문서 전체를 한국어로 다시 작성했습니다. 기술 식별자와 API 계약은 유지하고, 활성 requiredness·HTMX·응답 보안 설명을 한국어로 통일했습니다.

- 2026-09-01 — requiredness 이름 전환과 로컬 데모 span 연결 하이라이트 설계를 승인했습니다. 활성 pipeline 호출부는 기존 필드명에서 중첩 `is_required` 계약으로 전환하고, historical evaluation artifact는 변경하지 않습니다.

- 2026-08-28 — `PrivacyEntity`, occurrence별 불투명 `uid`, 계산되는 `tag#uid` 식별자, result 수준의 구분된 detector provenance, 중첩 requiredness를 중심으로 탐지기 abstraction을 구현했습니다. Judge, Router, 현재 pipeline 호출부는 설계상 아직 변경하지 않았습니다.

- 2026-08-28 — Svelte demo route를 FastAPI가 제공하는 HTMX로 교체하고, 로컬 asset 제공, dev key 발급, router inspection, 8개 사례 batch 실행을 추가했습니다. 재사용 가능한 `PrivacyRouter` extraction 상태와 로컬 backend 실패 fragment도 추가했습니다.

## 영향 범위

- **코드**: 활성 `ExtractorCore`/`Extractor`, Judge, Middle-Man, Masker, masking persistence, demo payload, prompt 계약을 중첩 `is_required`로 전환합니다. `archive/` 평가 artifact는 변경하지 않습니다.
- **스킬**: 없음.
- **문서**: 이 아키텍처 문서가 canonical 계약 기록이며, 현재 탐지·API 안내는 `is_required`를 사용합니다.
- **결정**: `Requiredness.value=true`이면 정확한 값을 로컬에 유지하고, `value=false`이면 마스킹할 수 있습니다. Demo는 검증된 offset과 record block을 연결하지만 raw 값을 JSON으로 반환하지 않습니다.
- **보관·버전 관리**: 별도 archive를 만들지 않습니다. historical 평가 출력은 원래 schema를 가진 record로 유지합니다.
- **검증**: migration, API payload, escaping/offset, hover/focus, 전체 pipeline 회귀 테스트와 agent-browser smoke 검증을 추가합니다.
- **업데이트하지 않는 이유**: 이 전환과 충돌하는 다른 현재 결정은 없습니다. 기존 저장 column은 versioned copy를 만들지 않고 in-place migration합니다.
