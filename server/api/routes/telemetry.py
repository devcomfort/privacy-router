"""Administrative telemetry export, retention, and purge routes."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.api import app, require_admin_auth
from telemetry import export_request_telemetry, normalize_utc, purge_request_telemetry

_RAW_TTL_HOURS = 24
_RETENTION_SWEEP_INTERVAL_SECONDS = 60 * 60


class TelemetryPurgeRequest(BaseModel):
    """Explicit scope for destructive telemetry deletion."""

    scope: Literal["expired", "before", "all"] = "expired"
    before: datetime | None = None
    confirm: bool = False


def _csv_export(data: dict[str, object]) -> str:
    output = io.StringIO()
    fieldnames = [
        "id",
        "endpoint",
        "created_at",
        "status",
        "status_code",
        "is_sensitive",
        "records_count",
        "policy_action",
        "route",
        "model_used",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "model_calls",
        "input_redacted",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for request in data.get("requests", []):
        if not isinstance(request, dict):
            continue
        usage = request.get("usage") if isinstance(request.get("usage"), dict) else {}
        writer.writerow(
            {
                **{field: request.get(field) for field in fieldnames if field not in usage},
                **{field: usage.get(field) for field in usage if field in fieldnames},
                "input_redacted": json.dumps(
                    request.get("input_redacted", {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    return output.getvalue()


@app.get("/api/v1/telemetry/retention")
async def telemetry_retention(_admin: str = Depends(require_admin_auth)) -> dict[str, object]:
    """Describe the enforced raw-data retention boundary."""
    return {
        "raw_ttl_hours": _RAW_TTL_HOURS,
        "automatic_purge_interval_seconds": _RETENTION_SWEEP_INTERVAL_SECONDS,
        "export_privacy_level": "redacted",
        "encrypted_payloads_exported": False,
    }


@app.get("/api/v1/telemetry/export")
async def telemetry_export(
    format: Annotated[Literal["json", "csv"], Query()] = "json",
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    _admin: str = Depends(require_admin_auth),
) -> Response:
    """Download redacted request and model-call telemetry."""
    if since is not None and until is not None and normalize_utc(since) > normalize_utc(until):
        raise HTTPException(422, "since must not be later than until")
    data = export_request_telemetry(since=since, until=until)
    filename = f"privacy-router-telemetry-{datetime.now().date().isoformat()}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "csv":
        return Response(_csv_export(data), media_type="text/csv", headers=headers)
    return JSONResponse(data, headers=headers)


@app.post("/api/v1/telemetry/purge")
async def telemetry_purge(
    body: TelemetryPurgeRequest,
    _admin: str = Depends(require_admin_auth),
) -> dict[str, object]:
    """Physically delete a bounded telemetry scope after explicit confirmation."""
    if body.scope == "before" and body.before is None:
        raise HTTPException(422, "before is required when scope is 'before'")
    if body.scope == "all" and not body.confirm:
        raise HTTPException(409, "confirm=true is required when scope is 'all'")
    deleted = purge_request_telemetry(scope=body.scope, before=body.before)
    return {"scope": body.scope, "deleted": deleted}
