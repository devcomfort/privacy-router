# Experiment Plan

## Beyond PII: Context-Dependent Confidential Data Control at LLM-Agent Egress

**Date:** 2026-07-22\
**Status:** planned; no result in this document\
**Companion:** `FINAL_PROPOSAL.md`

---

## 0. 실험 원칙

1. **Benchmark claim과 system claim을 분리한다.** Privacy Router가 이기지 않아도 benchmark는 분석 가치가 있어야 한다.
2. **탐지 점수와 end-to-end leakage를 분리한다.** 좋은 span F1이 안전한 routing을 자동으로 의미하지 않는다.
3. **Semantic scenario를 통계 단위로 사용한다.** Intervention, language, paraphrase, repetition을 독립 표본으로 세지 않는다.
4. **Threshold는 dev/calibration에서 고정하고 test의 achieved FPR를 보고한다.** Test 결과에 맞춰 FPR를 사후 조정하지 않는다.
5. **Hidden test는 preregistered condition별로만 실행한다.** prompt, threshold, model, evaluator는 dev에서 끝낸다.
6. **실제 개인정보·secret은 수집하지 않는다.** synthetic values와 consented authoring만 사용한다.
7. **유기적 로그를 benchmark로 위장하지 않는다.** 현재 46개 usage log는 payload text가 없는 metadata다.

---

## 1. Claim–Evidence Matrix

| ID | 논문 주장 | 필수 실험 | Primary metric | 성공 기준 | 실패 시 조치 |
|---|---|---|---|---|---|
| C1 | contextual control이 primary same-backbone baseline보다 비-PII secret을 잘 탐지 | E2 detector benchmark | recall at one preregistered safe-FPR operating point | 95% cluster-CI lower bound >0; practical target point estimate +10pp | 우월성 삭제; benchmark/negative result로 축소 |
| C2 | factual labels가 policy error를 조건부 진단하게 함 | E3 factorial oracle diagnostics | $P_0$ compliance + conditional oracle improvement | component별 오류와 interaction 보고 | universal-necessity/causal wording 삭제 |
| C3 | full system이 strong privacy-aware baseline보다 leakage를 줄이며 utility를 유지 | E5 transformation + routing workflow | semantic/exact leakage + task success | leakage superiority와 utility −5pp non-inferiority 모두 통과 | system claim 삭제 또는 policy 수정 |
| C4 | EN/KO paired evaluation이 언어별 취약점을 드러냄 | E2 shared-threshold language analysis | paired compliance/leakage gap | 결과를 보고; 사전 superiority claim 없음 | gap을 limitation/finding으로 보고 |
| C5 | ask-user abstention의 위험–부담 trade-off를 측정 | E4 selective prediction | AURC, risk at coverage, eventual completion | calibrated deferral이 random rejection보다 낮은 excess risk | confidence 기반 ask 비활성화 |
| C6 | typed masking/hydration의 관찰된 reliability를 측정 | E6 masking reliability | placeholder integrity, hydration, serialized-byte leakage | release gate ≥99.9%; zero failure는 CI와 함께 보고 | deployment readiness claim 중단 |
| C7 | practical overhead가 측정 가능하고 재현됨 | E7 efficiency | decomposed p50/p95 latency, tokens, $/1k, peak memory | 결과 보고; 고정 superiority claim 없음 | deployment guidance만 제공 |

C1과 C3가 main paper의 핵심이다. C2/C4/C5/C6/C7은 설명력과 시스템 완결성을 제공한다.

---

## 2. Work Packages and Run Order

### WP0 — Full-text novelty audit and policy freeze

**목표:** 데이터 제작 전에 중복 연구와 policy ambiguity를 제거한다.

Tasks:

1. Need to Know, RedactionBench, REDACT, ToolPrivacyBench, PrivacyAlign, AgentSCOPE의 full text·dataset·code·license·venue status를 확인한다.
2. contextual integrity, purpose limitation, enterprise DLP, secret scanning, access control/declassification 선행연구도 포함한다.
3. 각 dataset의 unit, information family, context factors, exact span, recipient/purpose authorization, lifecycle status, necessity, action, language를 artifact-level evidence로 코딩한다.
4. 동일 surface span의 lifecycle/authorization controlled pairs와 organizational/research information atoms가 이미 충분한지 확인한다.
5. disclosure state, recipient authorization, purpose authorization, raw-value necessity, policy certainty를 분리한 $P_0$를 고정한다.

