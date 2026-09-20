# Privacy Router

LLM 애플리케이션이 외부로 보낼 텍스트를 검사하고, **원문 전달·마스킹 후 전달·로컬 처리 중 어떤 행동이 적절한지 권고하는 Python 라이브러리**입니다. 정보를 가리면 작업 자체가 불가능해지는 경우와, 가려도 작업을 완료할 수 있는 경우를 구분합니다.

공개 정보도 추출하되 기밀 여부와 작업 필요성을 독립적으로 판단합니다. 판단 근거가 부족하면 미판정으로 남깁니다. **권고는 전송 허가가 아닙니다.** 대상 모델 선택·호출, 도구 실행, 실제 외부 전송은 호출자가 결정하며 자동 검출에는 누락과 오판이 있을 수 있습니다.

[설치](#설치) · [설정](#설정) · [사용법](#기본-사용법) · [판정과 권장 행동](#판정과-권장-행동) · [웹 데모](#웹-데모) · [문서](#문서)

## 구성과 처리 흐름

```text
전체 작업 원문 + 선택적 의도 어노테이션
  → 의도 분석 또는 제공된 어노테이션 검증
  → Cachier 조회 → 적중하면 재사용 / 미적중이면 Extractor 실행
  → Policy 행동 권고
  → 보호 구간 마스킹 → 원문 복원 일치 확인
  → 완전한 새 추출 결과를 캐시에 저장
  → 호출자에게 결과 반환 (대상 모델 호출·외부 전송 없음)
```

| 컴포넌트 | 역할 |
|---|---|
| `Annotator` / `IntentAnalyzer` | 작업 목표·동작·완료 조건·채널·미해결 사항을 정확한 원문에 결합. 상위 애플리케이션이 직접 제공하거나 신뢰된 로컬 모델로 분석 |
| `Extractor` | 공개·비공개 항목과 원문 위치, 항목별 두 판단과 이유, 전체 마스킹 영향을 한 추출 단계에서 반환 |
| `Cachier` | 세션·원문·전체 문맥·의도·탐지 규칙이 같은 결과의 메타데이터 재사용 |
| `Policy` / `HeuristicPolicy` | 이미 확보한 검사 근거만으로 행동 권고. 추가 LLM 호출 없음 |
| `Masker` | 보호 구간을 요청 단위의 불투명 플레이스홀더로 치환하고 계약에 따라 복원 |
| `Router` / `PrivacyRouter` | 위 컴포넌트를 연결하고 실제 단계별 실행 상태를 콜백으로 전달 |

각 컴포넌트는 독립적으로 사용할 수 있습니다. 별도의 `LLMExtractor`, `PresidioExtractor`, `OPFExtractor`, `LFMExtractor`와 `DetectorRegistry`는 정규화된 `DetectionResult`를 제공합니다. 이 탐지기들이 작업 의도와 마스킹 영향을 모두 평가하는 것은 아니며, PII 전용 탐지기의 작업 필요성은 미판정입니다.

입력 계약은 텍스트입니다. SDK 메시지 객체·첨부파일의 검사와 원래 구조에 결과를 적용하는 어댑터는 포함하지 않습니다. 코어 wheel에는 서버·인증·데이터베이스·웹 UI가 없으며, [`demo/`](demo/)는 별도 시연 애플리케이션입니다.

## 설치

Python **3.13 이상**과 [uv](https://docs.astral.sh/uv/)가 필요합니다. 저장소 루트에서 실행합니다.

```bash
git clone https://github.com/devcomfort/privacy-router.git
cd privacy-router
uv sync --frozen
```

필요한 탐지기 의존성만 추가로 설치합니다. 모델 가중치와 추론 서버는 별도로 준비해야 합니다.

```bash
uv sync --frozen --extra local-inference      # transformers 기반 로컬 추론
uv sync --frozen --extra privacy-detectors    # Presidio·OpenAI Privacy Filter
```

## 설정

의도 분석과 LLM 추출은 현재 작업 디렉터리의 [`.privacy-router.config.yaml`](.privacy-router.config.yaml)을 읽습니다.

- `models`: 모델 ID, `location`, 엔드포인트 등록. `decision.model`은 등록된 `local` 모델이어야 합니다.
- `decision`: `IntentAnalyzer`와 `Extractor`의 기본 모델·엔드포인트·출력 토큰 한도. 생성자의 `model`, `api_base`, `max_tokens`로 재정의할 수 있습니다.
- `PRIVACY_ROUTER_PROFILE`: YAML에 정의된 프로필 선택.
- `PRIVACY_ROUTER_TRUSTED_LOCAL_MODEL_HOSTS`: loopback 외에 신뢰할 로컬 모델 호스트를 명시적으로 허용하는 쉼표 구분 목록. 등록은 해당 호스트에 원문을 보내도 된다는 운영자의 신뢰 결정입니다.

체크인된 기본값은 `openai/google/gemma-4-26b-local`, `http://127.0.0.1:8011/v1`입니다. 설정만으로 서버가 시작되지는 않습니다. 모델 ID와 주소를 실제 추론 서버에 맞춘 뒤 아래 LLM 예제를 실행하세요. 연결 실패 시 외부 모델로 자동 대체하지 않습니다.

비밀값이 필요하면 [`.env.example`](.env.example)을 참고해 `.env`에 설정하고 Git에 커밋하지 않습니다. 기본 로컬 호출은 호환성용 더미 키를 사용합니다. 인증된 서버에는 `IntentAnalyzer(call_structured=...)`와 `Extractor(core=ExtractorCore(call_structured=...))`로 클라이언트를 주입하세요. 콜백은 [`shared.llm.call_llm_structured`](src/shared/llm.py)의 규격으로 전달받은 응답 모델 인스턴스를 반환하며, `component`는 `annotator` 또는 `extractor`입니다. 모델·엔드포인트 검증은 그대로 적용됩니다.

`LLM_MODEL`은 일반 LLM 호출 함수의 기본값입니다. `.env.example`의 `EXTRACTOR_MODEL`, `LOCAL_API_BASE`만 바꾸어도 위 두 분석기의 YAML 설정이 바뀌는 것은 아닙니다. YAML의 `local`·`external` 모델 설정도 `PrivacyRouter`의 자동 대상 모델 선택이나 전송을 활성화하지 않습니다.

## 기본 사용법

### 모델 없이 마스킹과 복원

다음 예제는 모델이나 서버 없이 실행할 수 있습니다. 값을 찾는 작업은 호출자가 이미 수행했다고 가정합니다.

```python
from masker import Masker

text = "내부 참조 코드 ALPHA-42를 확인하세요."
value = "ALPHA-42"
start = text.index(value)

masker = Masker()
masked = masker.mask(
    text,
    [{"span": value, "start": start, "end": start + len(value)}],
)
restored = masker.hydrate(masked.masked_text, masked.contract)
assert restored.hydrated_text == text
assert value not in masked.masked_text
print(masked.masked_text)
```

출력 토큰은 `SENSITIVE_DATA#` 뒤에 무작위 8자리 16진수가 붙는 형태입니다. **원문을 해시하거나 암호화한 값이 아닙니다.** `MaskingContract`가 토큰과 원래 값의 매핑을 보관하므로 계약은 외부에 보내지 않습니다. 미등록 플레이스홀더는 `HydrationError`로 거부하고, 응답에서 사라진 토큰은 임의로 채우지 않습니다. 별도의 Fernet 암호화 유틸리티는 [`src/masker/crypto.py`](src/masker/crypto.py)에 있습니다.

`Masker`를 직접 호출하면 전달한 위치를 처리합니다. **반복 값 전체 검색과 겹친 보호 구간 병합은 `PrivacyRouter`가 담당**합니다. 직접 통합하는 호출자는 보호할 모든 위치를 준비해야 합니다.

### 라우터 사용과 실행 상태 전파

설정한 로컬 모델이 실행 중일 때 사용하는 예제입니다. 코드 블록은 각각 `uv run python` 환경에서 실행할 수 있습니다.

```python
from agents import Extractor, IntentAnalyzer
from cachier import Cachier
from router import PrivacyRouter, Router

text = "내부 참조 코드 ALPHA-42가 들어갈 안내문 초안만 작성해줘. 실제 발송하지 마."
router: Router = PrivacyRouter(
    annotator=IntentAnalyzer(),
    extractor=Extractor(),
    cache=Cachier(),
    detector_fingerprint="example-model-prompt-rules-v1",
)
result = router.route(
    text,
    namespace="example-session",
    on_status=lambda event: print(event.sequence, event.stage, event.state),
)
print(result.recommendation.action, result.recommendation.reason)

# 동일한 원문·문맥·의도를 재사용한다. 완전한 결과가 캐시되었다면 모델 호출은 없다.
replayed = router.route(text, namespace="example-session", intent=result.intent)
print(replayed.cache_hit)
```

`route(text, *, namespace, history=(), intent=None, on_status=None)`는 분석 결과, 권고, 마스킹 계약과 복원 결과를 반환합니다. 기본 `policy`와 `masker`도 생성자에서 교체할 수 있습니다.

마스킹된 텍스트는 `result.masking.masked_text`, 복원 계약은 `result.masking.contract`, 복원 확인 결과는 `result.hydration.hydrated_text`입니다. `mask_then_share`이면 마스킹된 텍스트를 전달 후보로 검토하되 별도의 권한 확인이 필요합니다. 계약과 복원 원문은 외부에 보내지 않습니다.

- **전체 작업 문맥:** 필요한 이전 대화를 `text`에 포함하세요. `history`는 캐시 격리용이며 모델 입력에 자동으로 합쳐지지 않습니다.
- **호출 수:** 기본 흐름은 의도 분석과 단일 패스 추출의 두 단계입니다. 의도를 제공하면 분석을 건너뛰고, 캐시에 적중하면 추출을 건너뜁니다. 구조화 응답 재시도로 실제 호출 수는 늘어날 수 있습니다.
- **캐시 범위:** `namespace`는 호출자가 정하는 세션·권한 범위입니다. `detector_fingerprint`는 모델·프롬프트·규칙이 바뀌면 함께 바꿔야 합니다. 캐시나 모델 클라이언트를 여러 스레드에서 공유하면 호출자가 동기화합니다.

`RouterEvent`에는 실행 ID·순번·단계·상태·경과 시간·고정 코드만 들어가며 원문, 의도 내용, 모델 설명, 예외 메시지는 넣지 않습니다. 단계는 `validation`, `annotation`, `cache`, `extraction`, `policy`, `masking`이며 `run`이 전체 실행을 나타냅니다. 상태는 `started`, `completed`, `skipped`, `failed`입니다. 이벤트는 실제 작업 전후에 동기적으로 전달되며 추정 진행률이 아닙니다.

실행 실패는 `RoutingError.stage`와 실패 이벤트로 전달합니다. 콜백이 실패하면 이후 작업을 중단하고 그 예외를 그대로 전파합니다. 이미 진행 중인 동기 모델 호출을 취소하는 기능은 없습니다. 라우터는 호출 종료 후 입력·콜백·진행 상태를 보관하지 않습니다. **실행 완료와 외부 전달 가능은 별개**이므로 최종 `recommendation.action`을 확인해야 합니다.

### 추출만 사용하거나 의도를 직접 제공

```python
from agents import Extractor
from contracts import IntentAnnotation

text = "내부 참조 코드 ALPHA-42가 들어갈 안내문 초안만 작성해줘. 실제 발송하지 마."
intent = IntentAnnotation.for_text(
    text,
    goal="안내문 초안 작성",
    action="초안 작성",
    completion_condition="실제 발송 없이 안내문 초안 제공",
)
extraction = Extractor().extract(text, intent=intent)
for record in extraction.records:
    print(record.category, record.confidentiality.model_dump(), record.necessity.model_dump())
```

`Annotator.annotate(text) -> IntentAnnotation`은 의도 제공 프로토콜이고 `IntentAnalyzer`는 그 LLM 구현체입니다. `Extractor`가 의도 분석기를 내부에서 자동 호출하지는 않습니다.

어노테이션은 변경 불가능하며 정확한 원문의 UTF-8 SHA-256에 결합됩니다. 다른 원문에 사용하면 모델 호출 전에 거부합니다. 의도는 작업을 해석할 근거이지 실행·공개 허가가 아닙니다. 의도를 생략하거나 원문과의 호환성을 확인하지 못하면 기밀성은 계속 판단하되 개별 필요성과 전체 마스킹 영향은 미판정으로 남깁니다. 수행 요청이 없는 원문에서 분석기 자신의 JSON 출력 작업을 사용자 목표로 삼지 않습니다.

## 판정과 권장 행동

각 항목의 위치는 Unicode 코드 포인트 기준 `[start, end)`입니다. 공개 항목도 반환하며 두 판단 모두 `value`, `reason`, 계산된 `status`를 제공합니다.

| 판단 | 값 | 질문 |
|---|---|---|
| `confidentiality` | `public` / `private` | 공개 가능한 정보인가, 보호할 비공개 정보인가? |
| `necessity` | `required` / `optional` | 이 특정 원래 값이 작업 완료에 필요한가? |

근거가 부족하면 해당 축만 `value=None`, `status="unassessed"`입니다. 값이 있으면 `status="assessed"`입니다. 새 모델 응답에는 미판정인 경우에도 두 이유가 필요합니다. 캐시 재사용 결과의 이유는 저장하지 않았으므로 `None`입니다.

별도로 `masking_preserves_task`는 **공개 정보와 작업 지시는 유지하고 보호할 모든 값을 함께 가려도 작업을 완료할 수 있는지**를 나타냅니다. `True`는 유지, `False`는 완료 불가, `None`은 미판정이며 `masking_reason`에 이유를 반환합니다. 각 연락처가 대안이라 개별적으로는 `optional`이어도 모두 가리면 전달할 수 없습니다. 따라서 개별 선택성만으로 전체 마스킹이 안전하다고 결론 내리지 않습니다.

`HeuristicPolicy.recommend(results)`는 같은 작업·전체 문맥을 평가한 `ExtractionResult`, `DetectionResult`, `CachedAssessment`의 목록을 받아 다음 순서로 판단합니다.

| 우선순위 | 검사 근거 | `action` |
|---|---|---|
| 1 | 근거 없음·실패·부분 검사·보호 필요성이 있지만 위치 없음 | `None` — 권고 보류 |
| 2 | 기밀 여부 미판정 항목 존재 | `None` — 권고 보류 |
| 3 | 비공개 값이 작업에 필수이거나, 비공개 값이 있는 결과에서 전체 마스킹이 작업 완료를 막음 | `keep_local` — 로컬 처리 권장 |
| 4 | 그 외 비공개 값의 전체 마스킹 영향이 미판정 | `None` — 권고 보류 |
| 5 | 비공개 값이 있지만 전체 마스킹 후 작업 유지 확인 | `mask_then_share` — 마스킹 후 전달 권장 |
| 6 | 완전한 검사에서 보호 대상 없음 | `share_original` — 원문 전달 권장 |

보류는 네 번째 행동이 아닙니다. 호출자는 `None`을 외부 전달 차단으로 처리해야 합니다. `public + required`만으로 마스킹하거나 로컬 처리를 강제하지 않으며, 개별 필요성만 미판정이어도 전체 마스킹 판단을 사용할 수 있습니다. 서로 다른 문장을 따로 검사한 결과의 합은 전체 문맥 검사와 같지 않습니다.

모델 항목이 공개 여부와 무관하게 원문 위치·값 검증에서 탈락하면 결과는 `partial`입니다. 이를 완전한 공개 판정으로 바꾸지 않고 캐시에도 저장하지 않습니다. 누락된 모델 `records` 필드는 분석 실패이며, 명시적인 빈 목록과 구별합니다. 계약 상세는 [탐지 가이드](docs/user/detection.md)를 참조하세요.

## 캐시와 데이터 보관 경계

`Cachier`는 원문·이전 문맥·의도 내용·모델 이유·복원 매핑을 보관하지 않습니다. 해시 기반 키와 범주·위치·신뢰도·판정값·전체 마스킹 영향만 메모리에 보관합니다. 기본 용량은 256건이며 최근 사용 순서로 퇴출합니다.

조회에는 세션 범위, 원문 해시, 전체 이전 문맥 해시, 의도 해시, 탐지 규칙 지문이 모두 일치해야 합니다. 요약·절삭으로 문맥이 바뀌면 미적중입니다. 불완전한 결과는 저장하지 않고 같은 키의 이전 결과도 제거합니다. `invalidate(namespace)`와 `clear()`로 무효화할 수 있습니다.

- **호출자가 보호할 데이터:** 원문, 어노테이션, 추출 이유, `RouterResult`, `MaskingContract`, 복원 결과. 어느 것이든 민감 내용을 포함할 수 있습니다.
- **캐시도 외부 공개 금지:** 원문이 없어도 짧은 값의 해시는 후보 대입으로 추측할 수 있습니다. 해시는 익명화나 원문 복원 수단이 아닙니다.
- **재사용 검증:** `PrivacyRouter`는 원문의 스팬 해시를 확인하고 불일치 시 해당 세션 캐시를 무효화합니다. 완전한 추출은 마스킹·복원 일치 확인 후 저장합니다.

[캐시 명세](docs/cache-hash-utility.md)에 키 구성·저장 필드·직접 사용 예제가 있습니다.

## 웹 데모

데모는 라이브러리의 로컬 기본 설정과 달리 **신뢰된 피어의 Gemma 4 26B A4B**에 연결합니다. 현재 연결 대상은 `http://10.42.0.2:8090/v1`이며 서버 별칭 `openkb-compiler`와 실제 모델 경로를 확인합니다. 피어 연결과 인증 키가 없으면 추론할 수 없고 다른 모델로 대체하지 않습니다.

```bash
uv run --frozen python demo/server.py
```

단독 실행 기본 주소는 [http://127.0.0.1:8765](http://127.0.0.1:8765)입니다. 인증 키 파일은 `PRIVACY_DEMO_API_KEY_FILE`로 지정하며, 현재 장비의 기본 경로는 [`demo/server.py`](demo/server.py)의 `TOKEN_FILE`에 있습니다. 키 값을 명령행이나 저장소에 넣지 마세요.

현재 장비의 [Paseo 서비스 설정](paseo.json)은 loopback과 NetBird 주소 `100.69.181.62`의 **8875번 포트**에만 바인딩합니다. 같은 NetBird 네트워크에서는 [http://100.69.181.62:8875](http://100.69.181.62:8875)를 사용합니다. 다른 장비에서는 자신의 바인딩 주소로 변경해야 합니다.

- **직접 검사:** 의도 분석 → 캐시 → 추출 → 권고 → 마스킹·복원의 실제 상태와 시간을 표시합니다. 입력·예제 선택만으로 추론하지 않습니다.
- **항목별 설명:** 공개·비공개, 필수·선택 및 각각의 이유와 미판정 상태를 표시합니다. 보호 값은 반복 위치까지 강조하고 공개 항목은 반환된 위치만 강조합니다. 겹치면 보호가 우선하며 반복 강조가 추출 건수·원래 위치·판단 근거를 늘리지는 않습니다.
- **같은 입력 재실행:** 브라우저 메모리의 의도를 재전달해 캐시 적중 시 모델 호출을 생략합니다. 이전 이유를 보여줄 때는 출처를 표시하고 입력 수정·초기화·실패 시 지웁니다. 서버 캐시가 이유를 보관하는 것은 아닙니다.
- **과거 측정 결과:** 의도 분석 도입 전의 추출 단독 실험입니다. 현재 파이프라인의 성능이나 포괄적인 정밀도·재현율로 해석하지 않습니다.

데모는 실제 이메일·SMS 발송이나 대상 모델 호출을 하지 않습니다. 데모 서버와 브라우저는 입력·의도를 메모리에서만 처리하고 파일·로그·브라우저 영구 저장소에 기록하지 않습니다. 이 보장은 피어 추론 서버나 프록시의 로그·보관 정책까지 포함하지 않으므로 별도로 확인해야 합니다. 최대 12개 메시지·총 16,000자, 세션별 캐시 32건, 세션 비활성 만료 30분입니다.

**운영용 인증 서버가 아닙니다.** 비-loopback 바인딩은 `--allow-network`가 필요하고, 여러 주소는 `--host`를 반복합니다. 네트워크 접근 통제는 운영자 책임이며 공개 인터넷에 노출하지 마세요. 허용한 Host·Origin, 세션 쿠키, CSRF 검사는 별도로 적용합니다. HTTPS 프록시 출처는 `PASEO_URL` 또는 `--allowed-host`로 명시합니다.

`POST /api/analyze`에 `Accept: application/x-ndjson`을 지정하면 `status` 이벤트를 스트리밍합니다. 마지막 `result` 또는 `error`를 반드시 확인하세요. 헤더 전송 후 실패는 HTTP 200이어도 오류 이벤트로 끝납니다. 일반 JSON 요청은 완료 응답 하나를 반환합니다. 입력·Host/Origin·세션·CSRF 검증 실패는 스트리밍 전에 처리하지만, 피어 인증·모델 연결 실패는 스트림의 `error`로 전달될 수 있습니다.

## 테스트와 문서

```bash
uv run --frozen pytest -q
uv run --frozen ruff check src demo/server.py
node --check demo/static/app.js
```

코어 테스트는 외부 모델 서버나 데이터베이스 없이 실행됩니다. 의도 결합, 독립적인 두 판단, 전체 마스킹 영향, 정책 우선순위, 캐시 격리, 라우터 이벤트·실패, 마스킹·복원을 검증합니다. 테스트 통과는 실제 모델의 탐지 정확도를 보장하지 않습니다.

### 문서

| 목적 | 문서 |
|---|---|
| 항목별 판정과 원문 위치 규칙 | [탐지 가이드](docs/user/detection.md) |
| 캐시 키·보관 데이터·무효화 | [Cachier 명세](docs/cache-hash-utility.md) |
| 플레이스홀더·복원 API | [현재 API 구현](src/masker/masker.py). [기존 개념 설명](docs/user/masking-hydration.md)의 일부 예제·필드·불변성 설명은 현행 구현과 다르므로 실행 예제는 이 README를 사용 |
| 실제 모델 측정과 당시 조건 | [실험 색인](docs/experiments/README.md) |
| 주요 SDK 메시지 형식 조사 | [조사 보고서](docs/message-format-report.md), [당시 인쇄용 Word 문서](docs/message-format-report.docx) |
| 관련 문헌 | [참고 문헌](docs/user/references.md) |

실험과 SDK 조사 문서는 당시의 기록이며 현재 운영 어댑터나 최신 파이프라인 구현을 의미하지 않습니다. 코드 진입점은 [`src/agents/`](src/agents/), [`src/router/`](src/router/), [`src/policy/`](src/policy/), [`src/cachier/`](src/cachier/), [`src/masker/`](src/masker/), 공용 계약은 [`src/contracts/`](src/contracts/)입니다.

## 라이선스 및 문의

현재 저장소에는 오픈소스 라이선스가 없습니다. 소스 사용·복제·배포 권한은 별도로 부여되지 않습니다.

- DH. Kim — donghyeon@gist.ac.kr
- M. Saadati — mohammadsaadati@gm.gist.ac.kr
- Supervisor: Prof. Heung-No Lee, GIST

<!--
2026-09-20: 구현 현황을 처음 읽는 사용자의 설치·통합 순서로 재구성. Paperthin re0 원칙에 따라 누적 변경 이력·검증 회고·중복 설명을 현재 계약으로 통합.
Impact Surface
- Code: 변경 없음. src/의 공개 계약, config 모델 선택, demo/server.py와 static/app.js를 근거로 작성.
- Skills: 설치된 Paperthin readchk, re0, detool, sip의 문서 정리·검증 지침 참조. 스킬 자체 변경 없음.
- Docs: README만 갱신. 탐지·캐시 명세와 기존 라우터 섹션 앵커 유지.
- Decisions: 기능·보안·모델 선택 정책 변경 없음.
- Archive/versioning: 새 버전 문서 없음. 실험·SDK 조사 기록은 현행 구현과 구분.
- Verification: 코어 222개 테스트, Ruff·JavaScript 문법 검사 통과. Python 예제 3개 컴파일·공개 API 대조, 무모델 마스킹 예제 실행, 로컬 링크·앵커 29개와 demo --help 확인. 두 LLM 예제의 실추론은 이번 문서 작업에서 실행하지 않음. 독립적인 새 독자·구현 일치성 검토 수행.
- No-update rationale: README 정리 작업이며 코드 및 기존 실험 증거를 변경하지 않음.
-->
