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

> **분류 안내**: 이 보고서는 최초 발견 사항과 후속 교정을 함께 보존합니다. 과거에 “의도적 수용 위험”으로 분류한 공개 관리 주장은 구현 근거와 일치하지 않아 historical note로 이동했고, 실제 구현 결정은 `docs/dev/adr/`에서 변경 패키지 순서로 기록합니다.

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

### H7·H8. `web/admin.html` 관련 항목(근거 교정)
- **기존 주장**: `web/admin.html`의 모달 CSS 누락과 죽은 네비게이션 링크를 수정함
- **확인 결과**: Git 전체 이력에 `web/admin.html`은 존재하지 않음
- **관련 이력**: `e1262cce`의 별도 `admin/` 프로젝트는 기본 Svelte starter였고 `a2d69994`에서 제거됨
- **현행 UI**: `web/src/routes/admin/+page.svelte`
- **상태**: 과거 감사 주장을 보존하되 구현 근거로 사용하지 않음

---

## 🛡️ 아키텍처 결정 타임라인 교정

기존 ADR은 주제·날짜·상태를 섞었고, 일부 주장은 Git 이력과 일치하지 않았습니다. 현재 기록은 실제 구현 패키지 순서와 근거를 분리합니다. 전체 순서는 [`adr/README.md`](adr/README.md)를 참조합니다.

### ADR-001: SQLite를 기본 데이터베이스로 사용
- **상태**: Accepted; ADR-003에서 재확인
- **최초 확인 구현**: `e1262cce` (2026-06-07)
- **ADR**: [`adr/ADR-001-sqlite-default-database.md`](adr/ADR-001-sqlite-default-database.md)

### ADR-002: 관리 엔드포인트에 전용 관리자 키 사용
- **상태**: Superseded by ADR-003
- **확인 구현**: `ccb32569`의 `X-Privacy-Router-Admin-Key` 경계와 Svelte `/admin`
- **ADR**: [`adr/ADR-002-dedicated-admin-key.md`](adr/ADR-002-dedicated-admin-key.md)

### ADR-003: 브라우저 관리자 세션과 개발·배포 시작 분리
- **상태**: Accepted; ADR-002 대체, ADR-001 재확인
- **현행**: 단기 `HttpOnly` 세션+CSRF, client bearer key, loopback 전용 `dev`, fail-closed `serve`
- **ADR**: [`adr/ADR-003-browser-sessions-and-runtime-startup.md`](adr/ADR-003-browser-sessions-and-runtime-startup.md)

### ADR 순서에서 제외한 기록
- 공개 관리 UI 주장은 완전한 구현 패키지로 확인되지 않아 [`adr/history/2026-06-public-management-proposal.md`](adr/history/2026-06-public-management-proposal.md)에 보존
- 깨진 MCP 테스트 보존은 아키텍처가 아닌 유지보수 정책이므로 [`adr/history/2026-06-deprecated-mcp-test-retention.md`](adr/history/2026-06-deprecated-mcp-test-retention.md)에 보존

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
- `docs/dev/adr/README.md`
- `docs/dev/adr/ADR-001-sqlite-default-database.md`
- `docs/dev/adr/ADR-002-dedicated-admin-key.md`
- `docs/dev/adr/ADR-003-browser-sessions-and-runtime-startup.md`
- `docs/dev/adr/history/`

---

*Last updated: 2026-07-22*
