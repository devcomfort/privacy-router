# Research Proposal

## Evaluating Cumulative Privacy Leakage in LLM Agent Workflows

**Project context:** Future research direction extending Privacy Router
**Primary contribution:** A benchmark and empirical study
**Secondary contribution:** A stateful Privacy Router prototype used for comparison experiments
**Date:** 2026-07-13

---

# 한국어 제안서

## 1. 한 문장 연구 방향

**LLM 에이전트가 여러 단계와 여러 외부 경로를 거치며 민감정보를 조금씩 누출하는 문제를 측정하고, 이전 전송 내역을 보는 방어가 현재 요청만 보는 방어보다 실제 과업 성공을 덜 해치면서 누출을 더 잘 막는지 검증한다.**

이 연구의 중심은 새로운 보안 용어 또는 보편적 보안 원리를 만드는 것이 아니다. 중심 기여는 다음 두 가지다.

1. 누적 누출과 최종 과업 성공을 함께 측정하는 공개 가능한 benchmark
2. 기존 Privacy Router와 여러 비교 방법이 어디서 실패하는지 보여 주는 재현 가능한 실험

상태를 저장하는 Privacy Router 확장은 연구 가설을 시험하기 위한 prototype이다. 완전한 reference monitor, 형식적 noninterference 보장, 또는 새로운 일반 보안 메커니즘으로 주장하지 않는다.

## 2. 문제

### 2.1 한 번의 요청만 검사하면 놓치는 누출

현재 privacy filter는 보통 요청 또는 응답 하나를 독립적으로 검사한다. 그러나 tool-using agent는 같은 과업에서 여러 차례 외부 전송을 만든다.

예:

1. "저희 회사는 TSMC와 협력합니다."
2. "대상 공정은 3nm입니다."
3. "최근 내부 수율 개선은 15%입니다."
4. "이 내용을 외부 경쟁사 비교 도구에 넣어 주세요."

각 문장만 보면 불완전한 정보처럼 보일 수 있다. 같은 수신자에게 누적되면 `TSMC + 3nm + 내부 수율 15%`라는 미공개 사실이 완성된다. 현재 요청만 보는 detector는 이 조합을 놓칠 수 있다.

### 2.2 같은 정보도 수신자와 목적에 따라 허용 여부가 다르다

개인 식별 번호처럼 형식이 고정된 정보도 있지만, 다음 정보는 문맥 없이는 민감성을 판단하기 어렵다.

- 미공개 연구 아이디어
- 제조 수율
- 내부 원가와 가격 전략
- 특허 출원 전 기술 내용
- 프로젝트 codename
- 특정 고객과의 계약 조건

내부 분석 도구에 필요한 정보가 외부 서비스에는 불필요할 수 있다. 따라서 `sensitive / non-sensitive` 분류만으로는 충분하지 않다. 누가, 누구에게, 어떤 목적으로, 무엇을 보내는지가 필요하다. 이 관점은 Nissenbaum의 Contextual Integrity와 직접 연결된다.

### 2.3 민감정보를 제거한 뒤에도 과업이 성공하는지 확인해야 한다

완전 차단은 누출을 막지만 과업을 실패시킨다. 반대로 무조건 허용하면 과업은 성공하지만 privacy는 보장되지 않는다. 실제 방어는 다음 두 결과를 동시에 측정해야 한다.

1. 허용되지 않은 정보가 외부로 전달되었는가?
2. 방어 적용 후에도 최종 과업이 성공했는가?

이 연구에서 **full-workflow evaluation**은 agent의 전체 실행을 끝까지 수행하고 최종 결과까지 확인한다는 뜻으로만 사용한다.

## 3. 연구 범위

### 포함

- agent가 cloud LLM에 보내는 요청
- agent가 외부 tool에 보내는 argument
- MCP 또는 agent 간 메시지
- agent가 memory 또는 문서에 쓰는 내용
- 지원 adapter를 통과하는 email/SMS tool call
- trusted local UI 또는 local model로 보내는 결과

### 제외

- 사용자가 직접 보내는 일반 문자·이메일
- 운영체제 전체의 네트워크 감시
- 지원 adapter를 우회한 전송
- 악성 agent 또는 운영체제 침해에 대한 완전한 방어
- 암호학적 정보 흐름 보장
- 모든 언어와 모든 조직에 대한 보편적 privacy 규칙

