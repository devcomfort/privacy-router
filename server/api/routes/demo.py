"""Development endpoints for the HTMX router demonstration."""

from __future__ import annotations

import html
import logging
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from agents import PipelineResult, PrivacyRouter, redact_extraction_records
from db import ApiKey, get_session
from server import get_runtime_mode
from server.api import app, create_api_key, require_auth

logger = logging.getLogger(__name__)

_LOCAL_ROUTER_ERROR = "Local router unavailable. Start the configured local model and retry."
DEMO_CASES: tuple[tuple[str, str], ...] = (
    ("safe-greeting", "오늘 날씨가 좋습니다."),
    ("python-help", "파이썬 리스트 컴프리헨션의 사용법을 설명해줘."),
    ("synthetic-contact", "테스트 주소 synthetic@example.invalid를 포함한 안내문을 작성해줘."),
    ("contextual-secret", "사내 프로젝트 오로라의 미공개 일정에 대해 요약해줘."),
    ("direct-sensitive-request", "내 테스트 이메일 주소를 그대로 알려줘."),
    ("research-idea", "새로운 강화학습 알고리즘 설계를 도와줘."),
    ("research-method", "비공개 attention 방법론의 실험 계획을 검토해줘."),
    ("plain-writing", "제품 소개문 초안을 작성해줘."),
)


class DemoRouterRequest(BaseModel):
    """Request body for one local router inspection."""

    text: str = Field(..., min_length=1, max_length=20_000)


def _require_dev_demo() -> None:
    """Allow demo key issuance only while the server runs in dev mode."""
    if get_runtime_mode() != "dev":
        raise HTTPException(status_code=404, detail="Not found")


def _is_htmx(request: Request) -> bool:
    """Return whether the caller expects an HTML fragment from HTMX."""
    return request.headers.get("HX-Request", "").lower() == "true"


async def _parse_demo_request(request: Request) -> DemoRouterRequest:
    """Parse JSON and HTMX URL-encoded request bodies into one model."""
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("application/json"):
        return DemoRouterRequest.model_validate(await request.json())
    values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return DemoRouterRequest.model_validate({key: items[0] for key, items in values.items()})


def _pipeline_payload(pipeline: PipelineResult) -> dict[str, object]:
    """Build a privacy-safe JSON payload from a pipeline result."""
    records = pipeline.records
    sensitivity = pipeline.sensitivity
    judgment = pipeline.judgment
    route = pipeline.route
    return {
        "is_sensitive": bool(sensitivity.is_sensitive),
        "policy_action": judgment.policy_action,
        "route": route.endpoint,
        "requires_masking": bool(route.requires_masking),
        "record_count": len(records),
        "records": redact_extraction_records(records),
        "rationale": judgment.rationale,
    }


def _run_router(text: str) -> dict[str, object]:
    """Analyze one text through the existing Privacy Router pipeline."""
    return _pipeline_payload(PrivacyRouter().process(text))


def _pipeline_fragment(payload: dict[str, object]) -> str:
    """Render one privacy-safe router result as an HTMX fragment."""
    records = payload["records"]
    record_items = "".join(
        f"<li><strong>{html.escape(str(record['category']))}</strong> "
        f"<span>{html.escape(str(record['span']))}</span> "
        f"<small>confidence {float(record['confidence']):.0%}</small></li>"
        for record in records
    )
    if not record_items:
        record_items = "<li class=muted>No sensitive spans detected.</li>"
    return f"""
<section class="result-panel" aria-live="polite">
  <div class="result-heading">
    <div>
      <p class="eyebrow">Router inspection</p>
      <h2>{html.escape(str(payload["policy_action"]))}</h2>
    </div>
    <span class="route-pill">{html.escape(str(payload["route"]))}</span>
  </div>
  <dl class="result-grid">
    <div><dt>Sensitive</dt><dd>{"yes" if payload["is_sensitive"] else "no"}</dd></div>
    <div><dt>Masking</dt><dd>{"required" if payload["requires_masking"] else "not required"}</dd></div>
    <div><dt>Records</dt><dd>{payload["record_count"]}</dd></div>
  </dl>
  <p class="rationale">{html.escape(str(payload["rationale"]))}</p>
  <ul class="record-list">{record_items}</ul>
</section>
"""


