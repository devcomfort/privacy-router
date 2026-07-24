# Experiment Tracker

**Project:** Beyond PII — Context-Dependent Confidential Data Control\
**Created:** 2026-07-22\
**Rule:** planned rows are not evidence; fill result paths only after verified execution.

## Status Legend

- `blocked`: prerequisite missing
- `ready`: all prerequisites met
- `running`: immutable run manifest created
- `complete`: outputs verified
- `invalid`: result excluded under preregistered rule

## Gates

| Gate | Acceptance | Status | Evidence |
|---|---|---|---|
| G0 Novelty audit | Full-text artifact matrix finds no equivalent lifecycle-status minimal-pair benchmark | blocked | — |
| G1 Annotation pilot | Factual-label AC1 ≥0.67; blind single-factor validity ≥90%; no dominant lexical shortcut | blocked | — |
| G2 Dataset freeze | ≥400 semantic scenarios; hierarchy/split/model-view leakage checks pass | blocked | — |
| G3 Evaluator | Literal/atom/derived leakage and all known-answer fixtures match hand calculations | blocked | — |
| G4 Experiment freeze | Primary method/comparator/FPR plus prompt/model/evaluator/test hashes stored | blocked | — |
| G5 Main evidence | E2, E3, transformation/full-system E5, E6 complete | blocked | — |
| G6 Paper-ready | Human utility validation + failure audit + artifact card complete | blocked | — |

## Experiment Registry

| ID | Experiment | Claim | Prerequisite | Primary output | Status | Result path |
|---|---|---|---|---|---|---|
| E0-P | Pilot validity | benchmark validity | G0 | factual agreement, intervention validity, lexical diagnostics | blocked | — |
| E0-F | Full dataset validation | benchmark validity | G1 | hierarchy, split, realism, leakage checks | blocked | — |
| E1 | Baseline sanity | all | G1 | parseability and known-case outcomes | blocked | — |
| E2-D | Detector benchmark, dev | C1/C4 | G3 | fixed-threshold recall, span/$P_0$ compliance | blocked | — |
| E2-T | Detector benchmark, hidden test | C1/C4 | G4 | achieved FPR, recall, language table | blocked | — |
| E3 | Factorial oracle diagnostics | C2 | G3 | conditional improvements and interactions | blocked | — |
| E4 | Calibration and abstention | C5 | E2-D | AURC, excess risk, eventual completion | blocked | — |
| E5 | Transformation + full-system workflows | C3 | G4 | literal/atom/derived leakage and conditional utility | blocked | — |
| E6 | Mask/hydration/stream reliability | C6 | G3 | exactness, byte leakage, upper failure bound | blocked | — |
| E7 | Efficiency | C7 | E2-D | decomposed latency, cost, memory | blocked | — |
| E8 | Ablations | C1/C2/C5 | E2-D | component deltas | blocked | — |
| E9 | Failure audit | limitations | E2-T/E5 | coded error taxonomy | blocked | — |

## Frozen Decisions

| Item | Current decision | May change before |
|---|---|---|
| Primary population | organizational + research secret spans | G4 |
| Primary metric | organizational+research recall at one preregistered safe-FPR threshold | G4 |
| Practical target | point estimate +10pp; superiority requires 95% CI lower bound >0 | after pilot power analysis, before G4 |
| Utility margin | −5pp vs strong privacy-aware baseline, operationally justified | G4 |
| Resampling unit | semantic scenario | never after G2 |
| Languages | English and Korean; translated/independent subsets; shared threshold primary | G2 |
| Core actions | allow, minimize/mask external, approved external, local, ask, deny | G2 |
| Actual-secret policy | synthetic/consented only | never |
| Current usage logs | deployment metadata only | never |

## Run Manifest Template

```yaml
run_id:
experiment_id:
status: planned
benchmark_version:
benchmark_hash:
test_hash:
git_commit:
prompt_hashes: {}
model_input_schema_hash:
policy_profile_hash:
serialized_request_hash:
model:
provider:
endpoint_class: local|external
sampling: {}
thresholds: {}
seed:
started_at:
finished_at:
retry_count:
retry_reasons: []
raw_output_path:
prediction_path:
metrics_path:
notes:
```

## Per-Run Verification

- [ ] `test/*` registry models excluded
- [ ] benchmark and prompt hashes match frozen config
- [ ] serialized request contains `model_input` only; gold-field rejection check passed
- [ ] raw output count equals requested item count
- [ ] parse failures retained as errors
- [ ] retries and provider failures recorded
- [ ] no prompt or secret printed to public logs
- [ ] semantic-scenario cluster bootstrap/permutation used
- [ ] result path exists and metrics regenerate from raw predictions

## Paper Claim Status

| Claim | Required evidence | Status | Allowed wording now |
|---|---|---|---|
| C1 Contextual recall improvement | E2-T + cluster CI | no evidence | research hypothesis only |
| C2 Factual labels enable conditional diagnostics | E3 | no evidence | evaluation design only |
| C3 Leakage superiority + utility non-inferiority | E5 intersection–union result | no evidence | research hypothesis only |
| C4 EN/KO shared-threshold gap | E2-T | no evidence | benchmark intent only |
| C5 Deferral risk–burden trade-off | E4 | no evidence | research hypothesis only |
| C6 Observed reversible-masking reliability | E6 | unit-test evidence exists, benchmark evidence absent | implementation property only; no guarantee |
| C7 Practical overhead | E7 | 46 metadata logs insufficient | measurement plan only |

## Immediate Queue

1. Audit full artifacts for Need to Know, ToolPrivacyBench, RedactionBench, REDACT, PrivacyAlign, AgentSCOPE and adjacent contextual-integrity/DLP work.
2. Freeze separated policy ontology in `policy.md`, plus `model-input.schema.json`, `case.schema.json`, and information-atom rules.
3. Author 20–30 semantic scenarios, create two interventions × two languages, and run blind intervention/annotation pilot.
4. Measure lexical predictability, agreement, scorer reliability, tokens/calls, then run simulation-based power and budget analysis.
5. Only after G0/G1 pass, implement the full benchmark production pipeline.

## English Note

No experiment in this tracker is complete. Existing unit tests validate software behavior, and the 46 organic usage records provide deployment metadata, but neither constitutes evidence for the proposed benchmark claims.