연구 대상은 **agent가 생성하거나 중개하는 외부 전송**이다. 이메일과 SMS는 독립적인 범용 검사 대상이 아니라 agent가 호출할 수 있는 전송 도구의 예다.

## 4. 표현 원칙

새로운 고유명사나 약어를 만들지 않는다. 본문에서는 다음과 같이 뜻이 바로 드러나는 일반 표현을 사용한다.

- **외부 전송:** agent가 cloud LLM, tool, MCP peer, memory, 문서 또는 local UI로 정보를 보내는 동작
- **민감정보:** 정책상 보호해야 하는 정보
- **전송 내역:** 특정 수신자에게 특정 목적으로 이미 전달된 정보
- **허용되지 않은 누출:** 수신자에게 보내면 안 되는 민감정보가 전달된 경우
- **최종 과업 성공:** 방어 적용 후에도 agent가 원래 과업을 완료한 경우

## 5. 연구 질문

### RQ1. 이전 전송 내역이 필요한가?

현재 전송만 검사하는 방법과, 같은 수신자·목적에 대한 이전 전송 내역을 함께 검사하는 방법을 비교한다.

**가설:** 동일한 오탐률에서 이전 전송 내역을 사용하는 방법이 누적 누출을 더 많이 찾는다.

### RQ2. 어떤 전송 기록 방식이 충분한가?

다음 기록 방식을 비교한다.

- 기록 없음
- 직전 전송만 저장
- 전체 대화 기록 저장
- 정확히 같은 문자열만 기록
- 문장 의미의 유사도 기록
- 수신자와 목적별로 민감정보의 의미를 요약한 기록

**가설:** 수신자와 목적별 의미 요약은 전체 대화 기록보다 저장량이 작으면서, 문자열 기록보다 재표현과 여러 조각의 결합을 더 잘 처리한다.

### RQ3. 누출 감소와 과업 성공을 함께 달성할 수 있는가?

누출 탐지율, 오탐률, 최종 과업 성공률, 지연 시간, API 비용을 함께 측정한다.

**가설:** 이전 전송 내역을 사용하는 방법은 현재 Privacy Router보다 누출 탐지율을 높이면서 최종 과업 성공률 감소를 5%p 이내로 유지한다.

### RQ4. 어떤 상황에서 실패하는가?

다음 실패 유형을 분리해 측정한다.

- 한 사실을 여러 action으로 나누어 전송
- 같은 뜻을 다른 표현으로 반복
- 별칭, 대명사, codename 사용
- 수신자 변경
- 목적 변경
- 언어 혼합
- prompt injection이 포함된 외부 tool input
- 저장된 history의 누락 또는 손상
- timeout, retry, partial failure
- 합법적으로 반복되는 안전한 정보

## 6. Benchmark 설계

### 6.1 과업 분야

최소 네 분야를 포함한다.

1. **개인 행정:** 이름, 연락처, 금융, 서식 작성
2. **기업 운영:** 전략, 가격, 제조, 인사
3. **연구 업무:** 미공개 아이디어, 결과, 검토, 특허 일정
4. **의료:** 진단, 치료, 예약, 임상 요약

각 과업은 4~8개의 외부 전송을 포함한다. 한 과업 안에서 여러 경로를 함께 사용할 수 있다.

### 6.2 전송 경로

- 외부 cloud LLM 요청
- 외부 tool argument
- MCP 또는 agent 간 메시지
- memory 기록
- 문서 또는 artifact 기록
- 신뢰할 수 있는 local UI 출력

### 6.3 누출 패턴

1. 한 번에 직접 누출
2. 여러 전송으로 분할
3. 같은 뜻을 다른 표현으로 반복
4. 별칭 또는 대명사로 연결
5. 수신자 변경
6. 목적 변경
7. 서로 모순되는 정보로 탐지기 혼란
8. prompt injection이 포함된 외부 입력
9. 서로 다른 경로의 정보 결합
10. 허용된 정보의 정상 반복

### 6.4 안전한 대조 사례

공격 또는 누출 사례마다 구조가 유사한 안전한 사례를 만든다. 안전한 사례는 다음 중 하나만 바꾼다.

- 허용된 수신자
- 합법적인 목적
- 이미 공개된 정보
- 다른 정보 주체
- 과업에 필요한 최소 정보만 포함

