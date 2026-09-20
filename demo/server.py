"""Local, in-memory Privacy Router workbench. No text generation on startup."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PEER_BASE = "http://10.42.0.2:8090/v1"
PEER_ROOT = "google/gemma-4-26B-A4B-it"
PEER_ALIAS = "openkb-compiler"
REGISTERED_MODEL = "openai/google/gemma-4-26b-local"
MODEL = {"name": "Gemma 4 26B A4B", "backend": "IntentAnalyzer → Extractor"}
TOKEN_FILE = "/home/donghyeon/gist-rule-dataset/.data/openkb/peer-vllm-api-key"
MAX_BODY = 128 * 1024
MAX_CHARACTERS = 16000
SESSION_TTL = 1800
MAX_SESSIONS = 64
COOKIE_NAME = "privacy_demo_session"

# Prevent library telemetry, remote pricing downloads, and sensitive diagnostic logs.
# This is process-local configuration, not a replacement of any library function.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["LITELLM_TELEMETRY"] = "False"
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["PRIVACY_ROUTER_TRUSTED_LOCAL_MODEL_HOSTS"] = "10.42.0.2"
logging.disable(logging.CRITICAL)
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402
import instructor  # noqa: E402
import litellm  # noqa: E402
from openai import OpenAI  # noqa: E402

from agents.annotator import IntentAnalyzer  # noqa: E402
from agents.extractor import Extractor, ExtractorCore  # noqa: E402
from cachier import Cachier  # noqa: E402
from contracts import IntentAnnotation  # noqa: E402
from policy import PolicyRecommendation, RecommendedAction  # noqa: E402
from router import PrivacyRouter, Router, RouterEvent, RoutingError  # noqa: E402

litellm.telemetry = False
litellm.suppress_debug_info = True
litellm.turn_off_message_logging = True

RECOMMENDED_ACTIONS = [
    {
        "value": "mask_then_share",
        "label": "마스킹 후 공개 가능",
        "description": "마스킹 후에도 작업에 필요한 정보가 유효하므로 마스킹한 텍스트의 외부 전달을 권장합니다.",
    },
    {
        "value": "keep_local",
        "label": "마스킹 시 의미 소실 · 로컬 처리",
        "description": "작업에 필요한 값이 마스킹으로 사라지므로 외부 전달 대신 로컬 처리를 권장합니다.",
    },
    {
        "value": "share_original",
        "label": "공개 가능 · 원문 전달",
        "description": "완료된 검사에서 기밀 유출 요인이 발견되지 않아 원문 전달을 권장합니다. 검출 누락 가능성은 남습니다.",
    },
]
ACTIONS = {item["value"]: item for item in RECOMMENDED_ACTIONS}
RECOMMENDATION_REASONS = {
    "no_evidence": "검사 근거가 없어 권장 행동을 보류합니다. 외부 전달은 차단됩니다.",
    "incomplete_analysis": "검사가 불완전하여 권장 행동을 보류합니다. 외부 전달은 차단됩니다.",
    "confidentiality_unassessed": "기밀 여부를 판정하지 못한 항목이 있습니다. 각 항목의 이유를 확인하세요. 권장 행동을 보류하고 외부 전달을 차단합니다.",
    "masking_impact_unknown": "모든 민감정보를 가려도 작업을 완료할 수 있는지 확정하지 못했습니다. 아래 판단 근거를 확인하세요. 외부 전달은 차단됩니다.",
    "masking_loses_meaning": ACTIONS["keep_local"]["description"],
    "masking_preserves_task": ACTIONS["mask_then_share"]["description"],
    "no_sensitive_data": ACTIONS["share_original"]["description"],
}


def recommendation_view(recommendation: PolicyRecommendation) -> dict:
    action = recommendation.action
    return {
        "action": str(action) if action is not None else None,
        "reason": recommendation.reason,
        "label": ACTIONS[action]["label"] if action is not None else "권장 행동 보류",
        "explanation": RECOMMENDATION_REASONS.get(
            recommendation.reason, "권장 행동을 확정하지 못했습니다. 외부 전달은 차단됩니다."
        ),
    }


class DemoError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def unavailable() -> DemoError:
    return DemoError(
        503,
        "analysis_unavailable",
        "로컬 피어 검사를 완료하지 못했습니다. 연결 및 모델 상태를 확인한 뒤 다시 시도하세요.",
    )


def error_payload(error: DemoError) -> dict:
    return {
        "error": {"code": error.code, "message": error.message},
        "recommendation": recommendation_view(PolicyRecommendation(None, "incomplete_analysis")),
        "sharing": {"permitted": False, "text": None},
    }


@dataclass
class Measurements:
    calls: int = 0
    model_ms: float = 0.0
    stage_calls: dict[str, int] = field(default_factory=lambda: {"annotation": 0, "extraction": 0})
    stage_ms: dict[str, float] = field(default_factory=lambda: {"annotation": 0.0, "extraction": 0.0})


class PeerTransport(httpx.BaseTransport):
    """Count actual inference HTTP attempts, including unsuccessful attempts."""

    def __init__(self, measurements: Measurements):
        self.measurements = measurements
        self.transport = httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if (url.scheme, url.host, url.port) != ("http", "10.42.0.2", 8090):
            raise unavailable()
        inference = request.method == "POST" and url.path == "/v1/chat/completions"
        if not inference and not (request.method == "GET" and url.path == "/v1/models"):
            raise unavailable()
        start = time.perf_counter()
        if inference:
            self.measurements.calls += 1
        try:
            response = self.transport.handle_request(request)
            # Consume within the timing boundary; non-streaming completions only.
            response.read()
            return response
        finally:
            if inference:
                self.measurements.model_ms += (time.perf_counter() - start) * 1000

    def close(self) -> None:
        self.transport.close()


def peer_client(measurements: Measurements) -> httpx.Client:
    key = Path(os.environ.get("PRIVACY_DEMO_API_KEY_FILE", TOKEN_FILE)).read_text().strip()
    if not key or len(key) > 8192 or "\n" in key or "\r" in key:
        raise unavailable()
    return httpx.Client(
        transport=PeerTransport(measurements),
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx.Timeout(60.0, connect=5.0),
        follow_redirects=False,
        trust_env=False,
    )


def verify_peer(client: httpx.Client) -> None:
    response = client.get(f"{PEER_BASE}/models", timeout=5.0)
    response.raise_for_status()
    models = response.json().get("data", [])
    if not any(item.get("id") == PEER_ALIAS and item.get("root") == PEER_ROOT for item in models):
        raise unavailable()


def peer_status() -> dict:
    try:
        with peer_client(Measurements()) as client:
            verify_peer(client)
        return {**MODEL, "available": True, "detail": "peer device / GB10 · 모델 레지스트리 확인 완료 (추론하지 않음)"}
    except Exception:
        return {**MODEL, "available": False, "detail": "피어 연결 또는 모델 확인 실패 · 대체 모델을 사용하지 않습니다."}


@contextmanager
def peer_inference(measurements: Measurements, lock: threading.Lock):
    """Keep both annotation and extraction within one authenticated local run."""
    if not lock.acquire(blocking=False):
        raise DemoError(429, "model_busy", "피어에서 다른 검사가 진행 중입니다. 완료 후 다시 시도하세요.")
    try:
        with peer_client(measurements) as http_client:
            verify_peer(http_client)
            sdk = OpenAI(
                api_key=http_client.headers["Authorization"].removeprefix("Bearer "),
                base_url=PEER_BASE,
                http_client=http_client,
                max_retries=0,
                timeout=60.0,
            )

            def completion(*args, **kwargs):
                # Count Instructor attempts at the HTTP boundary, without
                # additional retries hidden in either transport library.
                return litellm.completion(*args, **kwargs, client=sdk, num_retries=0, max_retries=0)

            client = instructor.from_litellm(completion, mode=instructor.Mode.JSON)

            def peer_call(messages, response_model, *, model, api_base, max_tokens, component):
                if model != REGISTERED_MODEL or api_base != PEER_BASE or component not in {"annotator", "extractor"}:
                    raise unavailable()
                stage = "annotation" if component == "annotator" else "extraction"
                started = time.perf_counter()
                calls_before = measurements.calls
                try:
                    return client.chat.completions.create(
                        model=f"openai/{PEER_ALIAS}",
                        messages=messages,
                        response_model=response_model,
                        api_base=PEER_BASE,
                        api_key=sdk.api_key,
                        max_tokens=max_tokens,
                        temperature=0,
                        seed=42,
                        timeout=60.0,
                        max_retries=2,
                        caching=False,
                        **{"no-log": True},
                    )
                finally:
                    measurements.stage_calls[stage] += measurements.calls - calls_before
                    measurements.stage_ms[stage] += (time.perf_counter() - started) * 1000

            yield peer_call
    finally:
        lock.release()


def load_benchmark() -> dict:
    result_path = ROOT / "spikes/critic-ablation/gemma4-peer-results.json"
    source_path = ROOT / "docs/experiments/detector-bench/20260904-000126.results.json"
    result = json.loads(result_path.read_text())
    source_bytes = source_path.read_bytes()
    if sha256(source_bytes).hexdigest() != result["dataset_sha256"]:
        raise ValueError("Historical benchmark source mismatch")
    source = {row["case"]["id"]: row["case"] for row in json.loads(source_bytes)["rows"]}
    cases = {}
    complete = []
    for row in result["rows"]:
        case = source[row["case_id"]]
        entry = cases.setdefault(
            case["id"],
            {
                "id": case["id"],
                "title": case["name"],
                "text": case["text"],
                "expected_spans": case["expected"],
                "runs": [],
            },
        )
        if row["status"] == "complete":
            complete.append(row)
            entry["runs"].append(
                {
                    "repeat": row["repeat"],
                    "status": "complete",
                    "exact_hits": row["base"]["exact_hits"],
                    "contained_hits": row["base"]["contained_hits"],
                    "expected_count": row["expected"],
                    "latency_ms": row["base_ms"],
                    "exact_omissions": row["expected"] - row["base"]["exact_hits"],
                    "contained_omissions": row["expected"] - row["base"]["contained_hits"],
                }
            )
        else:
            entry["runs"].append(
                {
                    "repeat": row["repeat"],
                    "status": "failed",
                    "expected_count": row["expected"],
                    "exact_hits": None,
                    "contained_hits": None,
                    "latency_ms": None,
                }
            )
    return {
        "model": MODEL["name"],
        "implementation": "ExtractorCore 단일 패스 · 저장된 비교 실험의 기본 추출 결과",
        "scope": f"합성 예제 {result['cases_per_repeat']}개 × {result['repeats']}회 반복 (독립 표본 아님)",
        "completed_pairs": len(complete),
        "expected_spans": sum(row["expected"] for row in complete),
        "exact_hits": sum(row["base"]["exact_hits"] for row in complete),
        "contained_hits": sum(row["base"]["contained_hits"] for row in complete),
        "mean_ms": round(sum(row["base_ms"] for row in complete) / len(complete), 3) if complete else None,
        "failures": len(result["rows"]) - len(complete),
        "cases": list(cases.values()),
        "measured_at": result["completed_at_utc"],
        "sources": [str(result_path.relative_to(ROOT)), str(source_path.relative_to(ROOT))],
        "caveat": "기대 구간 포함률은 전체 정밀도·재현율이 아닙니다. 누락 수는 보존되지만 개별 누락 값은 해당 측정에 저장되지 않아 특정할 수 없습니다. 과거 LLMExtractor 어댑터 평가와 직접 비교할 수 없습니다.",
    }


@dataclass
class Session:
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    namespace: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = field(default_factory=time.monotonic)
    cache: Cachier = field(default_factory=lambda: Cachier(max_entries=32))
    lock: threading.Lock = field(default_factory=threading.Lock)


class Application:
    def __init__(self, *, router_factory: Callable[..., Router] = PrivacyRouter):
        self.sessions: dict[str, Session] = {}
        self.sessions_lock = threading.RLock()
        self.inference_lock = threading.Lock()
        self.router_factory = router_factory
        self.examples = json.loads((ROOT / "demo/examples.json").read_text())
        self.benchmark = load_benchmark()
        self.fingerprint = sha256(
            json.dumps(
                {
                    "model": REGISTERED_MODEL,
                    "root": PEER_ROOT,
                    "alias": PEER_ALIAS,
                    "endpoint": PEER_BASE,
                    "temperature": 0,
                    "seed": 42,
                    "max_tokens": 2048,
                    "instructor_attempts": 2,
                    "framing": "role-length-v1",
                    "prompt": sha256((ROOT / "src/agents/extractor/extract.prompt").read_bytes()).hexdigest(),
                    "validation": sha256((ROOT / "src/agents/extractor/extractor_core.py").read_bytes()).hexdigest(),
                    "intent_prompt": sha256((ROOT / "src/agents/intent.prompt").read_bytes()).hexdigest(),
                    "annotator": sha256((ROOT / "src/agents/annotator.py").read_bytes()).hexdigest(),
                    "intent_contract": sha256((ROOT / "src/contracts/annotation.py").read_bytes()).hexdigest(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def expire(self):
        now = time.monotonic()
        with self.sessions_lock:
            for key, session in list(self.sessions.items()):
                if now - session.touched > SESSION_TTL and session.lock.acquire(blocking=False):
                    try:
                        session.cache.clear()
                        del self.sessions[key]
                    finally:
                        session.lock.release()

    def session(self, cookie: str | None, *, create: bool) -> tuple[str, Session, bool]:
        self.expire()
        with self.sessions_lock:
            session = self.sessions.get(cookie)
            if session is not None:
                session.touched = time.monotonic()
                return cookie, session, False
            if not create:
                raise DemoError(403, "session_expired", "세션이 만료되었습니다. 페이지를 새로고침하세요.")
            if len(self.sessions) >= MAX_SESSIONS:
                raise DemoError(429, "sessions_full", "활성 세션이 많습니다. 잠시 후 다시 시도하세요.")
            cookie = secrets.token_urlsafe(32)
            session = Session()
            self.sessions[cookie] = session
            return cookie, session, True

    def analyze(
        self,
        session: Session,
        messages: list[dict],
        *,
        intent: IntentAnnotation | None = None,
        on_status: Callable[[RouterEvent], None] | None = None,
    ) -> dict:
        started = time.perf_counter()
        source = session_source(messages)
        validate_intent_source(source, intent)
        measurements = Measurements()
        with ExitStack() as resources:
            peer_call = None
            transport_error = None

            def call_structured(*args, **kwargs):
                nonlocal peer_call, transport_error
                if peer_call is None:
                    try:
                        peer_call = resources.enter_context(peer_inference(measurements, self.inference_lock))
                    except DemoError as exc:
                        transport_error = exc
                        raise
                return peer_call(*args, **kwargs)

            router = self.router_factory(
                annotator=IntentAnalyzer(
                    model=REGISTERED_MODEL, api_base=PEER_BASE, max_tokens=2048, call_structured=call_structured
                ),
                extractor=Extractor(
                    core=ExtractorCore(
                        model=REGISTERED_MODEL, api_base=PEER_BASE, max_tokens=2048, call_structured=call_structured
                    )
                ),
                cache=session.cache,
                detector_fingerprint=self.fingerprint,
            )
            try:
                result = router.route(
                    source,
                    namespace=session.namespace,
                    history=[frame_message(item) for item in messages[:-1]],
                    intent=intent,
                    on_status=on_status,
                )
            except RoutingError:
                raise transport_error or unavailable() from None
        action = result.recommendation.action
        permitted = action in {RecommendedAction.SHARE_ORIGINAL, RecommendedAction.MASK_THEN_SHARE}
        return {
            "status": "complete",
            "source_text": source,
            "records": [
                {
                    "start": record.start,
                    "end": record.end,
                    "category": record.category,
                    "confidence": record.confidence,
                    "confidentiality": record.confidentiality.model_dump(mode="json"),
                    "necessity": record.necessity.model_dump(mode="json"),
                }
                for record in result.records
            ],
            "intent": result.intent.model_dump(mode="json"),
            "intent_source": result.intent_source,
            "session": {"message_count": len(messages)},
            "recommendation": recommendation_view(result.recommendation),
            "masking_assessment": {
                "preserves_task": result.masking_preserves_task,
                "reason": result.masking_reason,
            },
            "masking": {
                "text": result.masking.masked_text,
                "hydrated_text": result.hydration.hydrated_text,
                "round_trip_ok": True,
            },
            "sharing": {
                "permitted": permitted,
                "text": (source if action == RecommendedAction.SHARE_ORIGINAL else result.masking.masked_text)
                if permitted
                else None,
                "reason": "권장 행동에 따른 로컬 미리보기입니다. 외부로 전송하지 않으며 자동 검출은 완전성을 보장하지 않습니다.",
            },
            "cache": {
                "hit": result.cache_hit,
                "entries": len(session.cache),
                "note": "세션·원문·전체 이전 문맥·의도 어노테이션 해시·검사기 지문 일치 및 span 해시 검증. 서버 캐시는 해시·위치·판정만 저장하며 의도 원문과 모델 이유를 보관하지 않습니다.",
            },
            "timings": {
                "total_ms": round((time.perf_counter() - started) * 1000, 3),
                "model_ms": round(measurements.model_ms, 3),
                "annotation_ms": round(measurements.stage_ms["annotation"], 3),
                "extraction_ms": round(measurements.stage_ms["extraction"], 3),
            },
            "model_calls": measurements.calls,
            "stage_calls": measurements.stage_calls,
            "model": MODEL,
        }


def frame_message(message: dict) -> str:
    return f"[{message['role']} · {len(message['content'])} characters]\n{message['content']}"


def session_source(messages: list[dict]) -> str:
    if len(messages) == 1:
        return messages[0]["content"]
    return "\n\n".join(frame_message(message) for message in messages)


def validate_messages(body: object) -> list[dict]:
    if not isinstance(body, dict) or "messages" not in body or set(body) - {"messages", "intent"}:
        raise DemoError(
            422, "invalid_input", "messages 배열과 선택적인 intent 어노테이션만 포함한 JSON 객체가 필요합니다."
        )
    messages = body["messages"]
    if not isinstance(messages, list) or not 1 <= len(messages) <= 12:
        raise DemoError(422, "invalid_messages", "1~12개의 메시지를 입력하세요.")
    total = 0
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or not isinstance(message["role"], str)
            or message["role"] not in {"user", "assistant", "system"}
            or not isinstance(message["content"], str)
            or not message["content"].strip()
        ):
            raise DemoError(422, "invalid_message", "각 메시지에는 허용된 role과 비어 있지 않은 content가 필요합니다.")
        text = message["content"]
        if any(0xD800 <= ord(char) <= 0xDFFF or ord(char) == 0 for char in text):
            raise DemoError(422, "invalid_unicode", "유효한 유니코드 텍스트를 입력하세요.")
        total += len(text)
    if total > MAX_CHARACTERS:
        raise DemoError(413, "input_too_large", "전체 입력은 16,000자 이하여야 합니다.")
    return messages


def validate_intent(value: object) -> IntentAnnotation:
    try:
        return IntentAnnotation.model_validate(value)
    except (TypeError, ValueError):
        raise DemoError(422, "invalid_intent", "의도 어노테이션 형식이 유효하지 않습니다.") from None


def validate_intent_source(source: str, intent: IntentAnnotation | None) -> None:
    if intent is not None and not intent.matches_source(source):
        raise DemoError(
            422, "intent_source_mismatch", "의도 어노테이션의 원문이 현재 입력과 다릅니다. 새로 분석하세요."
        )


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app: Application, allowed_hosts: dict[str, str]):
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, Handler)

    def service_actions(self):
        self.app.expire()

    def handle_error(self, request, client_address):
        # Never let socketserver emit exception tracebacks containing inputs.
        return


class Handler(BaseHTTPRequestHandler):
    server_version = "PrivacyDemo"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        return

    def send_error(self, code, message=None, explain=None):
        self.fail(DemoError(code, "http_error", "요청을 처리할 수 없습니다."))

    def send_response_headers(self, status: int, *, content_type: str, length: int | None = None, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        else:
            self.close_connection = True
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if status == 429:
            self.send_header("Retry-After", "3")
        if cookie:
            secure = (
                "; Secure" if self.server.allowed_hosts.get(self.headers.get("Host", "").lower()) == "https" else ""
            )
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}{secure}",
            )
        self.end_headers()

    def respond(self, status: int, payload, *, content_type="application/json; charset=utf-8", cookie=None):
        data = (
            payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        )
        self.send_response_headers(status, content_type=content_type, length=len(data), cookie=cookie)
        if self.command != "HEAD":
            self.wfile.write(data)

    def fail(self, error: DemoError):
        self.respond(error.status, error_payload(error))

    def stream_line(self, payload: dict):
        self.wfile.write(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() + b"\n")
        self.wfile.flush()

    def stream_analysis(self, session: Session, messages: list[dict], intent: IntentAnnotation | None):
        self.send_response_headers(200, content_type="application/x-ndjson; charset=utf-8")
        self.wfile.flush()
        try:
            response = self.server.app.analyze(
                session,
                messages,
                intent=intent,
                on_status=lambda event: self.stream_line({"type": "status", "event": asdict(event)}),
            )
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except DemoError as exc:
            self.stream_line({"type": "error", **error_payload(exc)})
        except Exception:
            self.stream_line({"type": "error", **error_payload(unavailable())})
        else:
            self.stream_line({"type": "result", "result": response})

    def validate_host(self) -> str:
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in self.server.allowed_hosts:
            raise DemoError(403, "invalid_host", "허용되지 않은 호스트입니다.")
        if self.headers.get("Sec-Fetch-Site") not in {None, "same-origin", "none"}:
            raise DemoError(403, "cross_origin", "동일 출처에서만 접근할 수 있습니다.")
        return hosts[0].lower()

    def cookie(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        if len(raw) > 4096:
            return None
        try:
            cookies = SimpleCookie()
            cookies.load(raw)
            return cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else None
        except CookieError:
            return None

    def do_GET(self):
        try:
            self.validate_host()
            if self.path == "/api/bootstrap" and self.command != "HEAD":
                cookie, session, _ = self.server.app.session(self.cookie(), create=True)
                self.respond(
                    200,
                    {
                        "csrf_token": session.csrf,
                        "model": peer_status(),
                        "examples": self.server.app.examples,
                        "recommended_actions": RECOMMENDED_ACTIONS,
                        "benchmark": self.server.app.benchmark,
                    },
                    cookie=cookie,
                )
                return
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/index.html": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            }
            if self.path not in assets:
                raise DemoError(404, "not_found", "요청한 경로가 없습니다.")
            filename, mime = assets[self.path]
            self.respond(200, (ROOT / "demo/static" / filename).read_bytes(), content_type=mime)
        except DemoError as exc:
            self.fail(exc)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self.fail(unavailable())

    def do_HEAD(self):
        self.do_GET()

    def read_json(self):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            raise DemoError(400, "invalid_body", "Content-Length가 지정된 JSON 본문이 필요합니다.")
        if not lengths[0].isascii() or len(lengths[0]) > len(str(MAX_BODY)):
            raise DemoError(413, "body_too_large", "요청 본문이 너무 큽니다.")
        length = int(lengths[0])
        if not 0 < length <= MAX_BODY:
            raise DemoError(413, "body_too_large", "요청 본문이 너무 크거나 비어 있습니다.")
        if self.headers.get_content_type() != "application/json":
            raise DemoError(400, "invalid_content_type", "application/json 형식이 필요합니다.")
        try:
            raw = self.rfile.read(length)
        except TimeoutError:
            raise DemoError(400, "body_timeout", "요청 본문 수신 시간이 초과되었습니다.") from None
        if len(raw) != length:
            raise DemoError(400, "incomplete_body", "요청 본문이 불완전합니다.")
        try:

            def unique_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate key")
                    result[key] = value
                return result

            return json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=unique_keys,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid constant")),
            )
        except (UnicodeError, ValueError, RecursionError):
            raise DemoError(400, "invalid_json", "유효한 UTF-8 JSON을 입력하세요.") from None

    def do_POST(self):
        streaming = False
        try:
            self.validate_host()
            origins = self.headers.get_all("Origin", [])
            allowed_origins = {f"{scheme}://{host}" for host, scheme in self.server.allowed_hosts.items()}
            if len(origins) != 1 or origins[0] not in allowed_origins:
                raise DemoError(403, "invalid_origin", "동일 출처 요청만 허용됩니다.")
            _, session, _ = self.server.app.session(self.cookie(), create=False)
            tokens = self.headers.get_all("X-CSRF-Token", [])
            if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], session.csrf):
                raise DemoError(403, "invalid_csrf", "세션 보안 토큰이 유효하지 않습니다. 페이지를 새로고침하세요.")
            if self.path not in {"/api/analyze", "/api/reset"}:
                raise DemoError(404, "not_found", "요청한 경로가 없습니다.")
            body = self.read_json()
            if not session.lock.acquire(blocking=False):
                raise DemoError(429, "session_busy", "현재 세션에서 검사가 진행 중입니다.")
            try:
                if self.path == "/api/reset":
                    if body != {}:
                        raise DemoError(422, "invalid_reset", "초기화 본문은 빈 객체여야 합니다.")
                    session.cache.clear()
                    session.namespace = secrets.token_urlsafe(32)
                    response = {"cleared": True}
                else:
                    messages = validate_messages(body)
                    intent = validate_intent(body["intent"]) if "intent" in body else None
                    validate_intent_source(session_source(messages), intent)
                    if "application/x-ndjson" in self.headers.get("Accept", ""):
                        streaming = True
                        self.stream_analysis(session, messages, intent)
                        return
                    response = self.server.app.analyze(session, messages, intent=intent)
            finally:
                session.touched = time.monotonic()
                session.lock.release()
            self.respond(200, response)
        except DemoError as exc:
            if not streaming:
                self.fail(exc)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            if not streaming:
                self.fail(unavailable())


def main():
    parser = argparse.ArgumentParser(description="Local Privacy Router interactive workbench")
    parser.add_argument(
        "--host", action="append", help="Listen address; repeat for multiple interfaces (default: 127.0.0.1)"
    )
    parser.add_argument("--port", type=int, default=os.environ.get("PASEO_PORT", "8765"))
    parser.add_argument("--allow-network", action="store_true", help="Explicitly allow a non-loopback bind")
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Additional HTTPS proxy Host authority, e.g. demo.example.com",
    )
    args = parser.parse_args()
    try:
        hosts = list(
            dict.fromkeys(
                str(ipaddress.ip_address("127.0.0.1" if host == "localhost" else host))
                for host in (args.host or ["127.0.0.1"])
            )
        )
    except ValueError:
        parser.error("--host must be localhost or an IP address")
    if any(not ipaddress.ip_address(host).is_loopback for host in hosts) and not args.allow_network:
        parser.error("non-loopback binds require --allow-network")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    allowed = {f"localhost:{args.port}": "http", f"127.0.0.1:{args.port}": "http", f"[::1]:{args.port}": "http"}
    for host in hosts:
        if host not in {"0.0.0.0", "::"}:
            authority = f"[{host}]:{args.port}" if ":" in host else f"{host}:{args.port}"
            allowed[authority] = "http"
    for authority in args.allowed_host:
        try:
            parsed = urlsplit(f"https://{authority}")
            valid = bool(parsed.hostname) and parsed.port != 0
        except ValueError:
            valid = False
        if (
            not valid
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in authority)
        ):
            parser.error("--allowed-host must be a bare HTTPS host authority")
        allowed[authority.lower()] = "https"
    paseo_url = os.environ.get("PASEO_URL")
    if paseo_url:
        try:
            parsed = urlsplit(paseo_url)
            valid = bool(parsed.hostname) and parsed.port != 0
        except ValueError:
            valid = False
        if (
            not valid
            or parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in paseo_url)
        ):
            parser.error("PASEO_URL must be an explicit HTTP(S) origin")
        allowed[parsed.netloc.lower()] = parsed.scheme
    with ExitStack() as stack:
        try:
            app = Application()
            servers = [stack.enter_context(DemoServer((host, args.port), app, allowed)) for host in hosts]
        except Exception:
            print(
                "Privacy demo could not initialize; check local assets, source measurements, and bind settings.",
                file=sys.stderr,
            )
            return 1
        workers = []
        try:
            for server in servers[1:]:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                workers.append((server, worker))
            addresses = ", ".join(f"[{host}]:{args.port}" if ":" in host else f"{host}:{args.port}" for host in hosts)
            print(f"Privacy Router demo listening on {addresses}; inputs are not persisted.", flush=True)
            servers[0].serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            for server, _ in workers:
                server.shutdown()
            for _, worker in workers:
                worker.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
