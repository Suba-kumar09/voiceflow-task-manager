"""Sign-in, sessions, CSRF and audit, against a real PostgreSQL test database."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models import AuditEvent, AuditOutcome, UserSession
from app.models.common import utcnow
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.integration


def test_login_sets_httponly_cookie_and_returns_profile(client, world, db):
    resp = client.post("/api/v1/auth/login", json={"username": "manager_web", "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "manager_web"
    assert body["role"] == "MANAGER"
    assert body["teams"] == [
        {"team_id": str(world["team_web"]), "team_name": "Web", "membership_role": "MANAGER"}
    ]
    assert "password" not in resp.text and "argon2" not in resp.text

    cookie = resp.headers["set-cookie"]
    assert "vf_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api" in cookie
    assert "SameSite=lax" in cookie

    events = db.execute(select(AuditEvent).where(AuditEvent.action == "auth.login")).scalars()
    assert [e.outcome for e in events] == [AuditOutcome.SUCCESS]


def test_session_token_is_stored_only_as_hash(client, world, db):
    client.post("/api/v1/auth/login", json={"username": "emp_web_1", "password": PASSWORD})
    raw_token = client.cookies.get("vf_session")
    stored = db.execute(select(UserSession.token_hash)).scalar_one()
    assert raw_token and stored != raw_token and len(stored) == 64


def test_username_is_case_insensitive(client, world):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "  Manager_Web ", "password": PASSWORD}
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("manager_web", "wrong-password-123"),
        ("no_such_user", PASSWORD),
        ("inactive_emp", PASSWORD),
    ],
)
def test_bad_logins_get_one_generic_message(client, world, db, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Invalid username or password."
    assert "set-cookie" not in resp.headers
    outcomes = db.execute(select(AuditEvent.outcome)).scalars().all()
    assert outcomes == [AuditOutcome.FAILURE]


def test_repeated_failures_are_throttled_even_with_correct_password(client, world):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "emp_web_1", "password": "nope-nope-1"})
    resp = client.post("/api/v1/auth/login", json={"username": "emp_web_1", "password": PASSWORD})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "too_many_requests"


def test_me_requires_a_session(client, world):
    resp = client.get("/api/v1/users/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_me_returns_current_user(client, world):
    csrf = login(client, "emp_web_1")
    me = client.get("/api/v1/users/me").json()
    assert me["username"] == "emp_web_1"
    assert me["csrf_token"] == csrf
    assert me["organization"]["name"] == "Org A"


def test_logout_requires_csrf_then_revokes_session(client, world, db):
    csrf = login(client, "emp_web_1")

    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert client.get("/api/v1/users/me").status_code == 200  # still signed in

    resp = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 204
    assert db.execute(select(UserSession.revoked_at)).scalar_one() is not None
    assert client.get("/api/v1/users/me").status_code == 401


def test_stolen_cookie_is_useless_after_logout(client, world, make_client, migrated_db_url):
    csrf = login(client, "emp_web_1")
    stolen = client.cookies.get("vf_session")
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})

    attacker = make_client(migrated_db_url)
    attacker.cookies.set("vf_session", stolen, path="/api")
    assert attacker.get("/api/v1/users/me").status_code == 401


def test_expired_session_is_rejected(client, world, db):
    login(client, "emp_web_1")
    db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    assert client.get("/api/v1/users/me").status_code == 401


def test_idle_session_is_rejected(client, world, db):
    login(client, "emp_web_1")
    db.execute(update(UserSession).values(last_seen_at=utcnow() - timedelta(hours=3)))
    db.commit()
    assert client.get("/api/v1/users/me").status_code == 401


def test_deactivated_user_loses_access_immediately(client, world, db):
    from app.models import User

    login(client, "emp_web_1")
    db.execute(update(User).where(User.username == "emp_web_1").values(is_active=False))
    db.commit()
    assert client.get("/api/v1/users/me").status_code == 401
