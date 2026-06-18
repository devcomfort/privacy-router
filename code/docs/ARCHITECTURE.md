# Privacy Router — 아키텍처 설계 문서

## 1. 개요

Privacy Router는 OpenAI Compatible API로 동작하며, 내부에 middle-man 에이전트가 포함되어 있습니다.

```
Client → POST /v1/chat/completions → Middle-Man Agent → [질문 필요 시 409 응답] → Client → 사용자 확인 → Client → 재요청 → 최종 응답
```

## 2. 현재 상태 (As-Is)

### 2.1 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/v1/chat/completions` | POST | OpenAI Compatible 채팅 완료 |
| `/v1/models` | GET | 사용 가능한 모델 목록 |
| `/api/settings` | GET/POST | 에이전트 설정 |

### 2.2 현재 파이프라인

```
User Text → Extractor → Router → Policy Decision
  ├─ allow → 외부 LLM 직접 호출
  ├─ mask_and_send → 마스킹 후 외부 LLM 호출
  ├─ local_api → 로컬 LLM 호출 (실패 시 masked fallback)
  ├─ blocked → 차단 메시지 반환
  └─ prompt_user → 409 응답 (확인 요청)
```

### 2.3 현재 문제점

1. **`prompt_user`는 확인만 요청** — 마스킹 범위 조정 불가
2. **캐시 없음** — 매번 추출 재실행
3. **Middle-Man 로직 분산** — proxy.py에 하드코딩

## 3. 목표 상태 (To-Be)

### 3.1 핵심 변경

| 항목 | 현재 | 목표 |
|------|------|------|
| 확인 요청 | 409 + 헤더 | `status: needs_input` + 구조화된 질문 |
| 마스킹 범위 | 고정 | 사용자 선택 가능 |
| 캐시 | 없음 | SQLite 기반 KV 캐시 |
| Middle-Man | proxy.py 하드코딩 | 별도 모듈화 |

### 3.2 새로운 응답 형식

#### Case 1: 자동 처리 완료 (기존 유지)

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
  "privacy_router": {
    "status": "completed",
    "is_sensitive": true,
    "records": [...],
    "policy_action": "mask_and_send",
    "masking_applied": true,
    "cached": false
  }
}
```

#### Case 2: 사용자 입력 필요 (새로운)

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{"message": {"role": "assistant", "content": null}, "finish_reason": "requires_action"}],
  "privacy_router": {
    "status": "needs_input",
    "question": "민감 정보가 감지되었습니다. 어떻게 처리할까요?",
    "extraction_summary": {
      "is_sensitive": true,
      "record_count": 3,
      "essential_count": 1,
      "records": [
        {"index": 0, "category": "PERSON_NAME", "span": "김동현", "is_essential": false, "confidence": 0.98},
        {"index": 1, "category": "INSTITUTION", "span": "광주과학기술원", "is_essential": false, "confidence": 0.90},
        {"index": 2, "category": "EMAIL", "span": "hong@example.com", "is_essential": false, "confidence": 0.95}
      ],
      "default_action": "mask_and_send"
    },
    "options": [
      {"id": "auto", "label": "자동 처리", "description": "시스템 결정에 따름"},
      {"id": "mask_all", "label": "전체 마스킹", "description": "모든 민감 정보 마스킹"},
      {"id": "mask_essential", "label": "필수만 마스킹", "description": "is_essential=true만 마스킹"},
      {"id": "block", "label": "로컬 처리", "description": "외부 API 대신 로컬 모델 사용"},
      {"id": "custom", "label": "사용자 지정", "description": "레코드별 선택"}
    ],
    "default_option": "auto"
  }
}
```

#### Case 3: 사용자 선택 후 재요청

```json
{
  "model": "privacy-router",
  "messages": [
    {"role": "user", "content": "원본 텍스트..."},
    {"role": "assistant", "content": null, "privacy_router": {"status": "needs_input", ...}},
    {"role": "user", "content": null, "privacy_router": {
      "selected_option": "custom",
      "overrides": [
        {"record_index": 0, "is_essential": true},
        {"record_index": 2, "remove": true}
      ]
    }}
  ]
}
```

## 4. Middle-Man 아키텍처

### 4.1 모듈 구조