이 대조 사례는 과도한 차단을 측정하는 데 사용한다.

### 6.5 데이터 단위

각 외부 전송에 다음 정보를 기록한다.

- 과업 ID와 scenario family ID
- 전송 ID와 순서
- 보내는 agent
- 수신자 또는 수신자 유형
- 목적
- operation
- destination field
- channel 또는 trust zone
- payload
- sensitive information ID
- 여러 조각으로 나뉜 경우 part ID와 연결 정보
- 해당 수신자·목적에 대한 허용 여부
- 이 action 뒤에 수신자가 전체 민감정보를 알 수 있는지
- 예상되는 안전한 action
- 최종 과업 성공 조건
- safe/attack label
- language와 domain

### 6.6 Annotation

- 두 명의 annotator가 독립적으로 작성
- 불일치는 제3자 또는 공동 adjudication으로 해결
- 자동 생성된 label을 그대로 정답으로 사용하지 않음
- task template와 scenario family 단위로 train/calibration/test를 분리
- 같은 template의 paraphrase가 서로 다른 split에 들어가지 않도록 함
- 실제 secret은 공개하지 않고 synthetic data 또는 동의·비식별화된 trace만 사용

## 7. Privacy Router prototype

### 7.1 현재 구현에서 재사용할 부분

현재 Privacy Router는 다음 기능을 이미 제공한다.

- Extractor가 문맥에 따라 category와 span을 생성
- `is_essential` 판단
- placeholder masking과 trusted restoration
- `chat_id` 기반 session cache
- OpenAI-compatible proxy
- MCP와 tool-call 처리
- `allow`, `selective_mask`, `local_only`, `ask_user`, `block` action

이 기능은 현재 전송만 보는 비교 방법과 새 prototype의 공통 기반으로 재사용한다.

### 7.2 추가할 최소 기능

1. request에 수신자, 목적, 동작, 목적지 field를 추가
2. 수신자와 목적별 전송 내역 저장
3. 새 전송과 이전 내역을 함께 검사
4. 허용·마스킹·local 처리·질문·차단 중 하나를 선택
5. 실제 전송이 성공한 경우 내역 갱신
6. mock cloud/tool/MCP/memory adapter로 전체 과업 실행
7. 최종 과업 성공 조건을 자동 검사

### 7.3 처리 순서

```text
Agent가 전송 요청
-> 수신자와 목적 표기 통일
-> 민감한 문자열과 의미 추출
-> 해당 수신자와 목적에 대한 허용 규칙 확인
-> 이전 전송 내역과 결합
-> 마스킹 또는 local 실행으로도 과업을 완료할 수 있는지 확인
-> allow | selective_mask | local_only | ask_user | block
-> 지원 adapter로 전송
-> 성공한 전송 기록
```

### 7.4 전송 전 기록과 실패 처리

여러 전송이 동시에 실행되거나 process가 중단되면 실제보다 적게 기록될 수 있다. prototype은 다음 보수적 규칙을 사용한다.

- 전송 직전에 대기 상태 기록
- 전송 성공 시 완료 상태로 변경
- 실패 시 기록 취소 또는 명시적 실패 상태 기록
- 대기 중인 전송이 있으면 같은 민감정보의 추가 외부 전송을 일시적으로 허용하지 않음

이 규칙은 연구용 단일 process 또는 통제된 worker에서만 시험한다. 분산 transaction, 복제본 일관성, 암호학적 결합은 이 연구 범위가 아니다.

### 7.5 마스킹과 원문 복원

- 외부 수신자에게 보낸 placeholder는 외부 응답에 남아 있어도 된다.
- 원문 복원은 처음 요청한 사용자의 신뢰할 수 있는 local UI 또는 명시적으로 허용된 local step에서만 수행한다.
- cloud model, external tool, peer agent가 원문을 요청해도 자동으로 복원하지 않는다.
- 원문 복원도 별도의 외부 전송으로 기록해 누출 계산에 포함한다.

## 8. 비교 방법

### 기본 비교

- 방어 없음
- 모든 민감정보 마스킹
- 현재 Privacy Router
- 현재 전송만 보는 방법
- 직전 전송까지 보는 방법
- 전체 대화 기록을 보는 방법
- 정확한 문자열 일치만 사용하는 전송 내역
- 문장 의미 유사도를 사용하는 전송 내역
- 수신자와 목적별 전송 내역

