"""Development endpoints for the HTMX router demonstration."""

from __future__ import annotations

import html
import json
import logging
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from agents import PipelineResult, PrivacyRouter, redact_extraction_records
from agents.extractor import ExtractionRecord
from db import ApiKey, get_session
from server import get_runtime_mode
from server.api import app, create_api_key, require_auth
from server.api.demo_jobs import DemoBatchSnapshot, DemoBatchStore

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

_demo_batches = DemoBatchStore()


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


def _run_router_pipeline(text: str) -> PipelineResult:
    """Analyze one text through the existing Privacy Router pipeline."""
    return PrivacyRouter().process(text)


def _valid_maskable_records(
    text: str,
    records: list[ExtractionRecord],
) -> list[tuple[int, ExtractionRecord]]:
    """Return non-overlapping maskable records with verified offsets."""
    candidates: list[tuple[int, ExtractionRecord]] = []
    for index, record in enumerate(records):
        if record.is_required.value is not False:
            continue
        if not 0 <= record.start < record.end <= len(text):
            continue
        if text[record.start : record.end] != record.span:
            continue
        candidates.append((index, record))

    candidates.sort(key=lambda item: (item[1].start, item[1].end, item[0]))
    retained: list[tuple[int, ExtractionRecord]] = []
    end = 0
    for index, record in candidates:
        if retained and record.start < end:
            continue
        retained.append((index, record))
        end = record.end
    return retained


def _highlighted_input(text: str, records: list[ExtractionRecord]) -> str:
    """Render escaped input text with maskable spans linked to record blocks."""
    parts: list[str] = []
    cursor = 0
    for index, record in _valid_maskable_records(text, records):
        parts.append(html.escape(text[cursor : record.start]))
        record_id = f"record-{index}"
        parts.append(
            f'<mark class="mask-span" data-record-id="{record_id}" tabindex="0" '
            f'aria-describedby="{record_id}">{html.escape(text[record.start : record.end])}</mark>'
        )
        cursor = record.end
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def _record_blocks(records: list[ExtractionRecord]) -> str:
    """Render escaped record metadata and linked maskable blocks."""
    if not records:
        return '<li class="muted">No sensitive spans detected.</li>'

    blocks: list[str] = []
    for index, record in enumerate(records):
        record_id = f"record-{index}"
        required = record.is_required.value
        if required is False:
            classes = "record-block maskable"
            link = f' id="{record_id}" data-record-id="{record_id}" tabindex="0"'
            action = "maskable"
        elif required is True:
            classes = "record-block required"
            link = f' id="{record_id}"'
            action = "local only"
        else:
            classes = "record-block unknown"
            link = f' id="{record_id}"'
            action = "requiredness unknown"
        blocks.append(
            f'<li class="{classes}"{link}>'
            f"<strong>{html.escape(record.category)}</strong>"
            f'<span class="record-action">{action}</span>'
            f"<small>confidence {record.confidence:.0%}</small></li>"
        )
    return "".join(blocks)


def _pipeline_fragment(text: str, pipeline: PipelineResult) -> str:
    """Render a privacy-safe router result as an HTMX fragment."""
    payload = _pipeline_payload(pipeline)
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
  <div class="input-preview" aria-label="Analyzed input">{_highlighted_input(text, pipeline.records)}</div>
  <ul class="record-list">{_record_blocks(pipeline.records)}</ul>
</section>
"""


def _failed_payload() -> dict[str, object]:
    """Return a safe terminal payload for one failed batch case."""
    return {
        "is_sensitive": None,
        "policy_action": "unavailable",
        "route": "blocked",
        "requires_masking": False,
        "record_count": 0,
        "records": [],
        "rationale": _LOCAL_ROUTER_ERROR,
    }


def _run_demo_batch(batch_id: str) -> None:
    """Run every built-in case through one reused router instance."""
    router = PrivacyRouter()
    for index, (_name, text) in enumerate(DEMO_CASES):
        if not _demo_batches.mark_running(batch_id, index):
            return
        try:
            payload = _pipeline_payload(router.process(text))
        except Exception:
            logger.warning("HTMX demo batch case failed: %s", index)
            _demo_batches.finish_case(batch_id, index, "failed", _failed_payload())
        else:
            _demo_batches.finish_case(batch_id, index, "completed", payload)


def _submit_demo_batch(batch_id: str) -> None:
    """Submit the batch worker without blocking the HTTP response."""
    _demo_batches.submit(batch_id, _run_demo_batch)


def _batch_status_label(status: str) -> str:
    """Return a user-facing label for a batch status."""
    return {
        "queued": "queued",
        "running": "running",
        "completed": "completed",
        "failed": "completed with failures",
        "expired": "expired",
    }.get(status, "unavailable")


def _batch_card(case: object) -> str:
    """Render one escaped batch case card."""
    name = html.escape(str(case.name))
    status = str(case.status)
    status_label = _batch_status_label(status)
    payload = html.escape(json.dumps({"text": case.text}, ensure_ascii=False), quote=False)
    result = case.result
    if result is None:
        outcome = '<p class="rationale">Waiting for this case to run.</p>'
    else:
        outcome = (
            f'<p class="rationale">policy {html.escape(str(result["policy_action"]))} · '
            f"route {html.escape(str(result['route']))} · "
            f"records {html.escape(str(result['record_count']))}</p>"
        )
    return f"""
