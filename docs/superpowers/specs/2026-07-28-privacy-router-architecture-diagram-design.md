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
- 캔버스: 세 개의 큰 평면을 세로로 배치하고 평면 사이를 최소 600px 띄운다.
- Backend API는 시스템 컴포넌트 평면 안에서 독립된 영역과 구분선으로 분리한다.
- 데이터는 추상 컴포넌트 수준으로 표현한다. 개발 단계의 세부 필드, Pydantic 스키마, DB 열은 넣지 않는다.
- 화살표 라벨은 `전이 조건 / 행동 / 전달 데이터`를 짧게 표현한다.
- Extractor, Judge, Router, Masker/Hydrator의 기능과 세 실행 경로가 반드시 한눈에 드러나야 한다.
- 참고 파일은 수정하지 않는다.

## 시각 체계

참고 파일의 러프한 프레임·도형·화살표 문법을 유지하되 시스템 구분을 위해 제한된 의미색을 사용한다.

- 선: 2px, roughness 1
- 제목: 28px
- 평면·영역 제목: 22–24px
- 컴포넌트: 18–20px
- 화살표 라벨: 16–18px
- Local/Privacy Core: 연한 보라
- Backend API/입력: 연한 파랑
- External: 연한 주황
- Data/Storage: 연한 청록
- 완료: 연한 초록
- 안전한 실패: 연한 빨강
- 상태는 색상뿐 아니라 텍스트로도 구분한다.

## 캔버스 구조

### 평면 1 — 시스템 컴포넌트

왼쪽에서 오른쪽으로 네 영역을 배치한다. 각 영역은 큰 프레임과 세로 구분선으로 독립시킨다.

1. **Client & Integration**
   - Hermes Agent, OpenCode/OpenAI-compatible clients
   - SvelteKit Demo/Admin UI
   - LiteLLM Guardrail client
   - MCP agent/client
2. **Backend API**
   - FastAPI application, authentication, request tracing
   - Chat Completions, Responses(JSON/SSE/WebSocket)
   - Classify/Generate/Guardrail
   - Admin, model registry, masking session, telemetry APIs
   - 이 영역은 Privacy Core와 명확한 구분선으로 나눈다.
3. **Privacy Core**
   - Context Builder와 session context cache
   - PrivacyRouter orchestrator
   - Extractor facade, ExtractorCore, optional Critic
   - deterministic Judge와 Router
   - Masker/Hydrator, placeholder repair, fixed-route executor
4. **Model, Data & Operations**
   - Local Decision Model과 Local Generation Model
   - External Model via adapter/LiteLLM/OpenRouter
   - encrypted SQLModel storage, config/model registry, masking contracts, response/context retention
   - telemetry, usage/cost/latency, Admin dashboard
   - unit tests와 real-model evaluation은 작은 지원 컴포넌트로만 표시한다.

컴포넌트 간 화살표에는 protocol 또는 추상 데이터만 표시한다. 예: `OpenAI request`, `privacy analysis`, `masked payload`, `local raw prompt`, `safe telemetry`.

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

상태는 둥근 사각형, 조건 분기는 다이아몬드, 실패는 빨간 종료 상태로 표현한다.

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

- 라벨은 한 화살표당 최대 두 줄을 원칙으로 한다.
- 상태 전이는 `조건 / 행동` 형식으로 쓴다.
- 데이터 이동은 `생산자 행동 / 데이터` 형식으로 쓴다.
- 장문 설명은 별도 노트 하나로 모으지 않고, 필요하면 인접한 짧은 주석으로 분리한다.
- 교차 화살표보다 중간 합류 노드를 사용한다.

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
- 참고 파일과 비슷한 러프한 그림체를 유지하면서도 더 풍부한 시스템 지도를 제공한다.
