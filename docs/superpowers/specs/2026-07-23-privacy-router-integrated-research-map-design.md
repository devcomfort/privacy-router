# Privacy Router 통합 연구 지도 Excalidraw 설계

## 목적

기존의 `논문 이야기`, `시스템 파이프라인`, `Claim–Evidence` 보드 3개를 하나의 Excalidraw 세션으로 통합한다. 처음 보는 교수·심사자는 연구 문제와 근거 한계를 이해하고, 연구팀은 같은 보드에서 구현 구조·실험 gate·다음 행동을 찾을 수 있어야 한다.

## 확정 사항

- 독자: 교수·심사자와 연구팀을 함께 고려한 균형형
- 구조: 위에서 아래로 읽는 단일 세로형 캔버스
- 언어: 한국어 중심, benchmark·leakage·utility·trust boundary 등 표준 용어는 영어 유지
- 설명 수준: 기존 핵심 문구에 `무엇`, `왜 중요한가`, `어떻게 검증하는가`, `실패하면 무엇을 줄이는가`를 추가
- 상태 문구: `GO_TO_PILOT (8/10) — 논문 결과가 확립된 상태는 아님`
- 근거 원칙: 계획·가설·unit-test evidence를 논문 결과로 표현하지 않음
- 기존 3개 `.excalidraw` 파일은 보존하고 새 통합 파일을 추가

## 산출물

- 로컬 원본: `refine-logs/visual/privacy-router-integrated-research-map.excalidraw`
- Excalidraw MCP `create_view`로 렌더링한 단일 세션
- Excalidraw MCP `export_to_excalidraw`로 생성한 공유 URL 1개

## 캔버스와 탐색

캔버스는 약 2000px 폭의 세로형 연구 지도로 구성한다. 전체 내용을 한 화면에 축소하지 않는다. 공유 URL을 열면 상단 overview가 먼저 보이고, 사용자는 아래로 스크롤하여 각 섹션을 읽는다. 각 섹션 시작에는 번호·제목·한 문장 목적을 두고, 우측에는 현재 보고 있는 위치를 알려 주는 작은 목차를 반복한다.

권장 순서:

1. Overview
2. 논문 이야기
3. 시스템 파이프라인
4. Claim–Evidence
5. 연구 gate와 다음 행동

본문 글꼴은 16px 이상, 섹션 제목은 24–28px, 전체 제목은 32px 이상으로 유지한다. 카드 한 줄이 길어지면 글꼴을 줄이지 않고 줄바꿈이나 카드 폭을 조정한다.

## 공통 시각 체계

- 파랑: 문제, 관찰 사실, 입력·출력 구조
- 보라: 방법, 정책, 시스템 구성요소
- 주황: 계획, 실험, 통과 기준
- 초록: 검증된 구현 속성, 허용된 fallback, 다음 행동
- 빨강: blocker, trust boundary, `NO PAPER EVIDENCE`
- 실선 화살표: 실제 읽는 순서 또는 데이터 흐름
- 점선 화살표: 선행조건, 진단 관계, 섹션 간 참조

색상만으로 상태를 표현하지 않고 `PLANNED`, `BLOCKED`, `NO PAPER EVIDENCE`, `IMPLEMENTATION EVIDENCE`를 함께 표기한다.

## 섹션 0 — Overview

상단에는 다음 네 요소를 배치한다.

1. **핵심 질문**: 같은 정보라도 공개 상태·수신자·목적·raw-value 필요성이 달라질 때 외부 전송 결정을 어떻게 평가할 것인가.
2. **한 문장 기여 후보**: lifecycle-dependent confidentiality를 controlled intervention으로 분리하고, exact span·policy action·serialized egress leakage·utility를 EN/KO에서 함께 측정하는 benchmark와 reference implementation.
3. **현재 상태**: `GO_TO_PILOT (8/10)`이며 full benchmark production과 논문 성능 주장은 아직 금지.
4. **읽는 법**: 문제와 기여를 이해한 뒤 시스템에서 측정 지점을 확인하고, 마지막으로 C1–C7의 근거 조건과 fallback을 검토.

Overview 아래에는 섹션 목차를 작은 카드 4개로 배치한다. 목차 카드는 시각적 탐색 표지이며 새로운 주장이나 결과를 담지 않는다.

## 섹션 1 — 논문 이야기

연구 논리를 왼쪽에서 오른쪽으로 두 줄에 배치한다.

1. **문제**: agent egress decision은 span의 종류만이 아니라 disclosure state, recipient authorization, purpose authorization, raw-value necessity에 의존한다.
   - 왜 중요한가: 같은 문자열도 상황에 따라 허용·mask·local·ask·deny가 달라질 수 있다.