def _run_all_fragment(results: list[dict[str, object]]) -> str:
    """Render all local demo results as an HTMX fragment."""
    cards = "".join(
        f"""
<article class="demo-card">
  <div class="result-heading">
    <div><p class="eyebrow">{html.escape(str(result["name"]))}</p>
    <h3>{html.escape(str(result["policy_action"]))}</h3></div>
    <span class="route-pill">{html.escape(str(result["route"]))}</span>
  </div>
  <p class="rationale">{html.escape(str(result["rationale"]))}</p>
</article>
"""
        for result in results
    )
    return f'<section class="batch-results" aria-live="polite"><div class="batch-heading"><h2>All local demos</h2><span>{len(results)} cases</span></div>{cards}</section>'


def _key_fragment(api_key: str, name: str) -> str:
    """Render a newly issued key for browser session storage."""
    escaped_key = html.escape(api_key, quote=True)
    return f"""
<div class="key-issued" data-demo-api-key="{escaped_key}">
  <strong>{html.escape(name)}</strong>
  <code>{escaped_key}</code>
  <span>Stored in this browser session.</span>
</div>
"""


def _error_fragment() -> str:
    """Render a non-sensitive local-backend failure for HTMX."""
    return f'<section class="result-panel" role="alert"><h2>Router unavailable</h2><p class="rationale">{html.escape(_LOCAL_ROUTER_ERROR)}</p></section>'


@app.post("/api/demo/key", response_class=HTMLResponse)
def issue_demo_key(request: Request) -> HTMLResponse:
    """Issue a development client key from the browser demo."""
    _require_dev_demo()
    raw_key, key_hash = create_api_key()
    name = f"htmx-demo-{uuid4().hex[:8]}"
    session = get_session()
    try:
        session.add(ApiKey(name=name, key_hash=key_hash, prefix=raw_key[:11]))
        session.commit()
    finally:
        session.close()
    response = HTMLResponse(_key_fragment(raw_key, name))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/demo/router", response_model=None)
async def inspect_router(
    request: Request,
    _auth: str = Depends(require_auth),
) -> HTMLResponse | JSONResponse:
    """Inspect one request through the FastAPI-exposed router pipeline."""
    body = await _parse_demo_request(request)
    try:
        payload = _run_router(body.text)
    except Exception:
        logger.warning("HTMX demo router request failed")
        if _is_htmx(request):
            return HTMLResponse(_error_fragment(), status_code=503)
        return JSONResponse({"status": "failed", "error": "local_router_unavailable"}, status_code=503)
    if _is_htmx(request):
        return HTMLResponse(_pipeline_fragment(payload))
    return JSONResponse(payload)


@app.post("/api/demo/run-all", response_model=None)
def run_all_demos(
    request: Request,
    _auth: str = Depends(require_auth),
) -> HTMLResponse | JSONResponse:
    """Run every built-in local router scenario with one router instance."""
    router = PrivacyRouter()
    results: list[dict[str, object]] = []
    for name, text in DEMO_CASES:
        try:
            payload = _pipeline_payload(router.process(text))
        except Exception:
            logger.warning("HTMX demo batch case failed: %s", name)
            payload = {
                "status": "failed",
                "is_sensitive": None,
                "policy_action": "unavailable",
                "route": "blocked",
                "requires_masking": False,
                "record_count": 0,
                "records": [],
                "rationale": _LOCAL_ROUTER_ERROR,
            }
        results.append({"name": name, **payload})
    if _is_htmx(request):
        return HTMLResponse(_run_all_fragment(results))
    return JSONResponse({"results": results})
