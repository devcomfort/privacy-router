"""API lifespan security regression tests."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from server.api import app


def test_lifespan_fails_closed_when_database_initialization_fails(monkeypatch):
    """A failed privacy migration must prevent the API from starting."""
    monkeypatch.setenv(
        "PRIVACY_ROUTER_MASTER_KEY",
        "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI=",
    )
    monkeypatch.setenv("PRIVACY_ROUTER_ADMIN_PASSWORD", "configured-admin-password")

    async def enter_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    with (
        patch("server.api.main.init_db", side_effect=RuntimeError("migration failed")),
        pytest.raises(RuntimeError, match="migration failed"),
    ):
        asyncio.run(enter_lifespan())


def test_lifespan_fails_closed_without_admin_password(monkeypatch):
    """Direct ASGI startup must enforce the serve-mode admin secret."""
    monkeypatch.delenv("PRIVACY_ROUTER_ADMIN_PASSWORD", raising=False)

    async def enter_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    with (
        patch("server.api.main.init_db") as init_db,
        pytest.raises(RuntimeError, match="PRIVACY_ROUTER_ADMIN_PASSWORD"),
    ):
        asyncio.run(enter_lifespan())

    init_db.assert_not_called()