### 관련 연구 비교

재현 가능한 범위에서 다음 계열과 비교한다.

- Contextual Integrity 기반 query rewriting
- purpose-bound tool privacy checker
- RTBAS-style runtime control
- PAPILLON/PUPA-style local–remote delegation
- PRISM-style cloud–edge routing

공개 code 또는 충분한 specification이 없으면 결과를 직접 재현한 것처럼 쓰지 않는다. 논문만 비교했음을 명시한다.

### 공정한 임곗값 설정

각 방법의 임곗값은 별도의 보정 데이터에서 정하고 테스트 전에 고정한다. 같은 안전 사례 오탐률에서 방법을 비교한다. 점수 간격 때문에 정확히 맞출 수 없으면 목표 이하에서 가장 가까운 보수적 임곗값을 사용하고 실제 오탐률도 함께 보고한다.

## 9. 평가 지표와 통계

### 9.1 개인정보 보호

1. **누출이 발생한 과업의 비율**
   하나 이상의 허용되지 않은 민감정보 누출이 발생한 task의 비율

2. **과업별 누출 탐지율의 평균**
   task마다 누적 누출 중 탐지한 비율을 구한 뒤 task 간 평균

3. **안전한 사례에 대한 오탐률**
   구조가 유사한 안전한 사례를 잘못 차단하거나 마스킹한 비율

4. **첫 누출 및 탐지 시점**
   누출이 처음 완성된 action 번호와 탐지 시점의 차이

### 9.2 과업 성공 및 비용

- 최종 과업 성공 여부
- 평가 기준표에 따른 부분 성공
- 필요한 정보 누락
- 지연 시간
- local 연산량
- 외부 API와 token 비용
- 사용자에게 추가로 질문한 횟수
- 전송 재시도 횟수

### 9.3 통계 계획

- 동일 과업에서 방법을 비교하는 paired design
- 과업 묶음을 고려한 clustered bootstrap 또는 mixed-effects analysis
- 95% 신뢰구간
- 임곗값과 판단 규칙을 테스트 전에 고정
- 예비 실험은 검정력과 분산 추정에만 사용하고 본 실험에서 제외
- 최종 과업 성공률의 비열등성 허용폭은 5%p
- 누적 누출 재현율의 목표 개선은 최소 15%p
- 최종 표본 크기는 예비 실험의 분산과 예상 발생률로 검정력 분석 후 사전 등록

`N >= 300` 같은 숫자를 근거 없이 먼저 고정하지 않는다. 각 주요 검정에 필요한 표본 크기를 별도로 계산한다.

## 10. 성공 기준

주장 가능한 결과는 다음 조건을 모두 만족해야 한다.

1. 동일한 안전 사례 오탐률에서 이전 전송 내역을 사용하는 방법이 현재 전송만 보는 방법보다 누적 누출 재현율을 최소 15%p 높임
2. 전체 대화 기록을 보는 방법과 같거나 더 나은 재현율을 보이면서 저장량 또는 지연 시간을 줄임
3. 현재 Privacy Router 대비 최종 과업 성공률 감소의 95% 신뢰구간이 5%p 이내
4. 결과가 특정 모델 또는 특정 프롬프트에만 의존하지 않음
5. 임곗값, 재시도 규칙, 실패 처리가 사전에 고정됨

조건을 만족하지 못하면 다음과 같이 결과를 축소해 보고한다.

- 이전 전송 내역이 유효한 scenario만 명시
- 특정 표현 또는 수신자 변경에서의 실패 분석
- state representation 간 trade-off
- negative result와 재현 조건

## 11. 기존 연구와 차이

### 가장 가까운 연구

- **Need to Know / DelegateCI-Bench:** 과업에 필요한 민감정보만 cloud LLM에 전달하는 query rewriting과 benchmark
- **ToolPrivacyBench:** tool-using agent에서 목적에 따른 privacy 판단을 평가
- **AgentLeak:** multi-agent 내부 채널의 privacy leakage benchmark
- **Silent Egress:** prompt injection에 의한 agent data leakage
- **RTBAS:** tool-based agent의 prompt injection 및 privacy leakage 제어
- **PAPILLON:** local model과 remote model을 결합한 privacy-preserving delegation
- **PRISM:** entity sensitivity에 따른 cloud–edge routing
- **Contextualized Privacy Defense:** agent 실행 문맥에 따른 privacy control
- **PrivacyLens:** 장기 agent trajectory의 privacy leakage 평가