2. **연구 공백**: PII 중심 또는 task-level privacy 평가는 조직·연구 기밀의 상태 변화를 충분히 분리하지 못한다.
   - 왜 중요한가: 문자열 종류만 맞추는 benchmark로는 context-dependent policy failure를 진단하기 어렵다.
3. **핵심 기여 후보**: controlled intervention, EN/KO paired benchmark, exact span + policy compliance + serialized leakage + utility evaluation.
   - 검증 조건: novelty audit와 pilot이 먼저 통과해야 하며 현재는 가설 상태다.
4. **Reference implementation**: Privacy Router는 benchmark를 실행하는 시스템이며 benchmark 자체와 분리한다.
   - 범위 제한: 새로운 암호학·학습·privacy definition을 주장하지 않는다.
5. **연구 질문 C1–C7**: detection, conditional diagnostics, leakage/utility, EN/KO robustness, abstention, masking reliability, overhead.
6. **검증 논리**: novelty audit → pilot validity → dataset/evaluator freeze → main evidence.
7. **Venue 전략**: ACL/EMNLP Findings 우선, PETS는 정책·위협 모델과 실무 타당성이 강화될 때만 조건부.
8. **현재 판정**: G0/G1과 policy/schema gate 전에는 novelty·superiority·full production을 주장하지 않는다.

섹션 하단에는 `문제 → 공백 → 기여 → 구현 → 연구 질문 → 검증 → venue`의 관계를 평문 한 문단으로 다시 설명한다.

## 섹션 2 — 시스템 파이프라인

두 개의 수영 레인을 사용한다.

### MODEL-VISIBLE 레인

1. **Candidate egress**: user/workspace context, outbound payload, recipient, purpose, policy profile P0.
2. **Extractor**: exact character span과 information atom 후보를 생성한다.
3. **Factual factors**: disclosure state, recipient authorization, purpose authorization, raw-value necessity를 기록한다.
4. **Frozen policy P0**: 닫힌 action vocabulary와 precedence로 허용 가능한 action을 결정한다.
5. **Transformation**: allow 또는 mask/rewrite를 적용하되 동일 route를 비교할 수 있게 분리한다.
6. **Route decision**: approved external, local, ask, deny 중 하나를 선택한다.
7. **Serialized egress bytes**: 외부 provider로 실제 전송되는 canonical bytes이며 leakage 판정의 기준 표면이다.

각 단계 카드에는 `입력`, `출력`, `대표 실패`를 한 줄씩 적는다. 예를 들어 Extractor 실패는 span boundary 오류, policy 실패는 precedence 또는 factor mapping 오류, route 실패는 허용되지 않은 수신자에게 전송하는 경우다.

외부 `trust boundary`는 굵은 빨간 점선으로 표시한다. `model_input` 외 gold field가 request에 포함되면 실행을 거부하는 fail-closed 규칙을 바로 아래에 둔다.

### EVALUATOR-ONLY 레인

- Gold labels: contextually protected information atom과 source/byte mapping
- Policy oracle: canonical action, acceptable-action set, recipient/purpose 규칙
- Scorer: serialized bytes와 gold를 비교하고 route별 utility를 연결
- Outcomes: literal·atom·derived leakage, recipient-specific exposure, task success, latency, cost
- Diagnostics: span oracle, factor oracle, policy oracle, route-matched, oracle-route

두 레인 사이에는 serialized bytes에서 scorer로 향하는 점선 하나만 둔다. 이는 gold가 model request로 올라가는 것이 아니라, 실제 전송 결과가 사후 평가로 내려간다는 뜻이다.

## 섹션 3 — Claim–Evidence

각 C1–C7을 다음 순서의 한 레인으로 표시한다.

`쉬운 설명 → Experiment → Metric / Pass rule → Current evidence → Failure fallback`

