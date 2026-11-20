import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db import session as db_session


def _clear_caches() -> None:
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session._session_factory.cache_clear()


@pytest.fixture
def make_client(monkeypatch):
    """Build a TestClient with a specific database URL ('' = not configured)."""

    def _make(database_url: str) -> TestClient:
        monkeypatch.setenv("VOICEFLOW_DATABASE_URL", database_url)
        monkeypatch.setenv("VOICEFLOW_ENVIRONMENT", "test")
        _clear_caches()
        from app.main import create_app

        return TestClient(create_app())

    yield _make
    _clear_caches()
