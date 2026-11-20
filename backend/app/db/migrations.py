"""Helpers to read Alembic's migration head without touching the database."""

from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import BACKEND_DIR


@lru_cache
def head_revision() -> str | None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()