**Gate G0:** 기존 artifact가 동일 benchmark를 제공하면 새 dataset 구축을 중단하고 reproduction/extension study로 전환한다.

### WP1 — 80–120 item pilot

**목표:** annotation 가능성과 primary effect의 분산을 확인한다.

- 20–30 semantic scenarios × 2 intervention variants × 2 languages = 80–120 items
- translated와 independently authored EN/KO realization을 구분
- personal, organizational, research, credential family 모두 포함
- factual-label annotator 2명 + blind intervention validator 1명 + adjudicator
- Privacy Router, context-removed, strong contextual direct baseline, fixed-taxonomy same-backbone baseline 실행

Outputs:

- factual-label agreement with confidence intervals
- semantic-equivalence/naturalness and single-factor intervention validity
- ambiguity/adjudication rate
- scenario-level discordant outcomes and lexical-only predictability
- latency/token/call-count distribution
- simulation-based power inputs

**Gate G1:** primary factual-label agreement가 0.67 미만이면 policy와 guide를 수정하고 pilot을 반복한다. blind validator의 single-factor validity가 90% 미만이거나 context-removed baseline이 full-context와 동률이면 lexical/template artifact를 수정한다. 재수정 후에도 실패하면 full benchmark를 중단한다.

### WP2 — Benchmark production

**목표:** 최소 400 semantic scenarios, 평균 3 variants, EN/KO realizations, 총 약 2,600–2,800 items.

- authoring → automatic validation → double annotation → adjudication
- scenario-group split
- hidden test sealing
- datasheet와 license 준비

**Gate G2:** test를 seal한 뒤 schema/policy가 바뀌면 version을 올리고 이전 test를 폐기한다.

### WP3 — Evaluator implementation and frozen dry run

**목표:** 모델 결과 없이 evaluator correctness를 증명한다.

- hand-constructed predictions로 metric unit tests
- source path, overlap, Unicode code-point/UTF-16/UTF-8 mapping tests
- controlled-intervention hierarchy와 split-leakage validation
- model-view serializer가 gold-only fields를 거부하는 tests
- literal, information-atom, derived leakage known-answer tests
- route-policy oracle, cost/latency, blinded report tests

**Gate G3:** synthetic known-answer fixture에서 모든 metric이 수작업 계산과 일치해야 한다.

### WP4 — Development experiments

**목표:** prompt, threshold, top models, baseline configuration을 dev에서 결정한다.

- E1 baseline sanity
- E2 dev detector benchmark
- E3 staged oracle decomposition
- E4 calibration
- E8 ablations

모든 선택을 `FROZEN_CONFIG.json`과 commit SHA로 기록한다.

### WP5 — Hidden test and end-to-end workflows

- hidden test는 frozen config에 등록된 각 method/condition으로 실행
- 오류로 중단된 infrastructure run만 사전 정의된 retry policy로 재실행
- output을 본 뒤 prompt/model/metric을 수정하면 해당 결과를 폐기하고 benchmark version을 올림
- E5/E6/E7 실행

### WP6 — Analysis, artifact release, paper

- confidence intervals와 statistical tests 생성
- failure taxonomy 100건 수작업 audit
- EN/KO paired analysis
- benchmark/model cards, threat model, limitations 작성
- raw prediction, evaluator version, config, cost log 공개

---

## 3. Dataset Specification

### 3.1 JSONL schema

```json
{
  "schema_version": "1.0.0",
  "semantic_scenario_id": "research_release_0042",
  "intervention_variant_id": "status_unreleased",
  "language_realization_id": "ko_independent_01",
  "paraphrase_id": "p0",
  "model_input": {
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user", "content": "..."}
    ],
    "outbound_payload": {"body": "..."},
    "intended_recipient": {
      "identity": "provider_a",
      "trust_boundary": "public_external",
      "transport": "openai_compatible_api"
    },
    "declared_purpose": "draft_summary",
    "policy_profile_id": "P0"
  },
  "gold": {
    "context_factors": {
      "disclosure_state": "confidential",
      "recipient_authorization": "disallowed",
      "purpose_authorization": "allowed",
      "raw_value_necessity": "placeholder_sufficient",
      "policy_certainty": "clear"
    },
    "spans": [
      {
        "source_path": "$.outbound_payload.body",
        "start_codepoint": 18,
        "end_codepoint": 34,
        "text": "synthetic value",
        "information_family": "research",
        "category": "UNPUBLISHED_EXPERIMENT_RESULT",
        "owner_or_subject": "research_group",
        "information_atom_ids": ["atom_1"]
      }
    ],
    "information_atoms": [
      {"id": "atom_1", "proposition": "The unreleased experiment achieved the synthetic result."}
    ],
    "canonical_action": "mask_external",
    "acceptable_actions": ["mask_external", "local"],
    "action_severity": {"allow_external": 3, "ask": 1}
  },
  "provenance": {
    "source_type": "authored_controlled_intervention",
    "intervened_factor": "disclosure_state",
    "author_id": "..."
  }
}
```