- **C1 detection**: 조직·연구 기밀을 같은 safe-FPR에서 더 잘 찾는가. E2-D/E2-T, recall 차이와 scenario-cluster CI lower bound > 0, practical target +10pp. 실패 시 우월성 문구를 삭제하고 benchmark 또는 negative result로 축소.
- **C2 conditional diagnostics**: factual factor가 오류 원인을 나누는 데 실제로 도움이 되는가. E3의 conditional oracle improvement를 사용하며 causal attribution으로 합산하지 않음. 실패 시 universal necessity와 causal wording 삭제.
- **C3 leakage + utility**: full system이 leakage를 줄이면서 task utility를 허용 범위 안에 유지하는가. E5의 intersection–union criterion과 utility non-inferiority bound > −5pp. 실패 시 system claim 삭제 또는 policy 수정.
- **C4 EN/KO robustness**: 하나의 threshold에서 언어별 성능 차이가 어떻게 나타나는가. E2-T paired gap을 보고하되 사전 동등성 주장은 하지 않음. 실패나 큰 gap은 limitation 또는 finding으로 보고.
- **C5 abstention**: ask-user가 위험을 줄이는 만큼 사용자 부담을 정당화하는가. E4의 AURC, risk at coverage, ask rate, extra turns, eventual completion. 실패 시 confidence 기반 ask 비활성화.
- **C6 masking reliability**: placeholder와 hydration이 byte level에서 안정적인가. E6의 integrity, hydration exactness, serialized-byte leakage, failure-rate CI와 release gate ≥99.9%. 현재 unit test는 implementation property일 뿐 paper evidence가 아님. 실패 시 deployment readiness claim 중단.
- **C7 overhead**: detector와 전체 pipeline의 지연·비용이 실용적인가. E7의 p50/p95 latency, tokens, cost per 1k, peak memory. 고정 superiority criterion은 두지 않고 deployment guidance로만 제공.

좌측 foundation rail에는 E0-P pilot validity, E0-F full-dataset validation, E1 known-answer sanity를 둔다. 공통 blocker로 G0 novelty audit, G1 pilot validity, G3 evaluator fixture, G4 policy/model/test freeze를 표시한다. 모든 C1–C7은 `NO PAPER EVIDENCE` 상태로 시작한다.

## 섹션 4 — 연구 gate와 다음 행동

G0–G6을 세로 gate 목록으로 정리하고 현재 상태를 모두 `BLOCKED`로 표시한다.

- G0: full-text artifact novelty audit
- G1: 20–30 scenario pilot과 annotation/validity 기준
- G2: 최소 400 semantic scenarios와 dataset freeze
- G3: evaluator known-answer fixture 일치
- G4: policy·schema·prompt·model·test hash freeze
- G5: main evidence E2/E3/E5/E6 완료
- G6: human utility validation, failure audit, artifact card

즉시 행동은 네 카드로 제한한다: full-text audit, P0/schema freeze, 20–30 scenario pilot, power·budget analysis. 각 행동에는 통과 시 열리는 다음 gate를 적는다.

## 섹션 간 연결

교차 연결은 세 개만 사용한다.

1. 논문 이야기의 `Reference implementation` → 시스템 파이프라인 시작
2. 논문 이야기의 `C1–C7` → Claim–Evidence 섹션
3. 시스템 파이프라인의 `Serialized egress bytes` → C3 leakage metric

긴 교차선은 점선과 짧은 라벨로 표시하며, 본문 카드 위를 가로지르지 않는다.

## 근거 문서

- `refine-logs/FINAL_PROPOSAL.md`
- `refine-logs/EXPERIMENT_PLAN.md`
- `refine-logs/EXPERIMENT_TRACKER.md`
- `refine-logs/PIPELINE_SUMMARY.md`
- `refine-logs/REVIEW_SUMMARY.md`

문서 간 충돌이 있으면 최신 고정명 파일과 tracker의 gate 상태를 우선한다. 숫자·threshold·venue 표현은 원문에 있는 값만 사용한다.

## 실패 처리

- 텍스트 잘림: 글꼴을 줄이지 않고 줄바꿈·카드 폭·섹션 높이를 조정
- 화살표 혼잡: 교차 연결을 제거하고 섹션 하단의 참조 라벨로 대체
- MCP export 실패: 로컬 `.excalidraw` 원본은 유지하고 endpoint를 한 번 재시도
- 공유 URL에서 viewport가 부적절함: overview가 처음 보이도록 `appState.zoom`, `scrollX`, `scrollY`를 조정
- 설명과 연구 문서가 충돌함: 설명을 삭제하거나 `planned`/`hypothesis`로 낮춤

## 완료 기준

- 하나의 `.excalidraw` 파일과 공유 URL에서 다섯 섹션을 모두 확인할 수 있음
- 기존 3개 보드는 변경되지 않음
- Overview에서 `GO_TO_PILOT`와 `결과 확립 아님`이 즉시 보임
- 논문 이야기에는 각 단계의 이유와 범위 제한이 포함됨
- 파이프라인에는 단계별 입력·출력·대표 실패와 trust boundary가 포함됨
- Claim–Evidence에는 C1–C7의 쉬운 설명, experiment, metric/pass rule, evidence 상태, fallback이 포함됨
- G0–G6과 즉시 행동 4개가 포함됨
- 모든 본문 텍스트가 16px 이상이며 카드 겹침·텍스트 잘림·의미 없는 교차선이 없음
- 공유 URL을 실제 브라우저에서 열고 overview와 각 섹션을 스크롤하여 시각 검증함
