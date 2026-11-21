"""Phase 9: team reports (screen + voice), reminders worker and notification preferences."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.models import Notification, Task, User
from app.services import reminders
from tests.integration.test_projects_orchestrator import (
    make_project,
    skilled_world,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")


def say(api, text):
    r = api.post("/voice/turns", json={"text": text}, key=None)
    assert r.status_code == 200, r.text
    return r.json()


def kinds(db, user_id) -> list[str]:
    db.expire_all()
    return [
        n.kind.value
        for n in db.execute(
            select(Notification)
            .where(Notification.recipient_user_id == user_id)
            .order_by(Notification.created_at)
        ).scalars()
    ]


@pytest.fixture
def team(as_user, skilled_world, db):  # noqa: F811
    """Emp Web 1 holds an OVERDUE task; Emp Web 2 holds one DUE SOON."""
    now = datetime.now(UTC)
    mgr = as_user("manager_web")
    backlog = [
        {
            "key": "D1",
            "title": "Database schema",
            "priority": "HIGH",
            "required_skills": ["Python"],
            "due_at": (now + timedelta(days=3)).isoformat(),
        },
        {
            "key": "D2",
            "title": "UI mockups",
            "priority": "HIGH",
            "required_skills": ["React"],
            "due_at": (now + timedelta(hours=5)).isoformat(),
        },
    ]
    project, _ = make_project(mgr, skilled_world, backlog=backlog)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    mgr.post(f"/projects/{project['id']}/start", key=None)
    # Make D1 overdue (dates in the past cannot be imported, so move it directly).
    db.execute(
        update(Task).where(Task.external_key == "D1").values(due_at=now - timedelta(hours=2))
    )
    db.commit()
    return mgr, skilled_world


# ----------------------------------------------------------------------------- reports


def test_team_summary_for_managers_only(team, as_user):
    mgr, w = team
    s = mgr.get("/reports/team-summary").json()
    assert s["timezone"] == "Asia/Kolkata" and s["period_label"] == "today"
    assert [t["title"] for t in s["overdue"]] == ["Database schema"]
    assert [t["title"] for t in s["due_soon"]] == ["UI mockups"]
    assert {p["name"]: p["state"] for p in s["people"]} == {
        "Emp Web 1": "at limit",
        "Emp Web 2": "at limit",
    }
    assert s["spoken"].startswith("Today (Asia/Kolkata time), 0 tasks were completed.")
    assert as_user("emp_web_1").get("/reports/team-summary").status_code == 403


def test_completed_today_counts_real_completions(team, as_user, db):
    mgr, _ = team
    emp = as_user("emp_web_2")
    tid = db.execute(select(Task.id).where(Task.external_key == "D2")).scalar_one()
    emp.post(f"/tasks/{tid}/start")
    emp.post(f"/tasks/{tid}/request-completion")
    assert mgr.get("/reports/team-summary").json()["completed"] == 1
    assert mgr.get("/reports/team-summary?period=week").json()["completed"] == 1


def test_voice_reports(team, as_user):
    mgr, _ = team
    assert say(mgr, "Give me today's summary")["speech"].startswith(
        "Today (Asia/Kolkata time), 0 tasks were completed."
    )
    r = say(mgr, "Who has overdue tasks?")
    assert r["speech"] == "1 overdue task. Emp Web 1: Database schema."
    r = say(mgr, "who is overloaded")
    assert (
        r["speech"]
        == "No one is overloaded. At their limit: Emp Web 1 and Emp Web 2. No one has spare capacity."
    )
    assert (
        say(mgr, "how many tasks were completed this week")["speech"]
        == "0 tasks were completed this week (Asia/Kolkata time)."
    )
    assert say(as_user("emp_web_1"), "give me the daily summary")["outcome"] == "denied"


def test_overload_is_reported(team, as_user, db):
    mgr, w = team
    extra = mgr.post(
        "/tasks", json={"team_id": str(w["team_web"]), "title": "Hotfix", "priority": "URGENT"}
    ).json()
    mgr.post(
        f"/tasks/{extra['id']}/assign",
        json={"assignee_id": str(w["emp_web_1"]), "override_capacity": True},
    )
    assert say(mgr, "who is overloaded")["speech"].startswith("Overloaded: Emp Web 1 (2 of 1).")


# ----------------------------------------------------------------------------- reminders


def test_reminders_are_sent_once(team, db):
    _, w = team
    stats = reminders.run(db)
    db.commit()
    assert (stats.overdue, stats.due_soon) == (1, 1)
    assert "OVERDUE" in kinds(db, w["emp_web_1"])
    assert "DUE_SOON" in kinds(db, w["emp_web_2"])
    assert "OVERDUE" in kinds(db, w["manager_web"])  # the manager hears about overdue work too

    before = len(kinds(db, w["emp_web_1"]))
    again = reminders.run(db)
    db.commit()
    assert (again.overdue, again.due_soon) == (0, 0)
    assert len(kinds(db, w["emp_web_1"])) == before


def test_moving_the_deadline_creates_a_new_reminder(team, db):
    _, w = team
    reminders.run(db)
    db.commit()
    db.execute(
        update(Task)
        .where(Task.external_key == "D1")
        .values(due_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    db.commit()
    reminders.run(db)
    db.commit()
    assert kinds(db, w["emp_web_1"]).count("OVERDUE") == 2


def test_quiet_hours_defer_reminders(team, db):
    _, w = team
    local = datetime.now(IST)
    db.execute(
        update(User)
        .where(User.id == w["emp_web_1"])
        .values(
            quiet_start=(local - timedelta(hours=1)).time().replace(microsecond=0),
            quiet_end=(local + timedelta(hours=1)).time().replace(microsecond=0),
        )
    )
    db.commit()
    stats = reminders.run(db)
    db.commit()
    assert "OVERDUE" not in kinds(db, w["emp_web_1"]) and stats.deferred_quiet >= 1
    # Two hours later, quiet hours are over: the reminder arrives.
    reminders.run(db, now=datetime.now(UTC) + timedelta(hours=2))
    db.commit()
    assert "OVERDUE" in kinds(db, w["emp_web_1"])


def test_daily_digest_once_per_day_after_9am(team, db):
    _, w = team
    today = datetime.now(IST).date()
    early = datetime(today.year, today.month, today.day, 8, 0, tzinfo=IST).astimezone(UTC)
    later = datetime(today.year, today.month, today.day, 10, 0, tzinfo=IST).astimezone(UTC)
    assert reminders.run(db, now=early).digests == 0
    db.commit()
    assert reminders.run(db, now=later).digests >= 1  # every team manager gets one
    db.commit()
    assert reminders.run(db, now=later + timedelta(hours=1)).digests == 0
    db.commit()
    digest = db.execute(
        select(Notification).where(
            Notification.recipient_user_id == w["manager_web"], Notification.kind == "DAILY_DIGEST"
        )
    ).scalar_one()
    assert digest.title.startswith("Daily summary for") and "Overdue:" in digest.body


@pytest.mark.parametrize(
    ("start", "end", "now", "quiet"),
    [
        ("22:00", "07:00", "23:30", True),
        ("22:00", "07:00", "06:59", True),
        ("22:00", "07:00", "07:00", False),
        ("13:00", "14:00", "13:30", True),
        ("13:00", "14:00", "12:00", False),
    ],
)
def test_quiet_hours_window_including_midnight(start, end, now, quiet):
    from datetime import time

    u = User(quiet_start=time.fromisoformat(start), quiet_end=time.fromisoformat(end))
    local = datetime.combine(datetime(2026, 11, 21).date(), time.fromisoformat(now), tzinfo=IST)
    assert reminders.in_quiet_hours(u, local) is quiet


# ----------------------------------------------------------------------------- preferences


def test_preferences_round_trip(as_user, skilled_world):  # noqa: F811
    emp = as_user("emp_web_1")
    prefs = emp.get("/users/me/preferences").json()
    assert (
        prefs["voice_announcements"] is True
        and prefs["quiet_start"] is None
        and prefs["timezone"] == "Asia/Kolkata"
    )
    r = emp.client.patch(
        "/api/v1/users/me/preferences",
        json={"voice_announcements": False, "quiet_start": "21:00", "quiet_end": "08:00"},
        headers={"X-CSRF-Token": emp.csrf},
    )
    assert r.status_code == 200
    assert (r.json()["voice_announcements"], r.json()["quiet_start"], r.json()["quiet_end"]) == (
        False,
        "21:00:00",
        "08:00:00",
    )
    bad = emp.client.patch(
        "/api/v1/users/me/preferences",
        json={"quiet_start": "21:00"},
        headers={"X-CSRF-Token": emp.csrf},
    )
    assert bad.status_code == 422
