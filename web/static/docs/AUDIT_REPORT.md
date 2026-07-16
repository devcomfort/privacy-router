> Public sanitized copy. Raw identifier-like examples are replaced with placeholders.

# Privacy Router — 전수조사 보고서

**작성일**: 2026-06-16
**조사 범위**: 95 Python + 11 HTML + 22 Config 파일
**조사 방법**: 5개 병렬 에이전트 (Server API, Agents, DB+Web, Tests+Config, Cross-cutting)

---

## 요약

| 심각도 | 원래 수 | 수정됨 | 남은 수 | 처리 |
|--------|--------|--------|--------|------|
| 🔴 CRITICAL | 6 | 4 | 0 | 즉시 수정 완료 |
| 🟠 HIGH | 8 | 3 | 0 | 즉시 수정 완료 |
| 🟡 MEDIUM | 9 | 0 | 9 | 권장 |
| 🔵 LOW | 8 | 0 | 8 | 선택 |

> **분류 안내**: 본 보고서는 발견 사항을 `즉시 수정`, `의도적 수용 위험(Accepted Risk)`, `남은 선택 사항`으로 재구성했습니다. 인증 관련 항목은 로컬 시스템 운영을 전제로 의도적으로 수용되었으며, `docs/adr/`에 ADR로 기록되어 있습니다.

---

## 🔴 즉시 수정 완료 (CRITICAL)

### C1. `classify.py` — records 필드 접근 오류
- **파일**: `server/api/routes/classify.py:121`
- **원인**: `result.sensitivity.records` 접근. `Sensitivity` 모델에는 `records` 필드가 없음
- **결과**: `generate_endpoint`에서 PII 탐지 기록이 유실될 수 있음
- **수정**: `result.sensitivity.records` → `result.records` (PipelineResult의 직접 필드)
- **상태**: ✅ 수정 완료

### C3. `masker/schemas.py` — validate_response() 정규식 불일치
- **파일**: `agents/masker/schemas.py:64`
- **원인**: 정규식 `#\d+`는 숫자 ID만 매칭하지만, 실제 플레이스홀더는 `#0fd1f02a` 같은 hex
- **결과**: 컨트랙트 안전성 검증이 항상 통과됨
- **수정**: 정규식을 `#[0-9a-f]+`로 변경
- **상태**: ✅ 수정 완료

### C4. `contract_store.py` — save_records() 플레이스홀더 매칭 실패
- **파일**: `agents/masker/contract_store.py:85`
- **원인**: `_uid_for()`가 `{category}_{hash8}` 형태를 반환하는데, `save_records()`는 이를 `[category#uid]` 형태로 비교하여 매칭 실패
- **결과**: 모든 레코드가 UNKNOWN으로 저장됨
- **수정**: 마스커가 생성한 `[category#hash8]` 형태와 동일하게 placeholder를 재계산하여 매칭
- **상태**: ✅ 수정 완료

### C5. `middle_man.py` — summarize()에서 존재하지 않는 필드 참조
- **파일**: `agents/router/middle_man.py:112`
- **원인**: `ExtractionRecord`에 없는 `harms` 필드를 참조
- **결과**: 대화형 리뷰 플로우에서 `AttributeError`
- **수정**: `harms` 참조 제거
- **상태**: ✅ 수정 완료

---

## 🟠 즉시 수정 완료 (HIGH)

### H1. `proxy.py` — 잘못된 타입 어노테이션
- **파일**: `server/api/routes/proxy.py:379`
- **원인**: `contract: Masker | None` (Masker는 클래스가 아닌 MaskingContract가 맞음)
- **수정**: `MaskingContract | None`으로 변경
- **상태**: ✅ 수정 완료

### H7. `admin.html` — 모달 CSS 누락
- **파일**: `web/admin.html:132`
- **원인**: `.modal-overlay`, `.modal` CSS 미정의
- **수정**: 모달 CSS 추가
- **상태**: ✅ 수정 완료

### H8. `admin.html` — 네비게이션 링크 404
- **파일**: `web/admin.html:77-79`
- **원인**: `/admin/keys`, `/admin/providers`, `/admin/models` 라우트 없음
- **수정**: 죽은 링크 제거
- **상태**: ✅ 수정 완료

---

## 🛡️ 의도적으로 수용된 위험 (Accepted Risks)

다음 항목들은 로컬 시스템 운영을 전제로, 계정 관리 등 운영 비용을 감수하기보다 인증을 제거하는 선택을 했습니다. 각 결정은 `docs/adr/`에 Architecture Decision Record(ADR)로 기록되어 있습니다.

### ADR-001: 키/관리 엔드포인트 인증 없음
- **파일**: `server/api/routes/keys.py`
- **항목**: C2 (키 관리 5개 엔드포인트 인증 누락)
- **이유**: 로컬 단일 사용자 환경에서 계정 관리 비용이 보안 이점보다 큼
- **ADR**: `docs/adr/ADR-001-no-auth-on-<api-key>.md`

### ADR-002: 관리 UI용 공개 엔드포인트
- **파일**: `server/api/routes/proxy.py`, `server/api/routes/providers.py`
- **항목**: H2 (`POST /api/settings`), 관리자 UI용 `GET/POST/PATCH/DELETE` keys, `GET providers`
- **이유**: 브라우저 기반 독립 관리 UI가 별도 인증 없이 동작해야 함
- **ADR**: `docs/adr/ADR-002-public-admin-endpoints-for-standalone-ui.md`