<article class="demo-card status-{html.escape(status)}">
  <div class="result-heading">
    <div><p class="eyebrow">{name}</p><h3>{html.escape(status_label)}</h3></div>
    <span class="route-pill">{html.escape(status)}</span>
  </div>
  <details class="payload-preview"><summary>Payload sent to PrivacyRouter.process()</summary><pre>{payload}</pre></details>
  {outcome}
</article>
"""


def _expired_batch_fragment() -> str:
    """Render a terminal fragment without expired payload data."""
    return '<section id="batch-run" class="batch-results" aria-live="polite"><h2>Batch expired</h2><p class="rationale">This local demo run is no longer available. Start Run all again.</p></section>'


def _run_all_fragment(snapshot: DemoBatchSnapshot | None) -> str:
    """Render batch progress and per-case payloads as an HTMX fragment."""
    if snapshot is None or snapshot.status == "expired":
        return _expired_batch_fragment()

    active = snapshot.status in {"queued", "running"}
    polling = (
        f' hx-get="/api/demo/run-all/{html.escape(snapshot.batch_id)}"'
        ' hx-trigger="every 500ms" hx-target="this" hx-swap="outerHTML"'
        if active
        else ""
    )
    current = html.escape(snapshot.current_name or ("Starting" if active else "Finished"))
    cards = "".join(_batch_card(case) for case in snapshot.cases)
    return f"""
<section id="batch-run" class="batch-results" aria-live="polite"{polling}>
  <div class="batch-heading"><div><p class="eyebrow">Run all</p><h2>Local demo batch</h2></div><span>{snapshot.completed}/{snapshot.total}</span></div>
  <progress max="{snapshot.total}" value="{snapshot.completed}" aria-label="Local demo progress">{snapshot.completed}/{snapshot.total}</progress>
  <p class="batch-current">Current case: <strong>{current}</strong></p>
  <div class="batch-cards">{cards}</div>
</section>
"""


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
        pipeline = _run_router_pipeline(body.text)
    except Exception:
        logger.warning("HTMX demo router request failed")
        if _is_htmx(request):
            return HTMLResponse(_error_fragment(), status_code=503)
        return JSONResponse({"status": "failed", "error": "local_router_unavailable"}, status_code=503)
    if _is_htmx(request):
        return HTMLResponse(_pipeline_fragment(body.text, pipeline))
    return JSONResponse(_pipeline_payload(pipeline))


@app.post("/api/demo/run-all", response_model=None)
def run_all_demos(
    request: Request,
    _auth: str = Depends(require_auth),
) -> HTMLResponse | JSONResponse:
    """Start every built-in local router scenario in a background batch."""
    batch = _demo_batches.create(DEMO_CASES)
    _submit_demo_batch(batch.batch_id)
    if _is_htmx(request):
        return HTMLResponse(_run_all_fragment(_demo_batches.snapshot(batch.batch_id) or batch))
    return JSONResponse(
        {
            "batch_id": batch.batch_id,
            "case_count": batch.total,
            "status": batch.status,
        }
    )


@app.get("/api/demo/run-all/{batch_id}", response_class=HTMLResponse)
def get_demo_batch_status(
    batch_id: str,
    _auth: str = Depends(require_auth),
) -> HTMLResponse:
    """Return one safe HTML polling fragment for a local demo batch."""
    return HTMLResponse(_run_all_fragment(_demo_batches.snapshot(batch_id)))
