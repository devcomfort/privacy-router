# API Key Management

Privacy Router의 추론 API는 Bearer 클라이언트 키를 사용합니다. `privacy-router dev`의 브라우저 데모만 짧은 수명의 로컬 세션으로 `/v1/chat/completions`를 호출할 수 있습니다. 배포 모드의 관리 API는 `PRIVACY_ROUTER_ADMIN_PASSWORD`를 브라우저 세션으로 교환한 뒤 사용합니다.

## 관리자 세션 생성

`/admin`에서 비밀번호를 입력하는 방법을 권장합니다. CLI에서는 쿠키와 CSRF 토큰을 함께 보관합니다.

```bash
CSRF_TOKEN=$(curl -sS -c /tmp/privacy-router-admin.cookies \
  -X POST http://localhost:8787/api/admin/session \
  -H "Content-Type: application/json" \
  -d '{"password":"<administrator-password>"}' \
  | jq -r .csrf_token)
```

세션 쿠키는 `HttpOnly`, `SameSite=Strict`, `Path=/api`이며 30분 뒤 만료됩니다. `POST`, `PATCH`, `PUT`, `DELETE` 관리 요청은 같은 세션에서 받은 `X-Privacy-Router-CSRF-Token`도 필요합니다. 비밀번호는 브라우저 저장소나 데이터베이스에 기록되지 않습니다.

평문 HTTP login은 직접 loopback 요청 또는 loopback에만 publish한 기본 Docker Compose에서만 허용됩니다. 다른 host에 노출할 때는 `PRIVACY_ROUTER_ALLOW_INSECURE_ADMIN=0`으로 두고 HTTPS를 종료해야 합니다.

## 클라이언트 키 생성

```bash
curl -b /tmp/privacy-router-admin.cookies \
  -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -H "X-Privacy-Router-CSRF-Token: ${CSRF_TOKEN}" \
  -d '{"name": "hermes-agent"}'
```

응답의 `api_key`는 `pr-...` 형식이며 생성 시 한 번만 표시됩니다. 데이터베이스에는 SHA-256 해시와 식별용 접두사만 저장됩니다.

Docker Compose는 선택적으로 `PRIVACY_ROUTER_API_KEY`를 시작 시 등록할 수 있습니다. 값은 `pr-`로 시작하는 24자 이상의 secret이어야 하며, 원문은 저장되지 않습니다.

## 클라이언트 키 사용

```bash
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer <privacy-router-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"model": "privacy-router", "messages": [{"role":"user","content":"Hello"}]}'
```

## 관리 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/v1/keys` | 키 목록 조회 (`prefix`만 표시) |
| `POST` | `/api/v1/keys` | 새 키 생성 |
| `POST` | `/api/v1/keys/{id}/renew` | 기존 키 비활성화 후 새 키 생성 |
| `PATCH` | `/api/v1/keys/{id}` | 이름 또는 활성 상태 변경 |
| `DELETE` | `/api/v1/keys/{id}` | 키 레코드 삭제 |
| `POST` | `/api/v1/keys/bulk-toggle` | 여러 키의 활성 상태 변경 |
| `POST` | `/api/v1/keys/bulk-delete` | 여러 키 레코드 삭제 |

관리자 로그아웃은 `DELETE /api/admin/session`에 세션 쿠키와 CSRF 토큰을 보내 수행합니다.

## 인증 경계

| 엔드포인트 | 인증 |
|---|---|
| Web UI 정적 페이지, `/v1/models`, `/api/runtime` | 불필요 |
| 관리 엔드포인트 조회 | 관리자 세션 쿠키 |
| 관리 엔드포인트 상태 변경 | 관리자 세션 쿠키 + CSRF 토큰 |
| 배포 모드의 추론·분류·마스킹 엔드포인트 | Bearer 클라이언트 키 |
| `dev` 브라우저의 `/v1/chat/completions` | loopback 전용 데모 세션 |

검증된 클라이언트 키의 데이터베이스 ID가 저장 응답과 마스킹 세션의 소유자 ID가 됩니다. 응답 조회·연결과 마스킹 조회·복원은 동일 소유자만 허용합니다.

## Provider API keys

외부 LLM provider 키는 SQLite나 관리 UI에 저장하지 않습니다. `provider.api_key_env`가 가리키는 서버 환경 변수에서만 읽습니다. 기본 OpenRouter 매핑은 `OPENROUTER_API_KEY`입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/providers` | 환경 변수 이름과 `has_key`, `source` 상태 조회 |

키를 교체하려면 `.env` 또는 배포 secret manager의 값을 바꾸고 서버를 다시 시작합니다. 예전 데이터베이스의 `encrypted_api_key`와 `key_fingerprint` 열은 시작 migration에서 값을 지운 뒤 제거합니다.
