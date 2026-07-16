"""Security-boundary regression tests for management APIs and public metadata."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from agents import ExtractionRecord, redact_extraction_records
from server.api import app, require_admin_auth, require_auth


def _route_dependencies(path: str, method: str) -> set[Callable[..., object]]:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return {dependency.call for dependency in route.dependant.dependencies}
    raise AssertionError(f"Route not found: {method} {path}")


@pytest.mark.asyncio
async def test_admin_auth_is_fail_closed_and_uses_constant_time_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRIVACY_ROUTER_ADMIN_KEY", raising=False)
    with pytest.raises(HTTPException) as missing:
        await require_admin_auth("anything")
    assert missing.value.status_code == 503

    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_KEY", "expected-admin-secret")
    with pytest.raises(HTTPException) as absent:
        await require_admin_auth(None)
    assert absent.value.status_code == 401

    with pytest.raises(HTTPException) as wrong:
        await require_admin_auth("wrong-admin-secret")
    assert wrong.value.status_code == 403

    assert await require_admin_auth("expected-admin-secret") == "admin"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/settings"),
        ("POST", "/api/settings"),
        ("GET", "/api/providers"),
        ("POST", "/api/providers/{provider_id}/key"),
        ("DELETE", "/api/providers/{provider_id}/key"),
        ("GET", "/api/profiles"),
        ("POST", "/api/profiles/activate"),
        ("GET", "/api/v1/keys"),
        ("POST", "/api/v1/keys"),
        ("POST", "/api/v1/keys/bulk-delete"),
        ("POST", "/api/v1/keys/bulk-toggle"),
        ("PATCH", "/api/v1/keys/{key_id}"),
        ("DELETE", "/api/v1/keys/{key_id}"),
        ("POST", "/api/v1/keys/{key_id}/renew"),
        ("GET", "/api/v1/models"),
        ("POST", "/api/v1/models"),
        ("DELETE", "/api/v1/models/{model_record_id}"),
        ("GET", "/api/v1/dashboard-data"),
    ],
)
def test_management_routes_require_admin_auth(method: str, path: str) -> None:
    dependencies = _route_dependencies(path, method)
    assert require_admin_auth in dependencies
    assert require_auth not in dependencies


def test_public_extraction_records_never_echo_raw_span_or_reasoning() -> None:
    secret = "SOURCE_SENTINEL_VALUE"
    reasoning = "Internal analysis containing SOURCE_SENTINEL_VALUE"
    records = [
        ExtractionRecord(
            category="INTERNAL_PROJECT_NAME",
            span=secret,
            confidence=0.93,
            start=8,
            end=8 + len(secret),
            is_essential=True,
            reasoning=reasoning,
        )
    ]

    public = redact_extraction_records(records)

    assert public == [
        {
            "index": 0,
            "category": "INTERNAL_PROJECT_NAME",
            "span": "<redacted>",
            "confidence": 0.93,
            "is_essential": True,
        }
    ]
    assert secret not in repr(public)
    assert reasoning not in repr(public)