`model_input`만 model에 직렬화한다. Evaluator는 `gold` field가 request에 포함되면 run을 거부한다. Span은 `source_path`별 NFC code-point offset으로 저장하고 원문 code point, UTF-16, transmitted UTF-8 byte mapping을 함께 검증한다. Canonical serialized egress bytes를 leakage 판정의 실제 전송 표면으로 사용한다.

### 3.2 Controlled-group templates

#### Status group

- A: “결과는 아직 제출 전이며 외부 공유 금지” → confidential
- B: “결과는 공식 논문으로 공개됨” → public
- 민감 후보 span과 task는 동일

#### Recipient-authorization group

- A: approved enterprise endpoint
- B: unapproved public endpoint
- intended payload, purpose, disclosure state, necessity는 동일

#### Necessity group

- A: exact value가 계산 또는 tool call에 필요
- B: category placeholder만으로 충분
- C: value가 task와 무관

#### Purpose group

- A: 승인된 분석 목적
- B: unrelated marketing/summarization 목적
- information, intended recipient, necessity는 동일

### 3.3 Coverage table

각 cell의 최소 group 수는 pilot 후 균형화한다.

| Axis | Levels |
|---|---|
| Language | English, Korean, code-mixed |
| Family | personal, organizational, research, credential/security |
| Cue distance | same sentence, same turn, previous turn |
| Span count | 0, 1, 2–4, 5+ |
| Expression | direct, implicit, derived, dispersed |
| Payload | chat text, tool argument, structured JSON |
| Policy certainty | clear allow, clear protect, ambiguous/ask |
| Adversarialness | normal, distractor, prompt injection |

Safe controls must include benign numbers, public project names, published results, example credentials, and generic technical phrases.

각 intervention은 최소 두 개의 lexical realization을 갖는다. Blind validator가 intended factor를 모른 채 정확히 한 semantic factor만 바뀌었는지 판정한다. Candidate span/local cue만으로 정답을 예측하는 context-removed baseline과 invariant wording controls로 lexical shortcut을 측정한다.

### 3.4 Naturalistic subset

목적은 authored template artifact를 측정하는 것이다.

- domain practitioner가 자신의 workflow 지식으로 독립 작성
- 실제 secret 없이 synthetic value와 consented·sanitized workflow description 사용
- template author, annotator, evaluator를 분리
- domain expert가 realism과 policy plausibility를 평가
- 200–400 items; independently authored held-out distribution shift로 보고

46 organic usage logs:

- 사용할 수 있는 것: endpoint, route, latency, token, action frequency
- 사용할 수 없는 것: prompt text, span ground truth, semantic category
- 결과표에서 “real-world privacy accuracy” 근거로 사용하지 않음

### 3.5 Annotation protocol

Annotator에게 method output을 보여주지 않는다.

Order:

1. 관찰 가능한 `model_input`만 읽고 candidate sensitive characters와 information atoms를 표시
2. disclosure state를 판단
3. intended recipient authorization과 purpose authorization을 각각 판단
4. task에 raw value가 필요한지 판단
5. 확신이 없으면 unknown과 이유 기록
6. $P_0$ action은 evaluator가 자동 산출하며 annotator action은 policy-validation용으로만 별도 수집

Quality checks:

- gold attention checks 5%
- impossible offset 자동 거부
- span text와 substring 일치 확인
- public/confidential variants의 span surface 동일성 확인
- single-factor pair에서 허용된 metadata 외 차이 자동 검사
- annotator별 speed outlier와 label entropy 점검
- bilingual reviewer의 semantic equivalence, naturalness, Korean particle/affix boundary 확인
- blind single-factor validator agreement와 lexical predictability 확인
- `model_input` serializer에 gold field가 섞이지 않는지 schema test

---

## 4. Systems and Baselines

### 4.1 Privacy Router conditions

