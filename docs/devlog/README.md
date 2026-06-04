# Privacy Router — Extractor·Judge 평가 보고서

> **개발 이력 (Development Artifact)**  
> 이 디렉토리는 Privacy Router의 핵심 파이프라인인 Extractor + Judge에
> 최적의 LLM 모델을 선정하고 프롬프트를 개선해 나간 과정을 기록합니다.
> 특히 **프롬프트 엔지니어링만으로 작은 모델의 컨텍스트 기반 탐지 능력을
> 획기적으로 개선**한 사례를 문서화합니다.

---

## 디렉토리 구조

```
docs/devlog/
├── README.md                    # 이 파일 — 개요 및 내비게이션
├── REPORT.md                    # 종합 보고서 (실험 설계, 결과 분석, 결론)
├── eval.py                      # 평가 스크립트 (N=5 반복 실행)
├── logs_v1/                     # Phase 1: 모델별 N=5 평가 로그 (9개 모델)
│   ├── gemini-3.1-flash-lite.log
│   ├── ministral-3b-2512.log
│   ├── deepseek-v4-flash.log
│   └── ... (6 more)
└── logs_v2/                     # Phase 2: 개선된 프롬프트 평가 로그 (7개 모델)
    ├── gemini-3.1-flash-lite.log
    ├── ministral-3b-2512.log
    ├── edge_cases.log
    └── ... (5 more)
```

---

## 프롬프트 개선 여정

### Phase 1 — 패턴 매칭 기반 (v1)

초기 Extractor 프롬프트는 구체적인 키워드 단서에 의존했습니다:

- "주민등록번호" 같은 PII 패턴
- "결정", "채택" 같은 의사결정 표현
- "아이디어", "미공개" 같은 연구 관련 표현

**결과:** `gemini-3.1-flash-lite`만 사업/연구 기밀을 탐지했고,
모든 오픈소스 모델(ministral, deepseek, qwen, granite 등)은
컨텍스트 기반 탐지에 실패했습니다.

### Phase 2 — 맥락적 추론 기반 (v2)

프롬프트에 두 개의 **질문 형태 추론 가이드**를 추가했습니다:

> "이 문장이 내일 신문에 실린다면, 경쟁사가 이득을 볼까?"
> "출판 전에 이 텍스트가 공개된다면, 연구자가 피해를 볼까?"

**결과:** 추가 비용 없이 6개 모델의 사업/연구 기밀 탐지율이 0% → 100%로
개선되었습니다. `ministral-3b-2512` ($0.10/1M tok) 가 `gemini-3.1-flash-lite`
($0.25/1M tok) 와 동등한 성능을 달성했습니다.

---

## 핵심 교훈

> **컨텍스트 기반 민감 정보 탐지는 모델 크기가 아니라 프롬프트 설계에 의해 결정된다.**

작은 모델은 추상적 규칙을 일반화하는 능력이 부족하지만,
구체적인 질문 형태의 가이드는 모델이 이미 가진 상식 추론 능력을 활성화시킵니다.
"단어를 찾는 것"이 아니라 "결과를 상상하는 것"을 요구하는 것이 핵심입니다.

---

## 관련 코드

| 컴포넌트 | 경로 |
|----------|------|
| Extractor 프롬프트 | `packages/extractor/classifiers/slm.py` |
| Judge 프롬프트 | `packages/judge/classifier.py` |
| 평가 스크립트 | `docs/devlog/eval.py` |

---

## 읽는 순서

1. **REPORT.md** — 실험 설계, Phase 1·2 결과, 분석, 결론을 담은 종합 보고서
2. **logs_v1/** — Phase 1 원시 로그 (모델별 N=5 반복)
3. **logs_v2/** — Phase 2 원시 로그 (개선된 프롬프트 적용)
4. **eval.py** — 평가 자동화 스크립트 (재현용)

---

*기간: 2026-06-02 ~ 2026-06-03*