### 이 연구가 답하려는 빈틈

기존 연구는 각각 query rewriting, tool privacy, internal-channel leakage, prompt injection, local/cloud routing, 또는 trajectory 평가를 다룬다. 이 연구는 다음 조합을 하나의 공개 benchmark에서 직접 비교한다.

1. 동일 과업에서 여러 외부 전송에 걸친 정보 결합
2. 수신자와 목적에 따른 허용 규칙
3. 같은 구조의 안전한 대조 사례
4. 최종 과업 성공까지 실행하는 평가
5. 전송 기록 방식과 실패 조건의 비교

이 다섯 요소 각각이 완전히 새로운 개념이라는 주장은 하지 않는다. 기여는 이들을 재현 가능한 benchmark와 실험 절차로 묶고, 현재 전송만 검사하는 방어의 실패 규모를 측정하는 데 있다.

## 12. Prior-art 검토 규칙

구현 전에 다음을 수행한다.

1. 2026-07-13 cutoff로 arXiv, OpenAlex, Semantic Scholar, Google Scholar, GitHub 재검색
2. 두 명의 독립 reviewer가 source quote를 포함한 claim chart 작성
3. 다음 항목을 기존 연구와 비교
   - 여러 전송 간 누적 정보 결합
   - 수신자와 목적별 정책
   - 같은 구조의 안전 사례에 대한 오탐률
   - 최종 과업 성공
   - 공개 dataset와 재현 가능한 code
4. 기존 공개 연구가 모든 항목을 이미 구현하고 평가했다면 새로운 메커니즘 주장을 중단
5. 그 경우 재현 연구, 더 강한 benchmark, 또는 명확히 확인된 빈틈으로 연구 범위 변경

논문 제목과 초록에서 benchmark 기여를 먼저 제시한다. prototype이 비교 방법보다 반복적으로 우수할 때만 방법 기여를 부차적으로 주장한다.

## 13. 실행 계획

### Phase 0 — 기존 연구 재검토

- 원문 인용이 포함된 비교표
- 독립 reviewer 사이의 불일치 해결
- 새 benchmark인지 재현 연구인지 결정

### Phase 1 — Benchmark 명세

- 과업 데이터 형식
- 외부 전송 데이터 형식
- 수신자와 목적별 정책
- annotation guide
- 과업 성공 평가표

### Phase 2 — Deterministic harness

- mock cloud model
- mock external tool
- mock MCP/peer-agent path
- mock memory and artifact write
- fault injection
- deterministic final-task checker

초기 smoke test는 기존 27개 single-turn case만 사용하고 confirmatory evidence로 사용하지 않는다.

### Phase 3 — Dataset production

- synthetic 과업 생성기
- 분야와 누출 패턴 coverage
- 같은 구조의 안전 사례
- 두 annotator의 독립 labeling
- scenario-family 단위 분할

### Phase 4 — 비교 방법과 prototype

- 현재 Privacy Router 동작 고정
- 이전 전송 내역을 사용하는 비교 방법
- 수신자와 목적별 전송 내역 prototype
- 동일 오탐률 보정
- 예비 실험과 검정력 분석

### Phase 5 — 고정된 조건의 본 실험

- 별도 테스트 세트 실행
- 같은 과업에 대한 개인정보 보호와 과업 성공 비교
- 신뢰구간
- 지연 시간과 API 비용
- 실패 유형 정리

### Phase 6 — 실제 환경 적용 가능성

- proprietary API subset이 가능하면 별도 평가
- 동의·비식별화된 organic Hermes trace와 synthetic scenario의 오류 비교
- 지원 언어와 분야별 결과 보고

## 14. 주요 위험과 대응

| 위험 | 대응 |
|---|---|
| 기존 연구와 완전한 중복 | Phase 0 비교표 후 재현 연구 또는 더 좁은 benchmark로 전환 |
| annotation disagreement | 독립 annotation, adjudication, agreement 공개 |
| synthetic data에만 맞춘 detector | organic trace subset과 같은 구조의 안전 사례 사용 |
| 전체 대화 기록이 항상 우수 | 지연 시간, 저장량, 오탐률까지 함께 비교 |
| 과업 성공 판정이 불안정 | deterministic checker 우선, human rubric은 보조 |
| 전송 내역 손상으로 누출 과소 계산 | failure injection과 대기/완료 상태 검사 |
| 마스킹 후 원문 복원에서 재누출 | 원문 복원도 외부 전송으로 기록 |
| 특정 모델이나 프롬프트에 과적합 | 모델, 프롬프트, 임곗값을 테스트 전에 고정 |
| 공개할 수 없는 raw trace | synthetic 또는 동의·비식별화된 데이터만 배포 |