- **PR-default:** one-pass contextual extraction
- **PR-high:** extractor + critic review
- **PR-oracle-policy:** gold spans/disclosure/authorization/necessity를 deterministic judge에 입력
- **PR-no-ask:** ambiguous를 가장 높은 confidence action으로 강제

### 4.2 Baseline conditions

#### B0 Unprotected external

원문을 외부 model로 보낸다. Detection metric 대상이 아니라 leakage/utility bound다.

#### B1 Regex + Presidio/PII NER

- 정규식 + 공개 NER
- confidence threshold는 dev safe-FPR에 맞춤
- organizational/research category를 사후에 추가한 handcrafted keyword list는 별도 baseline으로 분리

#### B2 Fixed-taxonomy same-backbone

- 같은 model, sampling, output schema, token budget
- 고정 category 목록만 제공
- ordered contextual questions와 dynamic category derivation 제거
- backbone 효과와 prompt decomposition 효과를 분리

#### B3 Direct contextual classifier

- 같은 model에 confidentiality, necessity, span을 한 번에 직접 요청
- structured question decomposition 없음

#### B4 Rewriting/minimization

- Need to Know 또는 PAPILLON 공개 code가 있으면 원 구현 사용
- 없으면 “paper-guided reimplementation”이라고 표시
- route action이 없으면 exact strings, source-aligned spans, information atoms, derived values, recipient exposure, task utility를 공통 평가

#### B5 Local-only / mask-all

privacy–utility 경계값. 주 baseline ranking에 섞지 않는다.

### 4.3 Model matrix

현재 registry의 실제 모델 중 `test/*`는 반드시 제외한다.

| Tier | Candidate | Role |
|---|---|---|
| local-small | EXAONE-4.0-1.2B | on-device lower-capacity point |
| local-medium | Gemma-4-26B local | local quality/latency point |
| remote-small | Ministral-3B, Granite-4.1-8B, Qwen3.5-9B | cost-sensitive detector comparison |
| remote-medium | Gemma-4-26B, DeepSeek-V4-Flash, Gemini-3.1-Flash-Lite | quality/cost frontier within registry |
| remote-reference | Claude Haiku 4.5 | direct-classifier reference |

모델명, endpoint, provider, release version은 run manifest에 고정한다. 동일 이름이 provider에서 업데이트되면 새 run ID를 만든다.

Run reduction:

1. 모든 후보를 pilot/dev에 실행
2. Pareto frontier에서 top 3를 선정: contextual recall, safe-FPR, latency
3. hidden test와 end-to-end는 top 3 + core baselines만 실행

---

## 5. Metrics

### 5.1 Span metrics

Gold와 prediction은 `(source_path, aligned code-point positions)` 집합으로 비교한다. 서로 다른 field의 같은 문자는 겹침으로 세지 않는다.

$$
\mathrm{Precision}_{char}=\frac{|P\cap G|}{|P|},\quad
\mathrm{Recall}_{char}=\frac{|P\cap G|}{|G|}
$$

- character micro/macro F1; both-empty convention은 preregister
- exact span F1: boundary-only와 category-aware를 둘 다 보고
- entity overlap F1: maximum bipartite matching, IoU threshold를 test 전에 고정
- canonical serialized payload의 source-to-byte coverage
- overlapping/nested span precedence와 normalization mapping을 annotation 전에 고정

### 5.2 Context and action metrics

- disclosure state, recipient authorization, purpose authorization macro-F1
- organizational+research recall at one preregistered safe-FPR
- raw-value necessity macro-F1 conditioned on gold-sensitive spans
- $P_0$ compliance and acceptable-action accuracy
- severity-weighted high-risk confusion

### 5.3 Controlled-intervention metrics

#### Flip accuracy

Gold factual label 또는 policy action이 바뀌는 pair에서 prediction도 올바른 방향으로 바뀐 비율.

#### Invariance accuracy

Gold label/action이 유지되는 wording·language control에서 prediction이 유지되는 비율.

#### Factor-specific intervention sensitivity

disclosure, recipient authorization, purpose authorization, raw-value necessity별로 분리한다. 실제 배포의 causal effect로 해석하지 않는다.

#### Lexical shortcut diagnostics

Context-removed baseline, explicit/implicit cue strata, invariant controls, held-out author/template 성능을 함께 보고한다.

### 5.4 Calibration and abstention

