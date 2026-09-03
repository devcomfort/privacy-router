# 시작하기

## 사전 조건

- Python 3.13+
- 기본 로컬 모델을 위한 Docker, Docker Compose, NVIDIA Container Toolkit
- Gemma 4 26B를 위한 가용 가속기 또는 통합 메모리 64 GB 이상
- 배포가 OpenRouter로 라우팅될 수 있는 경우에만 OpenRouter 키

## 빠른 시작

```bash
git clone https://github.com/devcomfort/privacy-router.git
cd privacy-router
cp .env.example .env
python -m pip install -e .
```

루프백 전용 키 없는 브라우저 데모를 시작한다. 첫 번째 명령은 Gemma 4 26B를 다운로드하고 서버를 구동한다; 두 번째 명령은 다른 터미널에서 실행한다:

```bash
./scripts/start_vllm.sh gemma4
privacy-router dev
```

배포를 위해 `.env`에서 `PRIVACY_ROUTER_MASTER_KEY`, `PRIVACY_ROUTER_ADMIN_PASSWORD`, 공급자 환경 변수를 설정한 후 `docker compose up -d`를 실행한다.

## Docker Compose 프로파일

Compose `profiles`는 선택적 서비스를 활성화한다:

| 프로파일 | 서비스 | 목적 |
|---|---|---|
| _(없음)_ | db, api | 핵심 배포 |
| `hermes` | hermes | Hermes Agent 데모 |

### 동작

- 프로파일이 없는 서비스는 항상 `docker compose up`로 시작한다.
- 프로파일이 있는 서비스는 해당 프로파일이 활성화된 때만 시작한다.
- 선택된 Compose 파일이 정의할 때 프로파일은 조합할 수 있다.

### 사용

```bash
# Core deployment
docker compose up

# Include Hermes Agent
COMPOSE_PROFILES=hermes docker compose up -d

# Persist the profile choice
echo "COMPOSE_PROFILES=hermes" >> .env
docker compose up
```

## Hermes Agent 데모 모드

Hermes Agent 컨테이너는 `HERMES_CONFIG`를 통해 Privacy Router 통합 모드 3가지를 지원한다:

| 설정 | 모드 | 작동 방식 |
|--------|------|-------------|
| `config-api.yaml` | API Proxy | 모든 LLM 호출이 자동으로 Privacy Router를 통과한다. 투명 — agent 동작 불필요. |
| `config-mcp.yaml` | MCP Tool | LLM 호출은 모델에 직접 연결한다. Agent는 필요 시 `privacy-router.process()`를 명시적으로 호출한다. |
| `config-privacy-router.yaml` | 결합 | API 프록시 + MCP 도구를 동시에 사용 가능 (기본값). |

```bash
# API Proxy mode — automatic protection
HERMES_CONFIG=api docker compose up -d hermes

# MCP Tool mode — explicit protection
HERMES_CONFIG=mcp docker compose up -d hermes

# Combined mode (default)
docker compose up -d hermes
```

Management API와 `/admin`은 단기 보안 세션을 위해 `PRIVACY_ROUTER_ADMIN_PASSWORD`를 교환한다. 상태 변경 요청은 추가로 세션의 CSRF 토큰을 요구한다. 공급자 자격 증명은 서버 환경 변수로 유지되며 UI에서 읽기 전용이다.

Docker Compose는 기본적으로 API, 데이터베이스, Hermes 포트를 `127.0.0.1`에 게시한다. `/admin`이 Docker 브리지에서 작동하도록 이 루프백 게시 HTTP 설정에만 `PRIVACY_ROUTER_ALLOW_INSECURE_ADMIN=1`을 설정한다. `PRIVACY_ROUTER_BIND_HOST`를 루프백에서 변경하면 오버라이드를 `0`으로 설정하고 API보다 전에 HTTPS를 종료한다.

**API 프록시 모드**는 friction-free 프라이버시 보호를 원할 때 최적이다 — 모든 요청이 자동으로 분류되고, 필요 시 마스킹되어 라우팅된다. **MCP 도구 모드**는 agent가 프라이버시 보호를 적용할 시기와 방법에 대해 세부적으로 제어할 때 최적이다 (예: 먼저 분류한 후 마스킹 여부 결정).