## 15. 예상 산출물

1. benchmark schema와 annotation guide
2. 공개 가능한 dataset와 validator
3. deterministic multi-step agent harness
4. 현재 Privacy Router와 history baseline adapters
5. stateful Privacy Router prototype
6. preregistration과 power report
7. confidence interval이 포함된 privacy/utility 결과
8. failure taxonomy와 negative-results report

## 16. 기대 기여

### Measurement contribution

per-action privacy filter가 여러 action의 결합에서 얼마나 자주 실패하는지, 같은 false-positive rate와 같은 task workload에서 정량화한다.

### Benchmark contribution

recipient, purpose, multiple channels, cumulative disclosure, matched safe cases, final task success를 함께 포함하는 재현 가능한 평가 자료를 제공한다.

### Empirical contribution

어떤 history representation이 paraphrase, alias, recipient switch, prompt injection, failure에서 강하거나 약한지 분석한다.

### Engineering contribution

Privacy Router를 stateful agent workflow에 적용할 때 필요한 최소 metadata, history update, masking/restoration boundary를 공개한다.

---

# English Proposal

## 1. Research Direction

**Evaluate privacy leakage that emerges across multiple actions in LLM-agent workflows, and test whether defenses that use prior disclosure history prevent more leakage than per-request filters without materially reducing final task success.**

The primary contribution is a benchmark and empirical failure study. A stateful extension of Privacy Router is a prototype for testing the benchmark hypotheses, not a claimed universal security mechanism or formal information-flow guarantee.

## 2. Problem

Tool-using agents send information through several channels: cloud-model requests, tool arguments, MCP messages, memory writes, document writes, and trusted local outputs. A sensitive fact can be split or paraphrased across actions. Each action may appear harmless in isolation, while the recipient can reconstruct the fact from the combined disclosures.

Whether a disclosure is allowed also depends on the recipient and purpose. The same manufacturing result may be necessary for an internal analysis tool but unnecessary for an external comparison service. Evaluation must therefore measure both unauthorized leakage and whether the defended agent still completes the original task.

## 3. Scope

The study covers agent-originated or agent-mediated actions that pass through supported adapters. It does not monitor arbitrary human-authored email or SMS, operating-system traffic, unsupported channels, or compromised hosts.

Five ordinary terms are used:

- **outgoing action:** one agent transmission to a model, tool, peer, memory, document, or local UI;
- **sensitive information item:** one policy-protected item;
- **disclosure history:** information already sent to a recipient for a purpose;
- **unauthorized leak:** the first point at which a recipient can reconstruct a disallowed item;
- **final task success:** whether the defended agent satisfies the original task criteria.

## 4. Research Questions

1. Does recipient- and purpose-specific disclosure history improve cumulative-leak detection over current-action inspection at the same false-positive rate?
2. Which history representation gives the best trade-off among recall, storage, latency, and robustness to paraphrase?
3. Can leakage decrease while final task success remains within a five-percentage-point non-inferiority margin?
4. Where do the defenses fail under split disclosures, paraphrases, aliases, recipient or purpose changes, prompt injection, corrupted history, and partial failures?

## 5. Benchmark

The benchmark contains 4–8-action tasks from personal administration, enterprise operations, research workflows, and healthcare. Channels include cloud-model requests, tool arguments, MCP/peer messages, memory writes, document writes, and trusted local outputs.

Each leakage case has a structurally matched safe case that changes only authorization-relevant context, such as the recipient, purpose, publication status, data subject, or minimum necessary content. Two annotators label each case independently, disagreements are adjudicated, and splits are made by task template and scenario family rather than paraphrase.

Each action records the sender, recipient, purpose, operation, destination, channel, payload, sensitive-information ID, fragment links where applicable, authorization, cumulative disclosure state, expected safe action, and final-task criterion.

## 6. Prototype and Baselines

