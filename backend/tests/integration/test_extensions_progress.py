"""Phase 8: deadline extensions, declining and progress — by API and by voice."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Notification, Task, TaskStatus, TaskStatusHistory
from tests.integration.test_projects_orchestrator import (
    make_project,
    skilled_world,  # noqa: F401  (fixture)
    started_project,
)

pytestmark = pytest.mark.integration

DUE = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)


def say(api, text, path=None):
    resp = api.post("/voice/turns", json={"text": text, "path": path}, key=None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def task(db, key) -> Task:
    db.expire_all()
    return db.execute(select(Task).where(Task.external_key == key)).scalar_one()


def notes(db, user_id, kind):
    db.expire_all()
    return (
        db.execute(
            select(Notification).where(
                Notification.recipient_user_id == user_id, Notification.kind == kind
            )
        )
        .scalars()
        .all()
    )


@pytest.fixture
def dated(as_user, skilled_world, db):  # noqa: F811
    """One HIGH task for Emp Web 1 (Python), due tomorrow, already started."""
    mgr = as_user("manager_web")
    backlog = [
        {
            "key": "C1",
            "title": "Cart API",
            "priority": "HIGH",
            "required_skills": ["Python"],
            "due_at": DUE.isoformat(),
        },
    ]
    project, _ = make_project(mgr, skilled_world, backlog=backlog)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    mgr.post(f"/projects/{project['id']}/start", key=None)
    emp = as_user("emp_web_1")
    emp.post(f"/tasks/{task(db, 'C1').id}/start")
    return mgr, emp, project


# ----------------------------------------------------------------------------- API


def test_extension_request_and_approval_by_api(dated, skilled_world, db, as_user):  # noqa: F811
    mgr, emp, _ = dated
    tid = task(db, "C1").id
    new_due = (DUE + timedelta(days=3)).isoformat()

    r = emp.post(
        f"/tasks/{tid}/extension-requests",
        json={"requested_due_at": new_due, "reason": "Sandbox is down"},
        key=None,
    )
    assert r.status_code == 201, r.text
    req = r.json()
    assert task(db, "C1").due_at == DUE  # unchanged until approved
    assert (
        notes(db, skilled_world["manager_web"], "EXTENSION_REQUESTED")[0].title
        == "Emp Web 1 asks for more time on Cart API"
    )

    shown = emp.get(f"/tasks/{tid}").json()
    assert shown["pending_extension"]["reason"] == "Sandbox is down"

    again = emp.post(
        f"/tasks/{tid}/extension-requests",
        json={"requested_due_at": new_due, "reason": "x"},
        key=None,
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "extension_pending"

    assert emp.post(f"/extension-requests/{req['id']}/approve", key=None).status_code == 403
    assert [x["id"] for x in mgr.get("/extension-requests").json()] == [req["id"]]

    done = mgr.post(
        f"/extension-requests/{req['id']}/approve", json={"note": "OK, unblock it first"}, key=None
    )
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"
    assert task(db, "C1").due_at == DUE + timedelta(days=3)
    history = (
        db.execute(select(TaskStatusHistory.action).where(TaskStatusHistory.task_id == tid))
        .scalars()
        .all()
    )
    assert "extend_deadline" in history
    approved = notes(db, skilled_world["emp_web_1"], "EXTENSION_APPROVED")[0]
    assert "OK, unblock it first" in approved.body
    assert mgr.get("/extension-requests").json() == []


@pytest.mark.parametrize(
    ("days", "code"),
    [(0, "date_invalid"), (-2, "date_invalid")],  # not later than the current due date
)
def test_extension_date_must_be_later(dated, db, days, code):
    _, emp, _ = dated
    tid = task(db, "C1").id
    r = emp.post(
        f"/tasks/{tid}/extension-requests",
        json={"requested_due_at": (DUE + timedelta(days=days)).isoformat(), "reason": "x"},
        key=None,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_only_the_assignee_can_ask_and_deny_keeps_the_date(dated, skilled_world, db, as_user):  # noqa: F811
    mgr, emp, _ = dated
    tid = task(db, "C1").id
    body = {"requested_due_at": (DUE + timedelta(days=2)).isoformat(), "reason": "busy"}
    assert (
        as_user("emp_web_2")
        .post(f"/tasks/{tid}/extension-requests", json=body, key=None)
        .status_code
        == 403
    )
    req = emp.post(f"/tasks/{tid}/extension-requests", json=body, key=None).json()
    assert (
        as_user("manager_mobile")
        .post(f"/extension-requests/{req['id']}/deny", key=None)
        .status_code
        == 403
    )
    assert mgr.post(f"/extension-requests/{req['id']}/deny", key=None).json()["status"] == "DENIED"
    assert task(db, "C1").due_at == DUE
    assert notes(db, skilled_world["emp_web_1"], "EXTENSION_DENIED")


def test_progress_by_api_shows_on_the_task(dated, db):
    _, emp, _ = dated
    tid = task(db, "C1").id
    assert (
        emp.post(
            f"/tasks/{tid}/progress", json={"percent": 40, "note": "Endpoints drafted"}, key=None
        ).status_code
        == 201
    )
    shown = emp.get(f"/tasks/{tid}").json()
    assert (shown["progress_percent"], shown["progress_note"]) == (40, "Endpoints drafted")
    assert emp.post(f"/tasks/{tid}/progress", json={"percent": 140}, key=None).status_code == 422
    assert emp.post(f"/tasks/{tid}/progress", json={}, key=None).status_code == 422


# ----------------------------------------------------------------------------- voice


def test_voice_extension_asks_until_when_and_why_then_waits_for_manager(dated, db):
    mgr, emp, project = dated
    r = say(emp, "I need more time")
    assert r["outcome"] == "clarify" and r["speech"].startswith("Until when do you need Cart API?")

    r = say(emp, "in five days")
    assert r["speech"] == "Why do you need more time for Cart API?"

    r = say(emp, "because the payment sandbox is down")
    assert r["awaiting_confirmation"] is True
    assert r["speech"].startswith("Ask Manager Web to move Cart API to ")
    assert r["speech"].endswith("The deadline changes only if they approve.")
    assert task(db, "C1").due_at == DUE

    r = say(emp, "yes")
    assert r["outcome"] == "done" and "Your deadline stays" in r["speech"]
    assert task(db, "C1").due_at == DUE  # still unchanged

    here = f"/projects/{project['id']}"
    r = say(mgr, "approve the extension", path=here)
    assert r["speech"].startswith("Give Emp Web 1 until ") and r["speech"].endswith("for Cart API?")
    assert any("payment sandbox is down" in c["text"] for c in r["checks"])
    r = say(mgr, "yes")
    assert r["outcome"] == "done" and r["speech"].startswith("Approved. Cart API is now due")
    assert (
        task(db, "C1").due_at.date() == (datetime.now(UTC) + timedelta(days=5)).date()
        or task(db, "C1").due_at > DUE
    )


def test_voice_extension_with_everything_in_one_sentence(dated, db):
    _, emp, _ = dated
    r = say(
        emp,
        "I need more time on the cart API for three more days because the client changed the scope",
    )
    assert r["awaiting_confirmation"] is True
    assert "because: the client changed the scope" in r["speech"]


def test_voice_extension_refuses_a_date_that_is_not_later(dated, db):
    _, emp, _ = dated
    r = say(emp, "I need more time until today")
    assert r["outcome"] == "clarify" and r["awaiting_confirmation"] is False
    assert "Please say a later date." in r["speech"]


def test_voice_deny_extension_with_reason(dated, skilled_world, db):  # noqa: F811
    mgr, emp, _ = dated
    say(emp, "I need two more days because of the sandbox")
    say(emp, "yes")
    r = say(mgr, "deny the extension because the launch date is fixed")
    assert r["speech"] == (
        "Turn down Emp Web 1's request for more time on Cart API, "
        "because: the launch date is fixed?"
    )
    assert say(mgr, "yes")["speech"].startswith("Done. The deadline for Cart API stays the same")
    assert (
        "the launch date is fixed"
        in notes(db, skilled_world["emp_web_1"], "EXTENSION_DENIED")[0].body
    )


def test_voice_progress(dated, db):
    _, emp, _ = dated
    r = say(emp, "I'm about 60 percent done with the cart API")
    assert r["speech"] == "Record Cart API as 60 percent done?"
    assert say(emp, "yes")["speech"] == "Noted: Cart API is 60 percent done."
    assert emp.get(f"/tasks/{task(db, 'C1').id}").json()["progress_percent"] == 60


def test_voice_decline_returns_task_and_is_not_handed_back(as_user, skilled_world, db):  # noqa: F811
    started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    r = say(emp, "I can't do the database schema because I have no database access")
    assert r["speech"].startswith("Decline Database schema because: I have no database access?")
    assert say(emp, "yes")["outcome"] == "done"
    t1 = task(db, "T1")
    assert (
        t1.status is TaskStatus.UNASSIGNED and t1.assigned_to is None
    )  # only Emp Web 1 has Python
    assert notes(db, skilled_world["manager_web"], "TASK_DECLINED")


def test_employees_cannot_decide_extensions_by_voice(dated):
    _, emp, _ = dated
    assert say(emp, "approve the extension")["outcome"] == "denied"