- calibration curve and Brier score; ECE는 secondary
- AURC and selective risk at coverage 50/70/80/90/95/100%
- excess risk relative to random rejection
- risk = any severity-weighted high-risk policy error
- ask rate, eventual completion, added turns/latency by language/family

Threshold는 calibration split에서만 선택하고 bilingual deployment에는 shared threshold 결과를 primary로 보고한다.

### 5.5 End-to-end confidentiality

Layered leakage:

1. **Exact-secret leakage:** inert synthetic credential/identifier의 byte match.
2. **Literal span leakage:** source-mapped gold bytes 중 unauthorized recipient에 전송된 비율.
3. **Information-atom leakage:** paraphrase·translation·summary로 전달된 gold proposition.
4. **Derived leakage:** transmitted content에서 직접 계산·복구 가능한 protected value.
5. **Recipient-specific exposure:** disclosure/recipient/purpose authorization에 따른 event-level violation.
6. **Placeholder side channel:** category, count, length, position과 surrounding context로부터의 inferability.

Reports:

- any unauthorized exposure per task
- exact/literal/atom/derived leakage rates
- credential exact leakage
- route-specific leakage: allow, mask/rewrite, local fallback, stream/tool failure

Placeholder는 literal-value leakage가 아닐 수 있지만 metadata leakage일 수 있으므로 별도 측정한다. Information-atom 판정기는 blinded human subset으로 검증한다.

### 5.6 Utility

Task-specific deterministic scorer가 있으면 우선한다.

| Workflow | Primary utility |
|---|---|
| structured tool call | schema validity + execution success |
| code/technical assistance | hidden tests or required-fact checklist |
| research summarization | required public facts retained, forbidden facts excluded |
| business drafting | rubric-complete content + factual preservation |
| personal assistant | intent completion + necessary-field preservation |

Free-form output:

- blinded pairwise human evaluation on stratified subset
- LLM judge는 auxiliary metric only
- LLM judge는 human subset과 agreement 검증
- presentation order를 swap하여 position bias 점검

Task-success non-inferiority margin은 **primary strong privacy-aware baseline** 대비 −5pp다. Margin은 operational acceptability로 독립 정당화하고, pilot은 scorer reliability와 power만 결정한다. Unprotected external은 utility reference/bound일 뿐 primary comparator가 아니다.

Two utility estimands:

- **Transformation effect:** 동일 downstream model/route에서 raw payload와 mask/rewrite payload 비교.
- **Full-system effect:** 실제 local/external route와 model 변경을 포함하며 route별 conditional utility를 보고.

`ask`는 사용자 응답 protocol, 추가 turn, delay, eventual completion을 포함해 채점한다.

### 5.7 Efficiency

- detector p50/p95 wall latency
- total egress-to-first-token and egress-to-complete latency
- prompt/completion tokens by component
- critic additional calls
- external model cost per 1,000 requests
- local GPU peak memory, utilization, energy if NVML sampling is reliable
- mask/hydration CPU time

Cold start와 warm steady state를 분리한다.

---

## 6. Experiment Definitions

### E0 — Dataset agreement and validity

**Input:** pilot then full annotation.\
**Output:** agreement, ambiguity, adjudication, family/language distribution.

Checks:

- factual-label AC1 with classwise CI
- source-aligned span and information-atom agreement
- blind single-factor intervention validity and language naturalness
- no split leakage by semantic scenario/template/entity/author

### E1 — Baseline sanity

Known cases:

- obvious safe text
- obvious credential
- published research title
- same title marked unreleased
- necessary vs incidental PII
- Korean particle boundary
- JSON tool arguments

All systems must produce parseable standardized output. Parse failure is an error, not dropped data.

### E2 — Main detector benchmark

Design:

- paired/clustered by semantic scenario
- one primary safe-FPR operating point chosen on calibration/dev; 1/5/10%는 secondary curves
- test에서는 threshold를 고정하고 achieved FPR와 CI 보고
- primary PR condition, same-backbone comparator, backbone, safe-case unit을 `FROZEN_CONFIG.json`에 하나씩 지정
- family, language, cue distance, payload, author/template difficulty breakdown

Primary comparison은 frozen PR condition vs fixed-taxonomy same-backbone contextual baseline이다. Strong contextual direct baseline과 PII systems는 secondary다. C1 population은 organizational+research test subset이다.

### E3 — Staged oracle decomposition

Run a factorial oracle diagnostic over:

- predicted/gold span boundary
- predicted/gold disclosure and authorization
- predicted/gold raw-value necessity
- predicted/gold information atoms

