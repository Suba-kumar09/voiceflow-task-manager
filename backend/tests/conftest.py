import os
import uuid
from dataclasses import dataclass, field

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.auth import passwords
from app.core.config import BACKEND_DIR, Settings, get_settings
from app.db import session as db_session

# Hashing uses fast test parameters only when VOICEFLOW_ENVIRONMENT=test.
os.environ["VOICEFLOW_ENVIRONMENT"] = "test"

TEST_DB_URL = Settings().test_database_url
PASSWORD = "correct-horse-battery-staple"

# Tables wiped between integration tests (children first is not needed with CASCADE).
_TABLES = "audit_events, user_sessions, team_memberships, users, teams, organizations"


def _clear_caches() -> None:
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session._session_factory.cache_clear()
    passwords.clear_caches()


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


# ---------------------------------------------------------------- integration fixtures


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"db_url={url}"]})()
    return cfg


@pytest.fixture(scope="session")
def migrated_db_url() -> str:
    if not TEST_DB_URL:
        pytest.skip("VOICEFLOW_TEST_DATABASE_URL not set")
    engine = create_engine(TEST_DB_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()
    command.upgrade(alembic_config(TEST_DB_URL), "head")
    return TEST_DB_URL


@pytest.fixture
def db(migrated_db_url):
    engine = create_engine(migrated_db_url)
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        engine.dispose()


@pytest.fixture
def client(make_client, migrated_db_url) -> TestClient:
    return make_client(migrated_db_url)


@dataclass
class World:
    """Two organizations. Org A: Web team and Mobile team. Org B: one team."""

    ids: dict[str, uuid.UUID] = field(default_factory=dict)

    def __getitem__(self, key: str) -> uuid.UUID:
        return self.ids[key]


@pytest.fixture
def world(db) -> World:
    from app.models import (
        MembershipRole,
        Organization,
        Team,
        TeamMembership,
        User,
        UserRole,
    )

    w = World()
    pw_hash = passwords.hash_password(PASSWORD)

    def org(key: str, name: str) -> Organization:
        o = Organization(name=name, slug=key, timezone="Asia/Kolkata", is_demo=False)
        db.add(o)
        db.flush()
        w.ids[key] = o.id
        return o

    def team(key: str, o: Organization, name: str) -> Team:
        t = Team(organization_id=o.id, name=name)
        db.add(t)
        db.flush()
        w.ids[key] = t.id
        return t

    def user(key: str, o: Organization, role: UserRole, active: bool = True) -> User:
        u = User(
            organization_id=o.id,
            username=key,
            display_name=key.replace("_", " ").title(),
            password_hash=pw_hash,
            role=role,
            is_active=active,
        )
        db.add(u)
        db.flush()
        w.ids[key] = u.id
        return u

    def member(t: Team, u: User, r: MembershipRole) -> None:
        db.add(TeamMembership(team_id=t.id, user_id=u.id, membership_role=r))

    a = org("org_a", "Org A")
    web = team("team_web", a, "Web")
    mobile = team("team_mobile", a, "Mobile")
    user("admin_a", a, UserRole.ADMIN)
    member(web, user("manager_web", a, UserRole.MANAGER), MembershipRole.MANAGER)
    member(mobile, user("manager_mobile", a, UserRole.MANAGER), MembershipRole.MANAGER)
    member(web, user("emp_web_1", a, UserRole.EMPLOYEE), MembershipRole.MEMBER)
    member(web, user("emp_web_2", a, UserRole.EMPLOYEE), MembershipRole.MEMBER)
    member(mobile, user("emp_mobile", a, UserRole.EMPLOYEE), MembershipRole.MEMBER)
    member(web, user("inactive_emp", a, UserRole.EMPLOYEE, active=False), MembershipRole.MEMBER)

    b = org("org_b", "Org B")
    team_b = team("team_b", b, "Ops")
    member(team_b, user("manager_b", b, UserRole.MANAGER), MembershipRole.MANAGER)
    member(team_b, user("emp_b", b, UserRole.EMPLOYEE), MembershipRole.MEMBER)

    db.commit()
    return w


def login(client: TestClient, username: str, password: str = PASSWORD) -> str:
    """Sign in on this client (cookie is stored on it); return the CSRF token."""
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]
