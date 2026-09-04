# Privacy Router

LLM 에이전트가 외부 모델을 호출하기 전에 민감 정보를 탐지하고, 필요한 경우 마스킹하는 **코어 라이브러리**입니다.

현재 저장소는 서버, HTTP API, 인증, 데이터베이스, 웹 UI를 포함하지 않습니다. Judge와 Router는 향후 재설계를 위한 개념적 스키마만 유지합니다.

## 현재 범위

- **Extractor**: LLM, Presidio, OpenAI Privacy Filter, LFM 기반 탐지기와 공통 추출 결과 규격 제공
- **Critic**: 선택적 2차 검토를 통해 누락된 민감 스팬 보완
- **Masker**: 요청 범위 플레이스홀더 생성 및 응답 복원
- **LLM 호출 계층**: LiteLLM 기반 일반/구조화 출력 호출
- **Judge / Router**: 향후 정책·라우팅 재설계를 위한 `Judgment`, `RouteResult` 등 데이터 모델만 제공

현재 코어에는 외부 모델로 실제 요청을 보내는 라우팅 실행기나 HTTP 스트리밍 엔드포인트가 없습니다. 스트리밍 서버는 향후 재설계 범위입니다.

## 설치

Python 3.13 이상이 필요합니다.

```bash
git clone https://github.com/devcomfort/privacy-router.git
cd privacy-router
cp .env.example .env
uv sync
```

GPU 추론기나 선택적 탐지기를 사용할 때만 추가 의존성을 설치합니다.

```bash
uv sync --extra local-inference
uv sync --extra privacy-detectors
```

## 설정

- `.env`: API 키와 실행 환경의 비밀값을 관리합니다. 이 파일은 Git에 커밋하지 않습니다.
- `.env.example`: 필요한 환경변수의 템플릿입니다.
- `.privacy-router.config.yaml`: 모델 목록과 Extractor의 모델·엔드포인트·토큰 설정을 관리합니다.
- `PRIVACY_ROUTER_PROFILE`: YAML에 정의된 프로필을 선택적으로 적용합니다.

주요 환경변수:

```dotenv
OPENROUTER_API_KEY=
OPENAI_API_KEY=
LOCAL_API_BASE=http://127.0.0.1:8000/v1
LLM_MODEL=openrouter/google/gemma-4-26b-it
EXTRACTOR_MODEL=openrouter/google/gemini-3.1-flash-lite
```

외부 모델 호출에는 해당 공급자의 API 키가 필요합니다. 로컬 엔드포인트는 `.privacy-router.config.yaml`에 등록하고 `api_base`를 설정합니다.

## 기본 사용법

### 민감 정보 추출

```python
from agents import Extractor

extractor = Extractor()
result = extractor.extract("주민등록번호 901212-1234567을 확인해줘")

print(result.sensitivity.is_sensitive)
for record in result.records:
    print(record.category, record.span, record.is_essential)
```

고정밀 모드는 1차 추출 뒤 Critic 검토를 추가합니다.

```python
from agents import Extractor

result = Extractor(precision="high").extract("검토할 텍스트")
```

### 마스킹과 복원

```python
from masker import Masker

masker = Masker()
masked = masker.mask(
    "김민수의 전화번호는 010-1234-5678입니다.",
    [
        {"category": "PERSON_NAME", "span": "김민수", "start": 0, "end": 3},
        {"category": "PHONE_NUMBER", "span": "010-1234-5678", "start": 11, "end": 24},
    ],
)

# masked.masked_text만 외부 모델에 전달
model_output = masked.masked_text
restored = masker.hydrate(model_output, masked.contract)
```

마스킹 결과의 `MaskingContract`가 플레이스홀더와 원본 값의 매핑을 보유합니다. 계약에 등록되지 않은 플레이스홀더가 응답에 나타나면 `HydrationError`가 발생합니다.

실제 암호화가 필요한 경우 `masker`의 Fernet 유틸리티를 사용할 수 있습니다. 세부 시연은 다음 명령으로 확인합니다.

```bash
uv run python -m masker
```

## 핵심 데이터 흐름

```text
입력 텍스트
    ↓
Extractor
    ↓
ExtractionResult + ExtractionRecord[]
    ↓
(향후 설계) Judge → Router
    ↓
Masker → 외부 모델 또는 로컬 모델
    ↓
Hydrator
```

추출기는 탐지 결과만 반환합니다. 정책 결정과 라우팅은 아직 구현 대상이 아니며, 실제 마스킹은 원본 `ExtractionRecord[]`를 사용해야 합니다.

## 패키지 구조

```text
privacy-router/
├── src/
│   ├── agents/          # Extractor, Critic, detector backends
│   ├── masker/          # 인메모리 마스킹 및 복원
│   ├── shared/           # 공용 구현 유틸리티
│   │   └── llm.py        # LiteLLM·instructor 호출 클라이언트
│   ├── contracts/        # Extractor·Masker·Judge·Router 공용 계약
│   └── config/           # YAML 및 환경변수 기반 설정
├── docs/user/           # 탐지·마스킹·출처 문서
└── docs/experiments/    # 모델 실측 및 벤치 결과
```

## 테스트

코어 테스트는 외부 서버나 데이터베이스 없이 실행됩니다.

```bash
uv run pytest -q
```

현재 기준 코어 테스트는 Extractor, 탐지기별 파서, Masker, LLM 호출 계층을 검증합니다.

## 문서

- [`docs/user/detection.md`](docs/user/detection.md): 문맥 기반 민감도 탐지와 스팬 규칙
- [`docs/user/masking-hydration.md`](docs/user/masking-hydration.md): 플레이스홀더 계약과 복원 규칙
- [`docs/user/references.md`](docs/user/references.md): 프로젝트 참고 문헌
- [`docs/experiments/README.md`](docs/experiments/README.md): 모델 평가·벤치 결과 색인

## 라이선스 및 문의

현재 저장소에는 오픈소스 라이선스가 없습니다. 소스 사용·복제·배포 권한은 별도로 부여되지 않습니다.

문의:

- DH. Kim — donghyeon@gist.ac.kr
- M. Saadati — mohammadsaadati@gm.gist.ac.kr
- Supervisor: Prof. Heung-No Lee, GIST

## 문서 변경 이력

- 2026-09-04: 서버·인증·DB 제거 이후의 코어 라이브러리 범위와 실제 사용법에 맞게 README를 재구성했습니다.

## Impact Surface

- Code: `src/agents/`, `src/masker/`, `src/shared/`, `src/config/` 패키지 경계를 반영했습니다.
- Skills: 변경 없음.
- Docs: 삭제된 서버·배포·웹 UI·실험 하네스 참조를 제거하고 현행 코어 문서 링크만 유지했습니다.
- Decisions: 서버 없는 코어 우선 범위와 Judge/Router 재설계 보류 결정을 반영했습니다.
- Archive/versioning: README의 이전 상태를 별도 보존할 필요가 없어 버전 파일을 만들지 않았습니다.
- Verification: 참조 경로 검색 및 `uv run pytest -q`로 145개 테스트를 확인했습니다.
- No-update rationale: `.privacy-router.config.yaml`과 `docs/experiments/`는 기존 설정·실측 기록을 유지했습니다.
