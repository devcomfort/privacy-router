# Privacy Router 연구 노트 Excalidraw 설계

## 목적

`refine-logs/FINAL_PROPOSAL.md`, `EXPERIMENT_PLAN.md`, `EXPERIMENT_TRACKER.md`, `REVIEW_SUMMARY.md`의 핵심을 서로 다른 관점의 Excalidraw 보드 3개로 시각화한다. 보드는 연구자·팀원에게는 실행 지도로, 지도교수·심사자에게는 논문 논리와 근거 상태를 설명하는 자료로 사용한다.

## 확정 사항

- 산출물: 독립적으로 읽을 수 있는 Excalidraw 보드 3개
- 언어: 한국어 중심, benchmark·leakage·utility 등 표준 용어는 영어 유지
- 공통 상태 문구: `GO_TO_PILOT (8/10) — 논문 결과가 확립된 상태는 아님`
- 공통 색상: 파랑=사실·구조, 보라=방법·시스템, 초록=검증된 근거, 주황=계획, 빨강=blocker
- 각 보드 내부에 `설계 의도`, `읽는 순서`, `색상 범례`를 포함
- 원자료가 주장하지 않는 성능·새로움·실험 결과를 추가하지 않음

## MCP 상태

Excalidraw MCP는 사용자 전역 설정 `~/.omp/agent/mcp.json`에 `https://mcp.excalidraw.com/mcp`로 이미 등록되어 있다. 2026-07-22에 MCP `initialize`와 `tools/list` 응답을 확인했다. 따라서 별도 설치나 프로젝트 `.mcp.json` 변경은 하지 않는다. 보드는 반드시 MCP의 `read_me` 확인 후 `create_view`로 렌더링하고, `export_to_excalidraw`로 공유 가능한 URL을 생성한다.

## 공통 시각 체계

- 캔버스: 가로형, 왼쪽에서 오른쪽으로 진행
- 제목 영역: 보드 이름, 독자, 상태 경고
- 본문: 둥근 사각형 카드, 단방향 화살표, 관련 요소만 점선 연결
- 설명 영역: 좌하단에 설계 의도와 읽는 법, 우하단에 범례·근거 문서
- 밀도: 핵심 카드는 보드당 8–14개, 카드당 4줄 이하
- 텍스트: 제목 28–32px, 섹션 20–24px, 본문 16–18px
- 위험 상태는 색상만으로 구분하지 않고 `BLOCKED`, `PLANNED`, `EVIDENCE` 표기를 병기

## 보드 1 — 논문 이야기 지도

### 설계 의도

논문을 처음 보는 사람이 연구 문제에서 제출 조건까지 한 번에 이해하도록 구성한다. benchmark 기여와 Privacy Router의 reference implementation 역할을 분리해, 시스템 구현을 알고리즘적 새로움으로 오해하지 않게 한다.

### 본문 흐름

1. 문제: agent egress에서 같은 정보도 공개 상태·수신자·목적·raw-value 필요성에 따라 전송 가능성이 달라짐
2. 연구 공백: PII 중심 또는 task-level privacy 평가는 조직·연구 기밀의 lifecycle-dependent 상태를 충분히 분리하지 못함
3. 핵심 기여: controlled intervention, EN/KO paired benchmark, exact-span+policy+egress evaluation
4. reference implementation: Extractor→factual factors→frozen policy P0→transform/route
5. 연구 질문·주장: C1–C7을 detection, policy, leakage/utility, bilingual robustness, abstention, reliability, overhead로 묶음
6. 검증 논리: novelty audit→pilot validity→dataset/evaluator freeze→main evidence
7. venue: ACL/EMNLP Findings 우선, PETS는 정책·위협 모델 강화 시 조건부
8. 현재 판정: GO_TO_PILOT, full benchmark production은 G0/G1 및 정책·schema gate 통과 전까지 금지

하단에는 G0–G6을 가로 진행 막대로 표시하고, 즉시 행동 4개를 연결한다: full-text audit, P0/schema freeze, 20–30 scenario pilot, power·budget analysis.

## 보드 2 — 시스템 파이프라인 지도

### 설계 의도

어디서 민감정보가 관찰되고, 어떤 사실 판단이 정책 action으로 변환되며, 실제 전송 표면에서 무엇을 측정하는지 보여준다. 탐지·마스킹·라우팅을 한 지표로 섞지 않고 단계별 failure source를 드러낸다.

### 본문 흐름

