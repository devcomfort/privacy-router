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
- 캔버스: 세 개의 큰 Excalidraw `frame`을 세로로 배치하고 평면 사이를 최소 600px 띄운다.
- Backend API는 시스템 컴포넌트 평면 안에서 독립된 영역과 구분선으로 분리한다.
- 데이터는 추상 컴포넌트 수준으로 표현한다. 개발 단계의 세부 필드, Pydantic 스키마, DB 열은 넣지 않는다.
- 색상 없이도 이해되도록 컴포넌트 수와 화살표 수를 줄이고, 직선 또는 직각 화살표를 우선한다.
- Extractor, Judge, Router, Masker/Hydrator의 책임과 세 실행 경로가 한눈에 드러나야 한다.
- 다이어그램 내부 라벨은 폰트 호환성을 위해 English-only로 작성한다.
- 참고 파일은 수정하지 않는다.

## 시각 체계

참고 파일의 러프한 프레임·도형·화살표 문법은 유지하되, 색상 의존성을 제거한다. 구분은 위치, frame, 구분선, shape, 라벨, dashed line만으로 표현한다.

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

### 평면 1 — 시스템 컴포넌트

왼쪽에서 오른쪽으로 네 영역을 배치한다. 각 영역은 하나의 큰 frame 안에서 세로 구분선으로만 분리한다.

1. **Clients**
   - Agent, SDK, UI가 OpenAI-compatible, MCP, Admin 요청을 보낸다.
2. **Backend API Plane**
   - FastAPI entry가 인증, 요청 추적, API shape 유지를 담당한다.
   - Context Adapter가 chat, responses, tools 입력을 검사 가능한 텍스트로 정규화한다.
3. **Privacy Core**
   - PrivacyRouter Pipeline이 `Extractor → Judge → Router`를 실행한다.
   - Transform/Execution 단계가 masking contract, fixed route execution, hydration/output inspection을 담당한다.
4. **Models · Data**
   - Local Models: Decision Model extraction과 Local Model sensitive generation.
   - External Model: raw safe 또는 masked payload만 수신.
   - Encrypted Storage + Telemetry: context, contract, response, route metrics.

컴포넌트 간 화살표에는 짧은 행동 또는 전달 데이터만 표시한다. 예: `request`, `normalize`, `inspected context`, `extract locally`, `safe or masked`.

### 평면 2 — 데이터 컴포넌트 흐름

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

### 평면 3 — 요청 상태 머신

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

1. Excalidraw MCP `create_view`로 세 평면을 순차 렌더링한다.
2. MCP `export_to_excalidraw`로 공유 URL을 만든다.
3. MCP에 전달한 drawable elements를 표준 Excalidraw 문서로 저장한다. `cameraUpdate`는 로컬 파일에서 제외한다.
4. 렌더된 뷰에서 텍스트 잘림, 도형 겹침, 화살표 교차, 구분선 침범을 확인한다.
5. 로컬 `.excalidraw` JSON을 파싱해 요소 수, ID 중복, 참조 무결성을 확인한다.

## 완료 기준

- 한 파일 안에 시스템 컴포넌트, 데이터 컴포넌트, 요청 상태 머신 평면이 모두 존재한다.
- Backend API가 독립 영역과 구분선으로 식별된다.
- 각 핵심 화살표에서 조건·행동·데이터 중 필요한 정보가 읽힌다.
- Extractor가 무엇을 추출하고 Judge와 Router가 무엇을 결정하는지 보인다.
- allow, selective_mask, block과 fail-closed 경로가 모두 연결된다.
- 세부 스키마 없이도 구현의 기능적 구조를 설명할 수 있다.
- 참고 파일과 비슷한 러프한 그림체를 유지하되, 색상 없이 읽히는 단순 시스템 지도를 제공한다.