All-gold input is the deterministic $P_0$ implementation check. 각 substitution delta는 **conditional oracle improvement**로 보고하며 합산하지 않는다. Interaction이 중요하면 full factorial 또는 Shapley-style decomposition을 secondary analysis로 사용한다. Residual nonzero error는 policy/schema implementation defect다.

### E4 — Calibration and ask-user

- calibration methods: clearly defined confidence source, then temperature scaling or isotonic regression on dev
- compare no-ask, fixed threshold, calibrated threshold, random rejection
- report AURC, high-risk error vs coverage, excess risk, uncertainty
- ask의 subgroup disparity, extra turns/latency, supplied user response, eventual completion 측정

### E5 — End-to-end workflows

Domains:

1. personal assistant/customer support
2. product/business planning
3. research assistant
4. developer/operations tool use

Hierarchy target:

- 30–40 semantic scenarios/domain
- 평균 3 intervention variants × EN/KO
- 약 720–960 language-realized candidate egress events

Conditions:

- strong contextual privacy-aware baseline
- B4 rewrite/minimize
- PR-default
- PR-high
- unprotected external, local-only, oracle는 bounds/subset

Transformation experiment는 같은 downstream model과 route를 고정한다. Full-system experiment는 Privacy Router가 선택한 local/external model을 사용하고 model/route 변화 자체를 cost와 utility에 포함한다. Route-matched와 oracle-route 결과를 추가해 masking effect와 model-capability effect를 분리한다.

### E6 — Masking, hydration, streaming, tool calls

Generated test corpus:

- 100k deterministic placeholder round trips for boundary/collision fuzzing
- Unicode EN/KO, repeated/overlapping spans, substrings, malicious user-supplied placeholder-like strings
- adversarial model responses that copy, mutate, invent, or reorder placeholders
- streaming chunks split at every byte boundary for representative UTF-8/SSE events
- tool arguments, invalid JSON, duplicate call IDs, unknown placeholders

Metrics:

- exact hydration, unrepaired placeholder, incorrect substitution
- canonical sensitive bytes emitted before metadata/policy release
- fail-closed rate for malformed stream/tool call
- zero observed failure일 때 binomial upper confidence bound

This is software reliability evidence, not LLM-quality evidence.

### E7 — Cost and latency

Factorial sample on 200 representative items:

- PR-default vs PR-high
- local-small vs local-medium vs selected remote
- short vs long context
- 0 vs 1 vs 5+ spans

Each local condition: 30 measured repetitions after warm-up.\
Each API condition: enough repeats to estimate provider variance without excessive cost, minimum 5.

### E8 — Ablations

Must-run:

| Ablation | 질문 |
|---|---|
| ordered contextual questions → direct prompt | structured decomposition이 필요한가 |
| dynamic categories → fixed taxonomy | 비-PII generalization이 category freedom 때문인가 |
| critic off | high precision pass가 무엇을 개선/악화하는가 |
| necessity removed → mask-all | task-necessity prediction의 utility 가치가 있는가 |
| ask threshold removed | abstention이 high-risk error를 줄이는가 |
| context removed | 모델이 실제로 surrounding context를 쓰는가 |

Nice-to-have:

- rationale hidden vs requested
- exemplar count
- quantized local model
- different placeholder formats

Ablation은 top 2 backbones와 dev set에서 수행한다. 모든 모델에 전부 반복하지 않는다.

### E9 — Failure analysis

Stratified target of 100 errors, sampled up to:

- 25 false negative
- 25 false positive
- 20 boundary/atom/hydration
- 20 authorization/necessity/action
- 10 EN/KO disagreement

한 category가 부족하면 잔여 표본을 prevalence-proportional로 다른 category에 배분하고 실제 count를 보고한다.

Two analysts independently assign root cause:

- missing world/context knowledge
- policy ambiguity
- long-distance cue failure
- category anchoring
- morphology/boundary
- model output/schema failure
- prompt injection
- routing or hydration bug

Failure taxonomy agreement와 representative examples를 공개한다.

---

## 7. Statistical Analysis Plan

### 7.1 Unit and confidence intervals

- resampling unit: `semantic_scenario_id`
- all variants, languages, paraphrases, repetitions remain inside the cluster
- 10,000 paired cluster-bootstrap/permutation replicates for primary differences
- 95% percentile or BCa CI; exact method frozen before test
- stochastic repetitions are nested measurements, not independent samples

