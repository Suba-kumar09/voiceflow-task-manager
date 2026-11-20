"""Database engine and session factory.

Synchronous SQLAlchemy sessions are used on purpose: psycopg's async mode cannot run on
Windows' default ProactorEventLoop, and FastAPI runs sync dependencies in a threadpool.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    pass


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise DatabaseNotConfiguredError("VOICEFLOW_DATABASE_URL is not set.")
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


def current_migration_revision(engine: Engine) -> str | None:
    """Return the Alembic revision applied to the database, or None if never migrated."""
    with engine.connect() as conn:
        has_table = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
        if not has_table:
            return None
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