```
agents/router/
├── middle_man.py      # Middle-Man Agent (의사결정 로직)
├── cache.py           # SQLite KV 캐시
├── router.py          # 기존 Router (라우팅)
└── schemas.py         # 스키마 정의

server/api/routes/
└── proxy.py           # API 엔드포인트 (Middle-Man 통합)
```

### 4.2 Middle-Man 의사결정 흐름

```python
def process_with_middle_man(text, metadata):
    # 1. 추출 (캐시 확인)
    extraction = extract_with_cache(text, metadata.cache_strategy)
    
    # 2. Middle-Man 판단
    if not extraction.is_sensitive:
        return auto_process(text, extraction)
    
    if metadata.auto_mask:
        if all_confident(extraction, metadata.masking_threshold):
            return auto_process(text, extraction)
        else:
            return ask_user(text, extraction)
    else:
        return ask_user(text, extraction)
```

### 4.3 캐시 전략

| 전략 | 설명 | DB 연산 |
|------|------|--------|
| `auto` | 기본값. HIT → 사용, MISS → 실행 후 저장 | SELECT / INSERT |
| `bypass` | 항상 새로 실행, 저장 안 함 | (none) |
| `refresh` | 새로 실행, 덮어쓰기 | UPSERT |
| `delete` | 삭제 후 새로 실행, 저장 안 함 | DELETE |

캐시 키: 텍스트의 chunked MD5 해시 (4KB 청크 → 병렬 해싱 → 결합 → 재해싱)

## 5. 구현 우선순위

| Phase | 작업 | 상태 |
|-------|------|------|
| 1 | `is_load_bearing` → `is_essential` 마이그레이션 | ✅ 완료 |
| 2 | SQLite KV 캐시 구현 | ✅ 완료 |
| 3 | Middle-Agent 모듈화 | ✅ 완료 |
| 4 | API에 Middle-Man 통합 | 🔲 대기 |
| 5 | `needs_input` 응답 형식 구현 | 🔲 대기 |
| 6 | 사용자 선택 처리 (재요청) | 🔲 대기 |

## 6. MCP vs API 차이

| 항목 | MCP | API |
|------|-----|-----|
| 진입점 | `server/mcp/tools.py` | `server/api/routes/proxy.py` |
| 호출 주체 | AI 에이전트 | 외부 클라이언트 |
| Middle-Man | 에이전트가 `review()`/`decide()` 호출 | 파이프라인 내부 자동 실행 |
| 질문 방식 | 에이전트가 사용자에게 질문 | `status: needs_input` 응답 → 클라이언트가 사용자에게 질문 |
| 상태 관리 | Stateless | Stateless (클라이언트가 컨텍스트 관리) |
| 캐시 | `no_cache` 플래그 | `cache_strategy` 메타데이터 |

---

*Last updated: 2026-06-16*
| 전략 | 설명 | 동작 |
|------|------|------|
| `auto` | 기본값 | 캐시 HIT → 사용, MISS → 실행 후 저장 |
| `bypass` | 캐시 무시 | 항상 새로 실행, 캐시 저장 안 함 |
| `refresh` | 캐시 갱신 | 새로 실행, 캐시 덮어쓰기 |
| `delete` | 캐시 제거 | 캐시 삭제 후 새로 실행, 저장 안 함 |

캐시는 **추출 결과만** 저장 (LLM 응답은 저장 안 함).

## 7. MCP vs API 차이

| 항목 | MCP | API |
|------|-----|-----|
| 진입점 | `server/mcp/tools.py` | `server/api/` |
| 호출 주체 | AI 에이전트 | 외부 클라이언트 |
| Middle-Man | 에이전트가 직접 호출 | 파이프라인 내부 자동 실행 |
| 질문 방식 | `review()` → 에이전트가 사용자에게 질문 | `status: needs_input` → 클라이언트가 사용자에게 질문 |
| 상태 관리 | Stateless (에이전트가 관리) | Stateless (클라이언트가 관리) |
| 캐시 | `no_cache` 플래그 | `cache_strategy` 메타데이터 |

## 8. 구현 우선순위

1. **Phase 1**: 자동 모드 (single-turn) — 기존 `process()` 유지
2. **Phase 2**: Middle-Man 통합 — confidence 기반 자동/질문 분기
3. **Phase 3**: 대화형 모드 (multi-turn) — `needs_input` 응답 + 사용자 선택 처리
4. **Phase 4**: 캐시 전략 — `cache_strategy` 메타데이터 처리

---

*Last updated: 2026-06-16*
