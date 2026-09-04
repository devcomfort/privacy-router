# Privacy Router 아키텍처 다이어그램 설계

## 목적

현재 구현된 Privacy Router를 하나의 Excalidraw 파일에서 설명한다. 독자는 세부 Pydantic 필드나 데이터베이스 스키마를 읽지 않고도 다음을 파악할 수 있어야 한다.

- 어떤 시스템 컴포넌트가 요청을 받는가
- 각 컴포넌트가 어떤 행동을 수행하는가
- 어떤 추상 데이터 컴포넌트를 생산하거나 소비하는가
- 요청이 어떤 상태와 조건을 거쳐 외부 모델, 로컬 모델, 완료 또는 안전한 실패로 전이하는가

## 확정 범위

- 산출물: `privacy-router-architecture.excalidraw` 한 파일
- 참고 스타일: 루트의 `architecture.excalidraw`
- 캔버스: 세 개의 큰 Excalidraw `frame`을 세로로 분리한다. 1번 frame은 시스템/사용자 컴포넌트를 함께 담고, 2번은 데이터 흐름, 3번은 요청 상태 머신을 담는다.
- 프레임 간 참조를 피하기 위해 User, Agent/Developer, Admin은 1번 frame 내부에 두고 dashed 구획선으로 시스템 내부 서비스와 분리한다.
- 데이터는 추상 컴포넌트 수준으로 표현한다. 개발 단계의 세부 필드, Pydantic 스키마, DB 열은 넣지 않는다.
- 색상 없이도 이해되도록 컴포넌트 수와 화살표 수를 줄이고, 직선 또는 직각 화살표를 우선한다.
- Extractor, Judge, Router, Masker/Hydrator의 책임과 세 실행 경로가 한눈에 드러나야 한다.
- 다이어그램 내부 라벨은 폰트 호환성을 위해 English-only로 작성한다.
- 참고 파일은 수정하지 않는다.

## 시각 체계

참고 파일의 러프한 도형·화살표 문법은 유지하되, 색상 의존성을 제거한다. 구분은 위치, 세 개 frame, 1번 frame 내부 dashed 구획선, shape, 라벨만으로 표현한다.

- 선: 2px, roughness 1
- 제목: 28px
- 평면·영역 제목: 22px
- 컴포넌트: 18–20px
- 화살표 라벨: 16px
- 다이어그램 내부 라벨: English-only
- 도형 채움: 기본 `transparent`
- 주 경로: solid arrow
- 보조 저장·운영 경로: dashed arrow
- 실패 상태: dashed rectangle과 명시적 `FAILED`/`REJECTED` 텍스트

## 캔버스 구조

### 프레임 1 — 시스템/사용자 컴포넌트

프레임 1의 상단 시스템 섹션에는 내부 서비스를 배치하고, 하단 사용자 섹션에는 User, Agent/Developer, Admin 컴포넌트를 배치한다.

1. **Backend API Plane**
   - FastAPI entry가 인증, 요청 추적, API shape 유지를 담당한다.
   - Context Adapter가 chat, responses, tools 입력을 검사 가능한 텍스트로 정규화한다.
   - Admin APIs가 runtime, masking, telemetry, key 관리 요청을 처리한다.
2. **Privacy Core**
   - PrivacyRouter Pipeline이 `Extractor → Judge → Router`를 실행한다.
   - Transform/Execution 단계가 masking contract, fixed route execution, hydration/output inspection을 담당한다.
3. **Models / Data**
   - Local Models: Decision Model extraction과 Local Model sensitive generation.
   - External Model: raw safe 또는 masked payload만 수신.
   - Encrypted Storage + Telemetry: config, context, contract, response, route metrics.

#### 내부 섹션 — 사용자·에이전트·관리자 컴포넌트

같은 1번 frame 안에서 시스템 섹션 아래에 배치하고 dashed 구획선으로 분리한다. 좌우 흐름은 이 섹션 내부의 짧은 연결로 제한하고, 시스템과의 요청·응답·관리·telemetry 흐름은 위아래 화살표로 연결한다.

1. **User Components**
   - End User/Operator와 User-facing Surface가 prompt와 보호된 응답을 주고받는다.
2. **Agent / Developer Components**
   - Hermes, OpenCode, SDK, client app이 Backend API Plane으로 OpenAI-compatible 또는 MCP 요청을 올린다.
   - Client Config는 base URL, API key, model/profile 설정을 Agent Runtime에 제공한다.
3. **Admin Components**
   - Admin Dashboard는 keys, profiles, models를 관리하고 Client Config 설정을 공급한다.
   - Telemetry View는 Admin APIs를 통해 raw payload 없이 safe traces, usage, masking metadata를 조회한다.

컴포넌트 간 화살표에는 짧은 행동 또는 전달 데이터만 표시한다. 예: `request`, `normalize`, `inspected context`, `extract locally`, `safe or masked`.

### 프레임 2 — 데이터 컴포넌트 흐름

시스템 박스가 아니라 데이터 산출물 중심으로 왼쪽에서 오른쪽으로 배치한다.