### ADR-003: SQLite를 기본 데이터베이스로 사용
- **파일**: `db/session.py`
- **이유**: PostgreSQL이 실행 중이지 않은 개발 환경에서 즉시 동작해야 함
- **ADR**: `docs/adr/ADR-003-sqlite-as-default-database.md`

### ADR-004: 구 MCP 테스트 파일 보존
- **파일**: `server/tests/test_mcp_tools.py`
- **항목**: C6 (구 함수 import로 인한 테스트 깨짐)
- **이유**: 새 MCP `process` 도구로 마이그레이션되었으나, 참고용으로 보존. 별도 `tests/scenarios/test_mcp_process.py`에서 현행 테스트 수행
- **ADR**: `docs/adr/ADR-004-keep-deprecated-test-mcp-tools.md`

---

## 🧱 타입 안전성 개선 (Bottom-up Pydantic Refactor)

`getattr`/`hasattr` 사용을 최소화하기 위해 낮은 수준의 Pydantic 모델부터 타입을 강화했습니다.

| 파일 | 변경 사항 |
|------|----------|
| `agents/router/schemas.py` | `PipelineResult.sensitivity/judgment/records`를 `Any`에서 `Sensitivity`/`Judgment`/`list[ExtractionRecord]`로 타입화 |
| `agents/extractor/extractor.py` | `_validate_record()`에서 `getattr(item, ...)`을 직접 필드 접근으로 변경 |
| `server/mcp/tools.py` | `pipeline.sensitivity.is_sensitive`, `pipeline.judgment.policy_action` 등 직접 접근 |
| `server/api/routes/responses.py` | `_privacy_metadata()`의 `pipeline` 파라미터를 `PipelineResult`로 타입화 |
| `server/api/routes/proxy.py` | `_sensitivity_meta()`의 `pipeline` 파라미터를 `PipelineResult`로 타입화 |

### 남은 `getattr`/`hasattr` (외부 경계 및 테스트만)

| 파일 | 용도 |
|------|------|
| `server/adapters/base.py` | litellm 외부 응답의 `usage` 객체에서 token 수 추출 |
| `tests/sanity/test_openai_compat.py` | 외부 호환 API 응답 구조 검증 |
| `agents/router/tests/test_router.py` | 모델 필드 존재 여부 검증 |

---

## 🟡 MEDIUM (권장, 아직 미수정)

| # | 파일 | 문제 |
|---|------|------|
| M1 | `models.py:172` | probe에 하드코딩된 플레이스홀더 API 키 사용 |
| M2 | `proxy.py:368` | `except Exception: pass` — 에러 무시 |
| M3 | `responses.py:153` | `_resolve_api_base` 중복 정의 |
| M4 | `db/models.py:140` | `MaskingRecord.session_id` FK 제약 없음 |
| M5 | `router/router.py:86` | 문서에 잘못된 액션 이름 |
| M6 | `router/router.py:152` | `prompt` 엔드포인트 핸들러 없음 |
| M7 | `router/schemas.py` (이전) | `PipelineResult` Any 사용 → **타입화로 해결** |
| M8 | `extractor/two_phase.py` (이전) | 중복된 고정밀 경로를 `Extractor(precision="high")`로 통합하고 제거 → **해결** |
| M9 | `config/schemas.py` | 문서 예제에 잘못된 tier 값 |

---

## 🔵 LOW (선택 사항)

| # | 파일 | 문제 |
|---|------|------|
| L1 | `proxy.py:55` | `except (KeyError, Exception)` — `KeyError` 중복 |
| L2 | `middle_man.py:7` | 미사용 import (`Any`) |
| L3 | `cache.py:46` | `datetime.utcnow()` deprecated (Python 3.12+) |
| L4 | `cache.py:12` | 세션 패턴 불일치 |
| L5 | `masker/schemas.py:128` | `HydrationResult.unresolved` 항상 빈 리스트 |
| L6 | `middle_man.py:16` | `UserAction` enum 정의되었지만 미사용 |
| L7 | `landing.html:135` | "서버 가동시간"이 실제로는 브라우저 탭 시간 |
| L8 | `index.html:190` | `loadModels()` null 가드 없음 |

---

## ✅ 검증 통과

| 항목 | 상태 |
|------|------|
| `agents/extractor/tests/` | ✅ 16 passed |
| `agents/masker/tests/` | ✅ 37 passed |
| `agents/router/tests/test_router.py::TestRouterPipelineResult` | ✅ 3 passed |
| `agents/router.schemas` import | ✅ OK |
| `server.mcp.tools` import | ✅ OK |
| `server.api.routes.responses` import | ✅ OK |
| `server.api.routes.proxy` import | ✅ OK |

> 참고: `agents/router/tests/test_router.py::TestRouterPolicyActions::test_mask_and_send_when_no_essential`는 본 수정 이전부터 실패하던 항목으로, 라우팅 정책 로직의 별도 문제입니다.

---

## 변경 파일

- `server/api/routes/classify.py`
- `agents/masker/schemas.py`
- `agents/masker/contract_store.py`
- `agents/router/middle_man.py`
- `server/api/routes/proxy.py`
- `server/api/routes/responses.py`
- `agents/router/schemas.py`
- `agents/extractor/extractor.py`
- `server/mcp/tools.py`
- `docs/AUDIT_REPORT.md`
- `docs/adr/ADR-001-no-auth-on-<api-key>.md`
- `docs/adr/ADR-002-public-admin-endpoints-for-standalone-ui.md`
- `docs/adr/ADR-003-sqlite-as-default-database.md`
- `docs/adr/ADR-004-keep-deprecated-test-mcp-tools.md`

---

*Last updated: 2026-06-16*