1. user/workspace context와 candidate egress
2. 신뢰 경계: 외부 model/tool 호출 직전
3. Extractor: exact character spans와 information atoms
4. factual labels: disclosure state, recipient authorization, purpose authorization, raw-value necessity
5. frozen policy P0: acceptable actions와 precedence
6. transformation: allow, mask/rewrite
7. route: approved external, local, ask, deny
8. serialized egress bytes: 실제 leakage 판정 표면
9. outcomes: literal/atom/derived leakage, recipient-specific exposure, task success, latency/cost
10. diagnostics: span oracle, factor oracle, policy oracle, route-matched, oracle-route

신뢰 경계는 굵은 빨간 점선으로, model-visible input과 gold/evaluator-only data는 분리된 수영 레인으로 표시한다. `model_input` 외 gold field가 request에 포함되면 실행을 거부한다는 규칙을 명시한다.

## 보드 3 — Claim–Evidence 지도

### 설계 의도

각 주장이 어떤 실험과 통과 기준으로만 성립하는지 추적한다. 계획을 결과로 오인하지 않도록 모든 claim을 evidence 상태와 실패 시 축소안에 연결한다.

### 본문 구조

Claim별 수평 레인:

- C1 detection: E2, matched safe-FPR, cluster-CI lower bound >0; practical target +10pp
- C2 conditional diagnostics: E3, factual labels·controlled interventions; 인과 주장이 아닌 조건부 오류 분석
- C3 leakage+utility: E5, leakage superiority와 utility −5pp non-inferiority의 intersection–union
- C4 EN/KO: E2-T, shared-threshold gap을 보고하며 사전 동등성 주장 없음
- C5 abstention: E4, AURC·risk at coverage·eventual completion
- C6 masking reliability: E6, placeholder integrity·hydration·serialized-byte leakage와 실패율 상한
- C7 overhead: E7, decomposed p50/p95 latency·tokens·cost·peak memory

각 레인은 `Claim → Experiment → Metric → Pass condition → Current status → Failure fallback` 순서로 배치한다. 좌측 foundation rail에는 E0-P pilot validity, E0-F full-dataset validation, E1 known-answer sanity를 배치하고 모든 claim의 선행조건으로 연결한다. 우측에는 공통 blocker인 G0 novelty audit, G1 pilot validity, G3 evaluator fixtures, G4 freeze를 배치한다. 모든 C1–C7의 현재 상태는 `NO PAPER EVIDENCE`로 표시하되, C6에만 기존 unit-test evidence가 implementation property임을 별도로 표시한다.

## 산출물

- `refine-logs/visual/privacy-router-research-story.excalidraw`
- `refine-logs/visual/privacy-router-system-pipeline.excalidraw`
- `refine-logs/visual/privacy-router-claim-evidence.excalidraw`
- 각 보드의 Excalidraw 공유 URL

각 `.excalidraw` 파일은 MCP에 전달한 drawable elements와 동일한 로컬 원본이다. MCP 전용 `cameraUpdate` pseudo-element는 표준 Excalidraw 파일에서 제외한다. URL 생성이 실패해도 로컬 파일은 보존하고 실패를 보고한다.

## 데이터 흐름

1. 최신 고정명 연구 문서에서 검증된 문구와 상태만 추출
2. MCP `read_me`로 요소 형식·팔레트·binding 규칙 확인
3. 보드별 Excalidraw 요소 JSON 생성
4. MCP `create_view`로 실제 렌더링
5. MCP `export_to_excalidraw`로 공유 URL 생성
6. drawable elements를 표준 Excalidraw document envelope에 넣어 `.excalidraw` 파일로 저장
7. 브라우저에서 공유 URL을 열어 제목·카드·화살표·범례·viewport를 확인

## 실패 처리

- MCP 연결 실패: 재초기화 후 한 번 재시도하고, 계속 실패하면 설치 문제가 아니라 원격 endpoint 장애로 명시
- 잘못된 요소 JSON: `read_me` 규격에 맞춰 해당 보드만 수정
- 텍스트 겹침·잘림: 카드 폭 또는 줄바꿈을 조정하고 다시 렌더링
- URL export 실패: 로컬 `.excalidraw` 파일은 완료 산출물로 유지하되 공유 URL 미생성 상태를 명시

## 완료 기준

- 보드 3개가 모두 MCP `create_view`로 렌더링됨
- 각 보드에 설계 의도·읽는 순서·범례가 있음
- `GO_TO_PILOT`와 `결과 확립 아님`이 명확히 보임
- 연구 문서의 C1–C7, E0–E7, G0–G6 관계에 모순이 없음
- 1440×900 viewport에서 핵심 흐름을 스크롤 없이 식별할 수 있음
- 텍스트 잘림, 카드 겹침, 의미 없는 교차 화살표가 없음
- 보드마다 로컬 `.excalidraw` 원본과 공유 URL이 제공됨