### 7.2 Hypothesis tests

- C1: frozen PR condition vs frozen same-backbone comparator at one dev threshold; superiority if lower 95% cluster-CI >0, practical target if point estimate ≥10pp
- C3: intersection–union of leakage superiority and one-sided 95% utility non-inferiority bound >−5pp
- paired binary/continuous outcomes: semantic-scenario cluster bootstrap or permutation
- multi-factor analysis: mixed-effects model or GEE
  - fixed: method, language, family, factor, difficulty
  - random intercept or cluster: semantic scenario
- multiple secondary comparisons: Holm correction

### 7.3 Power

Pilot의 scenario-level discordance, intracluster correlation, safe-case prevalence, threshold-estimation uncertainty를 이용해 simulation-based power analysis를 수행한다.

Target:

- positive recall superiority with a +10pp practical-effect planning target
- power ≥0.8
- two-sided alpha 0.05
- safe cases sufficient to estimate the primary FPR with useful CI

400 semantic scenarios는 초기 하한이다. Power가 부족하면 scenario 수를 늘리고 variants/languages/repetitions로 독립 표본 수를 부풀리지 않는다.

### 7.4 Missing and failed runs

- parse failure: incorrect prediction
- timeout: timeout category + incorrect; latency censoring rule 사전 고정
- provider 5xx/rate limit: exponential backoff 후 최대 2회 infrastructure retry
- content refusal: model behavior로 집계, 자동 재시도 안 함
- 모든 제외와 retry를 run manifest에 기록

---

## 8. Reproducibility and Contamination Controls

Every run stores:

- benchmark version and test hash
- git commit SHA
- prompt file hashes
- model/provider/version string
- request parameters
- raw output and normalized prediction
- start/end timestamps, latency, retry reason
- route/action and intermediate stage outputs
- evaluator version
- random seed where supported
- exact serialized `model_input` request payload and gold-stripping validation result

Controls:

- authoring template와 model prompt를 분리
- benchmark 문장을 public repository에 공개하기 전 hidden test 완료
- external LLM에 test set 전체를 prompt-tuning 목적으로 반복 전송하지 않음
- LLM-generated seed를 쓰면 human rewriting과 provenance label 추가
- prompt injection text가 annotation instruction에 영향을 주지 않도록 annotator UI에서 분리 표시
- provider contamination은 internal sealing으로 막을 수 없음을 limitation으로 명시하고 가능하면 third-party lockbox/evaluation server 사용

---

## 9. Compute, Cost, and Labor Budget

### 9.1 Calls

Approximate planning envelope:

- pilot: 120 items × 4 systems, PR-high extra critic 포함 ≈ 600 model calls
- dev screening: 약 540 items × 8 models/conditions ≈ 4,320 base calls
- ablations: 약 480 items × 6 conditions × 2 backbones ≈ 5,760 base calls
- hidden test: 약 540 items × 5 selected systems ≈ 2,700 base calls
- end-to-end: 720 events × 4 primary conditions; detector/critic/generation을 분리 집계하여 약 5,000–8,000 requests

Actual count is computed from frozen manifest. 중복 trial은 provider nondeterminism 또는 statistical need가 있을 때만 추가한다.

### 9.2 API cost

Before each phase:

$$
\mathrm{ExpectedCost}=\sum_m N_m\left(\bar{T}_{in}c_{in,m}+\bar{T}_{out}c_{out,m}\right)/10^6
$$

- pilot의 actual serialized input/output tokens와 critic/generation call multiplicity로 비용을 갱신
- preliminary authorization cap: USD 300; projected core evidence가 초과하면 model screening 폭을 줄이고 C1/C3 evidence는 유지
- cap 70%에서 중간 검토
- mutable model pricing/version을 run 시점에 재검증

### 9.3 Local compute

- single local GPU
- soft budget 200 GPU-hours
- local inference는 batch size, quantization, server version을 고정
- OOM은 batch size만 낮추고 model precision 변경 시 새 condition으로 기록

### 9.4 Annotation labor

2,600–2,800 items, double factual annotation + bilingual/intervention validation + adjudication:

- pilot에서 역할별 median annotation time 측정
- preliminary planning range 300–500 person-hours
- full build 전에 실제 pilot time으로 예산 재산정
- domain/bilingual adjudicator 시간을 별도 계산

---

## 10. Artifact Layout

기존 `ground-truth.json`과 historical `eval/results/`는 덮어쓰지 않는다.

