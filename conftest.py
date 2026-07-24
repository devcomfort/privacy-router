"""Root conftest.py — adds project root to sys.path for monorepo imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_MASTER_KEY = "LBc6zy54KvMzZxmdaHns_W2NxmhKlZFPT9jKkzQ91bI="


@pytest.fixture(autouse=True)
def _persistent_test_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests deterministic without enabling production key fallback."""
    monkeypatch.setenv("PRIVACY_ROUTER_MASTER_KEY", _TEST_MASTER_KEY)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify tests that require running external services as scenarios."""
    for item in items:
        path = item.path.as_posix()
        if "/tests/scenarios/" in path or "/tests/sanity/" in path:
            item.add_marker(pytest.mark.scenario)


# Add project root so that `agents.*`, `server.*`, `db.*` imports work
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
