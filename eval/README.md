# Privacy Router — Evaluation Package

이 패키지는 Privacy Router extractor의 모델 평가를 재현하기 위한 모든 자료를 포함합니다.

## Quick Start

```bash
# 1. 모델 가중치 다운로드
bash eval/download_models.sh

# 2. 엔진 시작 (예: vLLM + Gemma4 E4B)
docker compose -f docker-compose.yml -f docker-compose.engines.yml --profile vllm-e4b up -d

# 3. 평가 실행 (5 trials)
bash eval/run_eval.sh --model gemma4-e4b-vllm --trials 5

# 4. 결과 확인
bash eval/run_eval.sh --report
```

## Directory Structure

```
eval/
├── README.md              ← 이 파일
├── download_models.sh     ← 가중치 다운로드 스크립트
├── run_eval.sh            ← 평가 실행 스크립트
└── NOTES.md               ← 모델/엔진별 주의사항

scripts/
├── eval_runner.py         ← 통합 평가 러너 (N≥5 trials, 멀티턴)
├── tune_params.py         ← Optuna 파라미터 튜너
└── eval_all.py            ← 기존 평가 러너 (레거시)

test_data/
├── __init__.py
├── adversarial_conversations.py  ← 적대적 케이스 (5 conversations)
├── researcher_conversations.py   ← 연구자 페르소나 (5 conversations)
└── student_conversations.py      ← 학생 페르소나 (5 conversations)

agents/extractor/
├── extract.prompt         ← 기본 추출 프롬프트 (한국어)
├── extract.short.prompt   ← ≤2B 모델용 압축 프롬프트
├── extract.socratic.prompt ← Socratic CoT 프롬프트
├── extract.fixed.prompt   ← 고정 카테고리 프롬프트
└── critic.prompt          ← 2단계 비판 프롬프트

docs/experiments/results/  ← 평가 결과 JSON
docs/developments/results/tuning/ ← Optuna 튜닝 JSON
```

## 평가 지표

### 전체 지표
- **Sensitivity Accuracy**: 민감/비민감 판정 정확도
- **Action Accuracy**: 정책 결정 (allow/block/selective_mask) 정확도
- **JSON Validity**: 모델 출력 JSON 파싱 성공률

### 표면별 지표
- **형태적 (Pattern-based)**: PII (주민등록번호, 전화번호, 이메일, 실명) — 패턴 기반 감지
- **맥락적 (Context-based)**: 사업비밀, 연구아이디어, 전략, 예산, 내부URL — 맥락 기반 감지
- **False Positive Rate**: 비민감 케이스에서의 위양성 비율

## 테스트 데이터셋

### 단일 턴 (17 cases)
| Category | Cases | Tags |
|----------|-------|------|
| PII (형태적) | 6 | identity |
| 사업비밀 (맥락적) | 5 | competitive, creation/statement |
| 연구비밀 (맥락적) | 2 | competitive, consultation |
| 비밀유지마커 | 1 | competitive, statement |
| 안전 (내부URL) | 1 | safety, consultation |
| 비민감 | 3 | none |

### 멀티턴 (15 conversations, 46 user turns)
| Persona | Conversations | Description |
|---------|--------------|-------------|
| 학생 (GIST) | 5 | PII 유출, 연구 비밀 |
| 연구자 (삼성) | 5 | 사업 비밀, 예산, 전략 |
| 적대적 | 5 | 회피, 위양성, 점진적 공개 |

## 모델별 최적 파라미터

| Model | temp | top_p | json_mode | sys_msg | Action% |
|-------|------|-------|-----------|---------|---------|
| Gemma4 E4B vLLM | 0.0 | 1.0 | false | false | 76.5% |
| Ministral 3B OpenRouter | — | — | — | — | 71.8% |
| EXAONE 1.2B vLLM | 0.5 | 0.75 | false | false | 42.4% |
| Gemma4 E2B vLLM | 0.25 | 0.75 | true | true | 28.2% |

## 재현 방법

### 1. 환경 설정
```bash
# Python 의존성
pip install litellm optuna httpx

# Docker 이미지
docker pull vllm/vllm-openai:nightly
docker pull ghcr.io/ggml-org/llama.cpp:server
```

### 2. 가중치 다운로드
```bash
# 전체 다운로드
bash eval/download_models.sh

# 특정 모델만
bash eval/download_models.sh --model exaone-1.2b
bash eval/download_models.sh --model gemma4-e4b

# 캐시 경로 지정
bash eval/download_models.sh --path /custom/cache
```

### 3. 엔진 시작
```bash
# vLLM + Gemma4 E4B
docker compose -f docker-compose.yml -f docker-compose.engines.yml --profile vllm-e4b up -d

# vLLM + EXAONE 1.2B
docker compose -f docker-compose.yml -f docker-compose.engines.yml --profile vllm-exaone up -d

# llama-server + EXAONE 1.2B GGUF
docker compose -f docker-compose.yml -f docker-compose.engines.yml --profile llama-exaone up -d
```

### 4. 평가 실행
```bash
# 단일 모델, 5 trials
bash eval/run_eval.sh --model gemma4-e4b-vllm --trials 5

# 전체 모델
bash eval/run_eval.sh --all --trials 5

# 결과만 보기
bash eval/run_eval.sh --report

# 엔진 상태 확인
bash eval/run_eval.sh --check
```

### 5. 파라미터 튜닝 (선택)
```bash
# Optuna 20 trials
python3 scripts/tune_params.py --model gemma-4-e4b-bf16 --trials 20
```

## 결과 해석

### 표면별 정확도 (Gemma4 E4B vLLM 기준)
```
형태적 (Pattern): 83.3% — PII 잘 감지
맥락적 (Context): 62.5% — 사업비밀/연구아이디어 감지 어려움
전체: 76.5%
False Positive: 0% — 위양성 없음
```

### 통계적 유의성
- EXAONE 1.2B vLLM vs llama: t=0.728, p≥0.05 (유의미하지 않음)
- N=5 trials로 충분한 분산 확보