```text
experiments/contextual-egress/
├── README.md
├── policy.md
├── schemas/
│   ├── case.schema.json
│   ├── prediction.schema.json
│   ├── model-input.schema.json
│   └── information-atom.schema.json
├── data/
│   ├── pilot.jsonl
│   ├── train.jsonl
│   ├── dev.jsonl
│   └── test.sealed.jsonl
├── prompts/
├── configs/
│   └── FROZEN_CONFIG.json
├── runners/
├── evaluators/
├── tests/
└── results/
    └── <run-id>/
        ├── manifest.json
        ├── raw.jsonl
        ├── predictions.jsonl
        ├── metrics.json
        └── failures.jsonl
```

Release package:

- dataset card
- annotation guide
- threat/policy model
- evaluator with unit tests
- frozen prompts/configs
- baseline adapters
- raw predictions where license permits
- statistical notebook/script
- cost and energy logs

---

## 11. Execution Checklist

### Must run before any paper claim

- [ ] Full-text overlap matrix complete
- [ ] Pilot agreement gate passed
- [ ] Policy ontology separates disclosure/recipient authorization/purpose authorization/necessity/route
- [ ] Model-view serializer and gold-label leakage tests passed
- [ ] Power analysis complete
- [ ] Scenario-group split leakage check passed
- [ ] Metric known-answer tests passed
- [ ] Semantic-atom and derived-leakage known-answer tests passed
- [ ] Core baselines reproduced
- [ ] Matched-FPR operating point frozen
- [ ] Hidden test hash and config frozen
- [ ] E2 detector benchmark complete
- [ ] E3 oracle decomposition complete
- [ ] E5 end-to-end privacy–utility complete
- [ ] E6 masking/hydration reliability complete
- [ ] EN/KO paired analysis complete
- [ ] Human validation of free-form utility complete
- [ ] Failure audit complete

### Nice to have

- [ ] third language
- [ ] quantized local model comparison
- [ ] multimodal payloads
- [ ] long-context stress test above normal workload
- [ ] external organization policy transfer

---

## 12. Reporting Rules

Do report:

- all methods at the preregistered primary threshold plus secondary safe-FPR curves
- predeclared per-family groups and uncertainty-aware worst-group scores
- confidence intervals and sample counts
- parse failure, timeout, refusal, retry
- language and scenario paired results
- negative outcomes

Do not report:

- “100% privacy” from finite benchmark accuracy
- metadata-only usage logs as semantic validation
- one model’s best prompt against another model’s untuned default without disclosure
- aggregate F1 without false-positive and leakage rates
- LLM-judge utility without human validation
- character-only leakage as evidence that semantic rewriting is safe
- arXiv preprint as peer-reviewed venue evidence

---

## 13. First Two-Week Action Plan

### Days 1–2

- literature artifact matrix
- one-page policy semantics
- final JSONL schema

### Days 3–5

- 25 scenario groups authored
- EN/KO counterpart review
- annotator guide and UI/worksheet

### Days 6–7

- triple annotation of pilot
- agreement and ambiguity analysis

### Days 8–10

- baseline adapters
- known-answer evaluator tests
- initial matched-FPR run

### Days 11–12

- power simulation
- schema/policy revision
- stop/go decision

### Days 13–14

- freeze benchmark schema/policy v0.1 after gates, not the final test
- recalculate production authoring, API, GPU, and labor budget
- experiment registry and spending gate activation

The correct next action is **WP0 full-text overlap matrix**, not additional model tuning.

---

## 14. English Execution Summary

The program begins with a full-text artifact audit, a frozen policy ontology, and a 20–30-semantic-scenario pilot. The planning envelope is at least 400 semantic scenarios, roughly three controlled variants per scenario, paired English–Korean realizations, and 200–400 independently authored items. Gold factual labels are physically separated from model-visible input; policy actions are derived under profile P0. The primary detector test compares one frozen Privacy Router condition with one same-backbone fixed-taxonomy baseline at a preregistered threshold and reports achieved test FPR. Conditional oracle diagnostics locate component failures without causal attribution. End-to-end evaluation separates transformation effects from full route/model effects and measures exact, literal, proposition-level, derived, and recipient-specific leakage. Leakage superiority and task-success non-inferiority must both pass. Calibration, user deferral burden, masking/hydration reliability, decomposed latency/cost, bilingual validity, and structured failure analysis are required secondary evidence.
