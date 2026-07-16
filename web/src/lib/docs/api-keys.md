# API Key Management

Privacy Router의 추론 API는 Bearer 토큰 인증을 사용합니다. 클라이언트 API 키는 `pr-{token_urlsafe(32)}` 형식으로 생성됩니다. 모든 관리 API는 별도의 `X-Privacy-Router-Admin-Key` 헤더를 요구하며, 서버의 `PRIVACY_ROUTER_ADMIN_KEY` 값과 일치해야 합니다. 관리 키가 설정되지 않으면 `503`, 헤더가 누락되면 `401`, 값이 틀리면 `403`으로 거부됩니다.

## 키 생성

```bash
curl -X POST http://localhost:8787/api/v1/keys \
  -H "Content-Type: application/json" \
  -H "X-Privacy-Router-Admin-Key: <admin-key>" \
  -d '{"name": "hermes-agent"}'
```

응답:

```json
{
    "id": "4cf89840-1e55-4d38-a9aa-a7ee8ea166df",
    "name": "hermes-agent",
    "api_key": "<privacy-router-api-key>",
    "message": "Store this API key securely. It will not be shown again."
}
```

**중요:** `api_key` 필드는 생성 시에만 반환됩니다. 이후 목록 조회에서는 `prefix`만 확인할 수 있습니다.

## 보안

- 키는 **SHA-256 해시**로 저장됩니다. 원본 키는 데이터베이스에 저장되지 않습니다.
- `pr-` 접두사로 Privacy Router 키임을 식별합니다.
- `token_urlsafe(32)`로 32바이트 암호화 안전 랜덤 생성

## 사용

```bash
curl http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer <privacy-router-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"model": "openrouter/mistralai/ministral-3b-2512", "messages": [...]}'
```

## 관리 API

아래 관리 API는 모두 `X-Privacy-Router-Admin-Key: <admin-key>` 헤더가 필요합니다. 이 관리 키는 추론 요청에 쓰는 `pr-...` 클라이언트 키와 별개입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/v1/keys` | 모든 키 목록 조회 (`prefix`만 표시) |
| `POST` | `/api/v1/keys` | 새 키 생성 |
| `POST` | `/api/v1/keys/{id}/renew` | 기존 키 비활성화 후 새 키 생성 |
| `PATCH` | `/api/v1/keys/{id}` | 이름 또는 활성 상태 변경 |
| `DELETE` | `/api/v1/keys/{id}` | 키 레코드 삭제 |
| `POST` | `/api/v1/keys/bulk-toggle` | 여러 키의 활성 상태 변경 |
| `POST` | `/api/v1/keys/bulk-delete` | 여러 키 레코드 삭제 |

## 키 갱신

기존 키를 비활성화하고 새 키를 생성합니다. 경로의 `id`에는 목록 API가 반환한 UUID를 사용합니다.

```bash
curl -X POST http://localhost:8787/api/v1/keys/4cf89840-1e55-4d38-a9aa-a7ee8ea166df/renew \
  -H "X-Privacy-Router-Admin-Key: <admin-key>"
```

## 인증 경계

| 엔드포인트 | 인증 |
|---|---|
| Web UI 정적 페이지, `/v1/models` | 불필요 |
| 키·모델·Provider 키·settings·profiles·dashboard 관리 엔드포인트 | `X-Privacy-Router-Admin-Key` 필요 |
| `/v1/chat/completions`, `/v1/responses`, `/api/v1/classify`, `/api/v1/generate`, `/api/v1/masking/*` | Bearer 클라이언트 키 필요 |

인증된 요청에서 검증된 API 키의 데이터베이스 ID가 저장 응답과 마스킹 세션의 소유자 ID가 됩니다. 응답 조회·연결과 마스킹 조회·복원은 동일한 소유자 ID만 허용합니다.

## Provider API Key Management

Provider API keys (for outbound LLM calls) are stored encrypted in the `provider` table.

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/providers` | 프로바이더 목록 (`has_key`, `key_fingerprint`, `source` 포함) |
| `POST` | `/api/providers/{id}/key` | API 키 암호화 저장 |
| `DELETE` | `/api/providers/{id}/key` | API 키 삭제 |

### Provider 키 저장

```bash
curl -X POST http://localhost:8787/api/providers/openrouter/key \
  -H "Content-Type: application/json" \
  -H "X-Privacy-Router-Admin-Key: <admin-key>" \
  -d '{"api_key": "<openrouter-api-key>"}'
```

키는 Fernet(AES-128-CBC)으로 암호화되어 `provider.encrypted_api_key`에 저장됩니다.
`key_fingerprint`는 키의 앞뒤 문자가 아니라, 키 조각을 노출하지 않는 16자리 도메인 분리 HMAC 지문입니다.

### 키 확인 체인

LLM 호출 시 키는 다음 순서로 확인됩니다:

1. `provider.encrypted_api_key` (DB, 암호화된 키)
2. `env[api_key_env]` (환경변수, 예: `OPENROUTER_API_KEY`)
3. `OPENROUTER_API_KEY` (fallback)