1. **Inbound Request** — messages, Responses input, tools 또는 MCP text를 포괄하는 추상 입력
2. **Inspected Context** — 현재 요청과 tenant-scoped 이전 대화에서 수집한 text-bearing context
3. **Extraction Result** — query-level sensitivity와 검증된 sensitive span records
4. **Policy Judgment** — allow, selective_mask, block 중 하나와 마스킹 가능성
5. **Route Decision** — external/raw, external/masked, local/raw 중 하나
6. 분기 데이터
   - **Raw Safe Payload**
   - **Masked Payload + Local Contract**
   - **Local Sensitive Payload**
7. **Provider Output** — content, stream chunks, tool calls, usage
8. **Protected Final Response** — hydration 또는 output inspection이 끝난 caller-facing response
9. **Safe Operational Data** — counts, action, route, model, tokens, cost, latency; raw sensitive value는 제외하거나 암호화

각 데이터 사이 화살표에 생산 컴포넌트와 행동을 함께 표기한다. 예: `Context Builder / collect`, `Extractor / detect exact spans`, `Judge / derive policy`, `Masker / replace with opaque token`, `Hydrator / restore registered token`.

### 프레임 3 — 요청 상태 머신

상태는 둥근 사각형, 조건 분기는 다이아몬드, 실패는 dashed rectangle과 명시적 실패 텍스트로 표현한다.

주 경로:

`RECEIVED → AUTHENTICATED → CONTEXT_READY → ANALYZING → CLASSIFIED → ROUTE_SELECTED`

`ROUTE_SELECTED` 이후 세 경로:

- `allow` → `EXTERNAL_RAW_READY` → `CALLING_EXTERNAL`
- `selective_mask` → `MASKING` → `EXTERNAL_MASKED_READY` → `CALLING_EXTERNAL` → `HYDRATING`
- `block` → `LOCAL_RAW_READY` → `CALLING_LOCAL`

추가 전이:

- uninspected media 또는 development mode는 선택된 외부 경로를 `LOCAL_RAW_READY`로 강제한다.
- provider 실행은 선택된 endpoint를 바꾸지 않고 같은 경로에서만 재시도한다.
- streaming은 첫 출력 전까지만 재시도할 수 있고, 첫 출력 후에는 경로를 바꾸지 않는다.
- tool call 결과는 protocol 검증과 민감 인자 보호를 거친다.
- 성공 경로는 `OUTPUT_PROTECTED → COMPLETED`에서 합류한다.
- 인증·모델·protocol 오류는 `REJECTED`로 종료한다.
- extraction, route invariant, masking, hydration 실패는 raw input을 노출하지 않는 `PRIVACY_FAILED`로 종료한다.
- provider 재시도 소진은 `PROVIDER_FAILED`로 종료한다.

## 화살표 라벨 규칙

- 라벨은 짧은 동사 또는 조건어를 우선한다.
- 흐름이 박스 이름만으로 분명하면 라벨을 생략한다.
- 장문 설명은 화살표에 넣지 않는다.
- 교차 화살표보다 중간 합류 노드를 사용한다.
- 화살표 라벨이 컴포넌트 박스와 겹치면 라벨을 줄이거나 제거한다.
- 구분선이 아닌 화살표는 `startBinding`/`endBinding`을 사용해 rectangle 또는 diamond 도형에 실제 연결한다.

## 사실 기준

다이어그램은 현재 코드의 다음 불변식을 따른다.

- ExtractorCore와 optional Critic만 로컬 Decision Model을 호출한다.
- Judge는 규칙 기반이며 LLM을 호출하지 않는다.
- Router는 policy action을 endpoint와 masking requirement로 결정론적으로 매핑한다.
- safe input만 원문으로 외부 모델에 전달한다.
- maskable sensitive input은 요청 범위의 불투명 placeholder로 치환하고 로컬 contract로만 복원한다.
- essential sensitive input, span을 안전하게 특정할 수 없는 sensitive input, 검사하지 못한 media는 로컬로 보낸다.
- 실패 시 더 약한 경로나 다른 endpoint로 자동 전환하지 않는다.

## 생성 및 검증

1. Excalidraw MCP `create_view`로 세 개 frame을 렌더링한다. 1번 frame 내부는 dashed 구획선으로 시스템/사용자 섹션을 나눈다.
2. MCP `export_to_excalidraw`로 공유 URL을 만든다.
3. MCP에 전달한 drawable elements를 표준 Excalidraw 문서로 저장한다. `cameraUpdate`는 로컬 파일에서 제외한다.
4. 렌더된 뷰에서 텍스트 잘림, 도형 겹침, 화살표 교차, 구분선 침범을 확인한다.
5. 로컬 `.excalidraw` JSON을 파싱해 요소 수, ID 중복, 참조 무결성을 확인한다.

## 완료 기준

- 한 파일 안에 1) 시스템/사용자 컴포넌트 frame, 2) 데이터 컴포넌트 frame, 3) 요청 상태 머신 frame이 분리되어 존재한다.
- Backend API가 독립 영역과 구분선으로 식별된다.
- 각 핵심 화살표에서 조건·행동·데이터 중 필요한 정보가 읽힌다.
- Extractor가 무엇을 추출하고 Judge와 Router가 무엇을 결정하는지 보인다.
- allow, selective_mask, block과 fail-closed 경로가 모두 연결된다.
- 세부 스키마 없이도 구현의 기능적 구조를 설명할 수 있다.
- 참고 파일과 비슷한 러프한 그림체를 유지하되, 색상 없이 읽히는 단순 시스템 지도를 제공한다.
