"""Runs Alembic against a real PostgreSQL test database, then checks /ready.

Skipped unless VOICEFLOW_TEST_DATABASE_URL is set (in the environment or backend/.env).
The test database is reset to an empty schema; never point this at real data.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import BACKEND_DIR, Settings

pytestmark = pytest.mark.integration

TEST_DB_URL = Settings().test_database_url


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"db_url={url}"]})()
    return cfg


@pytest.mark.skipif(not TEST_DB_URL, reason="VOICEFLOW_TEST_DATABASE_URL not set")
def test_migrate_up_down_up_then_ready(make_client):
    engine = create_engine(TEST_DB_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()

    client = make_client(TEST_DB_URL)
    pending = client.get("/api/v1/ready")
    assert pending.status_code == 503
    assert pending.json()["migrations"] == "pending"

    cfg = _alembic_config(TEST_DB_URL)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    resp = make_client(TEST_DB_URL).get("/api/v1/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert {k: body[k] for k in ("status", "database", "migrations")} == {
        "status": "ready",
        "database": "ok",
        "migrations": "up_to_date",
    }
    assert body["speech"] in {"ok", "model_missing", "not_installed", "disabled"}
