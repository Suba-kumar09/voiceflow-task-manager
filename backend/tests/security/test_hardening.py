"""Phase 10 security checks: headers, upload size, rate limits, docs, and isolation of the
newer endpoints (reports, traces, extension requests) across teams and organisations."""

import io
import wave

import pytest

from app.auth.throttle import LoginThrottle
from app.core.config import Settings

pytestmark = pytest.mark.integration


def wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buf.getvalue()


def test_security_headers_on_api_responses(client):
    r = client.get("/api/v1/health")
    h = r.headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["Cache-Control"] == "no-store"
    assert "Strict-Transport-Security" not in h  # only in production (needs HTTPS)


def test_errors_also_carry_headers(client):
    r = client.get("/api/v1/users/me")  # not signed in
    assert r.status_code == 401
    assert r.headers["X-Frame-Options"] == "DENY"


def test_api_docs_are_off_in_production():
    assert Settings(environment="production", database_url="x").docs_enabled is False
    assert Settings(environment="development", database_url="x").docs_enabled is True


def test_oversized_recording_is_refused_without_reading_it_all(as_user, world):
    emp = as_user("emp_web_1")
    r = emp.client.post(
        "/api/v1/voice/turns/audio",
        content=wav(25),  # limit is 20 s
        headers={"Content-Type": "audio/wav", "X-CSRF-Token": emp.csrf},
    )
    assert r.status_code == 413


def test_voice_commands_are_rate_limited_per_person(as_user, world):
    emp = as_user("emp_web_1")
    emp.client.app.state.voice_limiter = LoginThrottle(max_failures=3, window_seconds=60)
    codes = [
        emp.post("/voice/turns", json={"text": "what is my task"}, key=None).status_code
        for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]
    other = as_user("emp_web_2")  # a different person (separate app instance) is unaffected
    assert other.post("/voice/turns", json={"text": "what is my task"}, key=None).status_code == 200


# ----------------------------------------------------------------------------- isolation


def test_team_reports_never_cross_teams_or_organisations(as_user, world):
    web = as_user("manager_web")
    t = web.post(
        "/tasks",
        json={
            "team_id": str(world["team_web"]),
            "title": "Web only secret task",
            "priority": "LOW",
        },
    )
    assert t.status_code in (200, 201), t.text
    web.post(f"/tasks/{t.json()['id']}/assign", json={"assignee_id": str(world["emp_web_1"])})

    def names(api):
        return {p["name"] for p in api.get("/reports/team-summary").json()["people"]}

    assert "Emp Web 1" in names(web)
    assert "Emp Web 1" not in names(as_user("manager_mobile"))  # same org, other team
    assert "Emp Web 1" not in names(as_user("manager_b"))  # other organisation
    assert as_user("emp_web_1").get("/reports/team-summary").status_code == 403


def test_traces_are_admin_only_and_per_organisation(as_user, world):
    as_user("emp_web_1").post("/voice/turns", json={"text": "what is my task"}, key=None)
    assert as_user("manager_web").get("/voice/traces").status_code == 403
    assert as_user("emp_web_1").get("/voice/traces").status_code == 403
    assert len(as_user("admin_a").get("/voice/traces").json()) >= 1
    assert as_user("manager_b").get("/voice/traces").status_code == 403


def test_extension_requests_are_scoped(as_user, world):
    from datetime import UTC, datetime, timedelta

    web = as_user("manager_web")
    due = datetime.now(UTC) + timedelta(days=1)
    t = web.post(
        "/tasks",
        json={
            "team_id": str(world["team_web"]),
            "title": "Private task",
            "priority": "LOW",
            "due_at": due.isoformat(),
        },
    ).json()
    web.post(f"/tasks/{t['id']}/assign", json={"assignee_id": str(world["emp_web_1"])})
    emp1 = as_user("emp_web_1")
    emp1.post(f"/tasks/{t['id']}/start")
    r = emp1.post(
        f"/tasks/{t['id']}/extension-requests",
        json={
            "requested_due_at": (due + timedelta(days=2)).isoformat(),
            "reason": "Personal reason",
        },
    )
    assert r.status_code in (200, 201), r.text

    assert len(web.get("/extension-requests").json()) == 1  # their manager
    assert len(emp1.get("/extension-requests").json()) == 1  # the person who asked
    assert as_user("emp_web_2").get("/extension-requests").json() == []  # a teammate
    assert as_user("manager_mobile").get("/extension-requests").json() == []  # another team
    assert as_user("manager_b").get("/extension-requests").json() == []  # another organisation


def test_voice_cannot_report_on_another_team(as_user, world):
    r = as_user("emp_mobile").post("/voice/turns", json={"text": "who has overdue tasks"}, key=None)
    assert r.json()["outcome"] == "denied"
