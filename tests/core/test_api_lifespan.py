"""API lifespan security regression tests."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from server.api import app


def test_lifespan_fails_closed_when_database_initialization_fails():
    """A failed privacy migration must prevent the API from starting."""

    async def enter_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    with (
        patch("server.api.main.init_db", side_effect=RuntimeError("migration failed")),
        pytest.raises(RuntimeError, match="migration failed"),
    ):
        asyncio.run(enter_lifespan())