## 접속 포인트

| 서비스 | URL | 설명 |
|---------|-----|-------------|
| Landing | http://localhost:8787/ | 포털 (EN/KO) |
| 데모 채팅 | http://localhost:8787/demo | 프라이버시 파이프라인과의 대화형 채팅 |
| Admin | http://localhost:8787/admin | 모델, API 키, 마스킹 텔레메트리 관리 |
| 제품 문서 | http://localhost:8787/docs | 사용자 및 개발자 문서 |
| Hermes 대시보드 | http://localhost:9119 | Hermes Agent 웹 UI |
| API 문서 | http://localhost:8787/api/docs | OpenAPI Swagger UI |

## 클라이언트 API 키 생성

http://localhost:8787/admin을 열고 관리자 비밀번호를 입력한 후 **Create Key**를 사용한다. 반환된 `pr-...` 키는 한 번만 표시된다. 쿠키 및 CSRF API 흐름은 [API Key Management](/docs/api-keys)를 참조한다.

## 대화 맥락

두 OpenAI 호환 엔드포인트는 전체 대화 스냅샷 또는 최신 턴 델타 중 하나를 모두 수용한다:

- `POST /v1/chat/completions`
- `POST /v1/responses`

암호화된 맥락을 유지하기 위해 관련 요청에는 동일한 `X-Chat-ID` 헤더를 전송한다. 전체 스냅샷 재시도는 중복 제거된다; 델타 턴은 추가된다. `instructions` 및 도구 정의와 같은 현재 싱글턴 필드는 이전 값을 대체한다. 동시 요청은 서로를 덮어쓰는 대신 원자적으로 병합된다. 캐시 키는 인증된 API 키 범위에 있으므로, 동일한 클라이언트 대화 ID는 두 테넌트로 조인할 수 없다. 무상태 요청에는 헤더를 생략한다. ID는 1–512 UTF-8 바이트를 포함해야 한다.

Responses 요청은 함수 도구를 수용한다. 지원되지 않는 도구 유형은 공급자 호출 전에 `400`을 반환한다. 프라이버시 메타데이터는 현재 요청의 추출 기록만 포함하며 내부 추출기 추론이나 이전 전용 값은 포함하지 않는다.

### 민감 도구 호출 인자

함수 호출 인자는 기본적으로 스트리밍 및 비스트리밍 응답 모두에서 `SENSITIVE_DATA#<8 hex>` 플레이스홀더를 유지한다. 로컬 모델 라우트에서는 Privacy Router가 완성된 인자 JSON을 엄격히 구문 분석하고 중복 키와 비유한 숫자를 거부하며, 전달 직전에 디코딩된 문자열 값을 검사한다. 이 값에서 민감 평문을 마스킹한다. 하위 스트림 도구가 신뢰되고 요청이 명시적으로 선택할 때만 민감 평문 값을 허용한다:

```json
{
  "tools": [],
  "privacy_router": {
    "allow_sensitive_tool_arguments": true
  }
}
```

이 확장은 `/v1/chat/completions`와 `/v1/responses` 양쪽에 적용된다. JSON boolean `true`만 평문 도구 인자를 활성화한다; 생략된 필드 또는 다른 어떤 유형이라도 마스킹 상태로 유지한다. 선택 등록은 검사가 아닌 릴리스이다: 모든 로컬 도구 호출은 여전히 전달 전에 분석된다. 입력 플레이스홀더에서 유도된 하이드레이션 값과 로컬 모델이 새로 생성한 민감 값 모두를 응답의 모든 함수 호출을 통해 릴리스한다. 이 옵션은 요청 범위이며, 도구별 허용 목록이 아니다. 기본 마스킹은 JSON 구조를 유지한다. 구문 분석, 검사, 또는 마스킹 실패는 응답을 차단한다. 일반 내용 이후에 예상치 못한 도구 호출이 나타날 수 있으므로, 로컬 모델 스트리밍 응답은 완성 시까지 모든 생성 내용을 유지한 후 재…

## 로컬 개발

```bash
python -m pip install -e .
cp .env.example .env
./scripts/start_vllm.sh gemma4
# In another terminal:
privacy-router dev
# → http://localhost:8787
```

## 중지

```bash
docker compose down
```
