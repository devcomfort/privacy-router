"""Shared fixtures for scenario tests.

Provides:
- BASE_URL: server base URL
- auth_headers(): creates a test API key and returns auth headers
"""

from __future__ import annotations

import pytest

BASE_URL = "http://localhost:8787"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Server base URL."""
    return BASE_URL


@pytest.fixture(scope="session")
def auth_headers() -> dict[str, str]:
    """Create a test API key and return auth headers.

    The key is created directly in PostgreSQL (same DB as Docker container).
    """
    import db.models  # noqa: F401
    from db.session import init_db, get_session
    from db.models import ApiKey, Provider
    from server.api.auth import create_api_key

    init_db()

    raw, hashed = create_api_key()
    session = get_session()
    try:
        provider = session.get(Provider, "test-provider")
        if not provider:
            provider = Provider(
                id="test-provider", name="test", provider_type="openrouter", is_active=True
            )
            session.add(provider)
            session.commit()
        key = ApiKey(
            provider_id="test-provider",
            name="test-key",
            key_hash=hashed,
            prefix=raw[:8],
            is_active=True,
        )
        session.add(key)
        session.commit()
    finally:
        session.close()

    return {"Authorization": f"Bearer {raw}"}
