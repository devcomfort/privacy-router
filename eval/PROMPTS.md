# Prompt File Index

## agents/extractor/

| File | Lines | Size | Description |
|------|------:|-----:|-------------|
| `extract.prompt` | 298 | 12KB | **기본 추출 프롬프트** (한국어). Socratic 카테고리 유도, 마스킹 테스트. Ministral 3B 기본. |
| `extract.short.prompt` | 24 | 1.2KB | **압축 프롬프트**. ≤2B 모델용 (4096 ctx 제한). 필수 규칙만 포함. |
| `extract.socratic.prompt` | 131 | 5.2KB | **Socratic CoT 프롬프트**. 3단계 질문 (Identity→Competitive→Harm), severity ordering. 18개 고정 카테고리. |
| `extract.fixed.prompt` | 232 | 7.9KB | **고정 카테고리 프롬프트**. 11개 고정 카테고리 (PII_NUMBER, EMAIL, PERSON_NAME 등). Socratic 대신 사전 정의. |
| `critic.prompt` | 92 | 2.6KB | **2단계 비판 프롬프트**. Phase 1 결과를 검토하여 놓친 span 탐지. Ministral 3B, temp=0.1. |

## agents/judge/

| File | Lines | Size | Description |
|------|------:|-----:|-------------|
| `classify.prompt` | 108 | 6.4KB | **분류 프롬프트**. 민감도 판정 + 정책 결정 (allow/block/selective_mask). Gemini 3.1 Flash Lite 기본. |

## 프롬프트 선택 가이드

```
모델 크기    → 프롬프트 선택
─────────────────────────────
≤ 2B        → extract.short.prompt
3B ~ 4B     → extract.prompt (기본)
> 4B        → extract.prompt 또는 extract.socratic.prompt
```

## 프롬프트 구조 (extract.prompt 기준)

1. **Sensitivity Principle**: 민감 정보 존재 시 is_sensitive=true
2. **Span Rules**: 최소 엔티티 (조사/부사/동사 파생어 제외)
3. **Socratic Category Derivation**: 3단계 질문으로 SCREAMING_CASE 카테고리 유도
4. **Masking Test**: "[MASKED]로 치환 시 의미 유지?" → is_essential 판정
5. **Sensitivity Classification**: AI가 동적으로 SCREAMING_SNAKE_CASE 카테고리 생성 (고정 카테고리 목록 없음)
6. **Output Format**: JSON (sensitivity + records[])