The prototype reuses Privacy Router's contextual extraction, `is_essential` field, placeholder masking, trusted restoration, session cache, OpenAI-compatible proxy, and MCP/tool-call handling. It adds only:

1. recipient, purpose, operation, and destination metadata;
2. disclosure history indexed by recipient and purpose;
3. checks that combine the current action with prior disclosures;
4. conservative pending/committed updates around external sends;
5. deterministic mock adapters and final-task checks.

Baselines include no defense, blanket masking, current Privacy Router, current-action-only, previous-action-only, full transcript, exact-string history, embedding history, and recipient/purpose-specific history. Reproducible related systems are compared directly; paper-only systems are identified as such.

## 7. Evaluation

Primary privacy measures are:

- percentage of tasks with at least one unauthorized leak;
- task-averaged recall for cumulative leaks;
- false-positive rate on matched safe cases;
- action at which the first leak is completed and detected.

Utility measures are final task success, partial success, required-information omission, latency, local compute, external API cost, user interruptions, and retries.

Thresholds are selected on a disjoint calibration split and frozen before testing. Methods are compared at matched safe-case false-positive rates. Analysis uses paired task comparisons, clustered bootstrap or mixed-effects models, and 95% confidence intervals. Pilot data are used only for variance and power estimation. Confirmatory targets are at least a 15-percentage-point recall improvement and no more than a five-percentage-point reduction in final task success.

## 8. Positioning

The closest work includes Need to Know/DelegateCI-Bench, ToolPrivacyBench, AgentLeak, Silent Egress, RTBAS, PAPILLON, PRISM, Contextualized Privacy Defense, and PrivacyLens. These works cover contextual rewriting, purpose-bound tool privacy, internal-channel leakage, prompt injection, local/cloud delegation, routing, or agent trajectories.

This proposal does not claim that its individual ideas are new. Its defensible contribution is to combine and measure:

1. information accumulated across several agent actions;
2. recipient- and purpose-dependent authorization;
3. matched safe cases;
4. final task completion;
5. alternative history representations and failure conditions.

Before implementation, an independent source-quoted prior-art review determines whether the work proceeds as a new benchmark, a replication, or a narrower gap study.

## 9. Deliverables

1. Benchmark schema, annotation guide, dataset, and validator
2. Deterministic multi-step agent harness
3. Baseline adapters and stateful Privacy Router prototype
4. Preregistration and power analysis
5. Privacy–utility results with confidence intervals
6. Failure taxonomy and negative-results report

---

## Primary References

1. Huang et al., **"Need to Know: Contextual-Integrity-Grounded Query Rewriting for Privacy-Conscious LLM Delegation,"** arXiv:2606.04067, 2026. https://arxiv.org/abs/2606.04067
2. Hu et al., **"ToolPrivacyBench: Benchmarking Purpose-Bound Privacy in Tool-Using LLM Agents,"** arXiv:2606.28061, 2026. https://arxiv.org/abs/2606.28061
3. El Yagoubi et al., **"AgentLeak: A Benchmark for Internal-Channel Privacy Leakage in Multi-Agent LLM Systems,"** arXiv:2602.11510, 2026. https://arxiv.org/abs/2602.11510
4. Lar et al., **"Silent Egress: When Implicit Prompt Injection Makes LLM Agents Leak Without a Trace,"** arXiv:2602.22450, 2026. https://arxiv.org/abs/2602.22450
5. **"RTBAS: Defending LLM Agents Against Prompt Injection and Privacy Leakage,"** arXiv:2502.08966, 2025. https://arxiv.org/abs/2502.08966
6. Li et al., **"PAPILLON: Privacy Preservation from Internet-based and Local Language Model Ensembles,"** arXiv:2410.17127, 2024. https://arxiv.org/abs/2410.17127
7. Zhan et al., **"PRISM: Privacy-Aware Routing for Adaptive Cloud-Edge LLM Inference with Semantic Modulation,"** arXiv:2511.22788, 2025. https://arxiv.org/abs/2511.22788
8. Yang et al., **"Contextualized Privacy Defense for LLM Agents,"** arXiv:2603.02983, 2026. https://arxiv.org/abs/2603.02983
9. **"PrivacyLens: Evaluating Privacy Norm Awareness of Language Models in Action,"** arXiv:2409.00138, 2024. https://arxiv.org/abs/2409.00138
