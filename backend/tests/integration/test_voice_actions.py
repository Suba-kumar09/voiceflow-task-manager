"""Phase 7: voice commands that change data go through the execution harness.

Rule under test everywhere: NOTHING changes until the same user says "yes" to a pending,
unexpired, unused action; execution then uses the normal services (same checks as buttons).
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.models import (
    AgentPendingAction,
    AgentTrace,
    Notification,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TaskStatusHistory,
)
from app.models.common import utcnow
from tests.integration.test_projects_orchestrator import (
    BACKLOG,
    make_project,
    skilled_world,  # noqa: F401  (fixture)
    started_project,
)

pytestmark = pytest.mark.integration


def say(api, text, path=None):
    resp = api.post("/voice/turns", json={"text": text, "path": path}, key=None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def task(db, key) -> Task:
    db.expire_all()
    return db.execute(select(Task).where(Task.external_key == key)).scalar_one()


def history_count(db, t: Task) -> int:
    return db.execute(
        select(func.count()).select_from(TaskStatusHistory).where(TaskStatusHistory.task_id == t.id)
    ).scalar_one()


# ----------------------------------------------------------------------------- employee


def test_start_needs_yes_then_happens_once(as_user, skilled_world, db):  # noqa: F811
    started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")

    r = say(emp, "I've started the database schema")
    assert r["outcome"] == "confirm" and r["awaiting_confirmation"] is True
    assert r["speech"] == "Mark Database schema as started?"
    assert [c["state"] for c in r["checks"]] == ["ok", "ok"]
    assert task(db, "T1").status is TaskStatus.ASSIGNED  # nothing changed yet

    r = say(emp, "yes")
    assert r["outcome"] == "done" and r["speech"] == "Done. Database schema is in progress."
    assert task(db, "T1").status is TaskStatus.IN_PROGRESS
    before = history_count(db, task(db, "T1"))

    r = say(emp, "yes")  # a second yes must not do anything
    assert r["speech"] == "There is nothing waiting for your confirmation."
    assert history_count(db, task(db, "T1")) == before


def test_completion_asks_for_note_then_notifies_manager(as_user, skilled_world, db):  # noqa: F811
    w = skilled_world
    mgr = as_user("manager_web")
    backlog = [
        {
            "key": "A",
            "title": "Product listing page",
            "priority": "HIGH",
            "required_skills": ["React"],
            "evidence_policy": "NOTE",
            "acceptance_criteria": "Products show price and stock.",
        },
        {
            "key": "B",
            "title": "Wishlist page",
            "priority": "HIGH",
            "required_skills": ["React"],
            "depends_on": ["A"],
        },
    ]
    project, _ = make_project(mgr, w, backlog=backlog)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    mgr.post(f"/projects/{project['id']}/start", key=None)
    emp = as_user("emp_web_2")
    emp.post(f"/tasks/{task(db, 'A').id}/start")

    r = say(emp, "I've completed the product listing page")
    assert r["outcome"] == "clarify" and r["awaiting_confirmation"] is False
    assert "needs a short completion note" in r["speech"]
    assert [c["state"] for c in r["checks"]][-1] == "warn"

    r = say(emp, "All products show price, stock and images.")
    assert r["awaiting_confirmation"] is True
    assert r["speech"] == (
        "Send Product listing page to Manager Web for review with your note: "
        "“All products show price, stock and images”?"
    )
    assert task(db, "A").status is TaskStatus.IN_PROGRESS

    r = say(emp, "yes please")
    assert r["outcome"] == "done"
    assert task(db, "A").status is TaskStatus.PENDING_REVIEW
    note = db.execute(
        select(Notification).where(
            Notification.recipient_user_id == w["manager_web"],
            Notification.kind == "COMPLETION_SUBMITTED",
        )
    ).scalar_one()
    assert "All products show price, stock and images" in note.body

    # Manager approves by voice on the project screen; the dependent task is assigned.
    here = f"/projects/{project['id']}"
    r = say(mgr, "approve it", path=here)
    assert r["speech"] == "Approve Product listing page from Emp Web 2?"
    assert any("All products show price" in c["text"] for c in r["checks"])
    r = say(mgr, "yes")
    assert r["outcome"] == "done"
    assert task(db, "A").status is TaskStatus.COMPLETED
    b = task(db, "B")
    assert b.status is TaskStatus.ASSIGNED and b.assigned_to == w["emp_web_2"]


def test_blocker_asks_for_reason(as_user, skilled_world, db):  # noqa: F811
    started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    say(emp, "start my task")
    say(emp, "yes")
    r = say(emp, "I'm blocked")
    assert r["speech"] == "What is blocking Database schema?"
    r = say(emp, "because the staging database is down")
    assert r["speech"].startswith(
        "Report Database schema as blocked because: the staging database is down?"
    )
    say(emp, "yes")
    assert task(db, "T1").status is TaskStatus.BLOCKED


# ----------------------------------------------------------------------------- safety


def test_no_and_cancel_discard_the_pending_action(as_user, skilled_world, db):  # noqa: F811
    started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    say(emp, "I've started the database schema")
    assert say(emp, "no")["speech"] == "Cancelled. Nothing was changed."
    assert say(emp, "yes")["speech"] == "There is nothing waiting for your confirmation."
    assert task(db, "T1").status is TaskStatus.ASSIGNED


def test_expired_confirmation_does_nothing(as_user, skilled_world, db):  # noqa: F811
    started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    say(emp, "I've started the database schema")
    db.execute(update(AgentPendingAction).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    assert say(emp, "yes")["speech"] == "There is nothing waiting for your confirmation."
    assert task(db, "T1").status is TaskStatus.ASSIGNED


def test_someone_elses_yes_cannot_confirm_my_action(as_user, skilled_world, db):  # noqa: F811
    started_project(as_user, skilled_world)
    say(as_user("emp_web_1"), "I've started the database schema")
    assert (
        say(as_user("emp_web_2"), "yes")["speech"]
        == "There is nothing waiting for your confirmation."
    )
    assert task(db, "T1").status is TaskStatus.ASSIGNED


def test_employees_cannot_use_manager_commands(as_user, skilled_world):  # noqa: F811
    started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    for said in (
        "approve it",
        "assign the ready tasks by priority",
        "start the e-commerce project",
    ):
        r = say(emp, said)
        assert r["outcome"] == "denied" and r["speech"] == "Only a manager can do that.", said


def test_service_rules_still_apply_at_execution_time(as_user, skilled_world, db):  # noqa: F811
    """If the task changes between read-back and "yes", the yes is refused honestly."""
    mgr, _, _ = started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    say(emp, "I've started the database schema")
    # (Unassigning would not do: the orchestrator would correctly hand T1 straight back.)
    mgr.post(f"/tasks/{task(db, 'T1').id}/cancel", json={"reason": "Out of scope"})
    r = say(emp, "yes")
    assert r["outcome"] == "failed"
    assert r["speech"].startswith("I couldn't do that:") and r["speech"].endswith(
        "Nothing was changed."
    )


# ----------------------------------------------------------------------------- manager


def test_assign_ready_reads_the_plan_back_then_assigns(as_user, skilled_world, db):  # noqa: F811
    mgr = as_user("manager_web")
    project, _ = make_project(mgr, skilled_world)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    db.get(Project, project["id"]).status = ProjectStatus.ACTIVE  # active, nothing assigned yet
    db.commit()
    here = f"/projects/{project['id']}"

    r = say(mgr, "A signed the ready tasks by priority", path=here)
    assert r["awaiting_confirmation"] is True
    assert [(x["key"], x["outcome"], x["assignee"]) for x in r["plan"]] == [
        ("T1", "ASSIGN", "Emp Web 1"),
        ("T2", "ASSIGN", "Emp Web 2"),
        ("T5", "NO_QUALIFIED", None),
    ]
    assert r["speech"].endswith("Shall I assign 2 tasks?")
    assert task(db, "T1").status is TaskStatus.UNASSIGNED

    r = say(mgr, "go ahead")
    assert r["outcome"] == "done"
    assert "Database schema to Emp Web 1" in r["speech"]
    assert task(db, "T1").assigned_to == skilled_world["emp_web_1"]


def test_assign_ready_says_honestly_when_nothing_can_be_assigned(as_user, skilled_world):  # noqa: F811
    mgr, project, _ = started_project(as_user, skilled_world)
    r = say(mgr, "assign the ready tasks", path=f"/projects/{project['id']}")
    assert r["awaiting_confirmation"] is False
    assert r["speech"].startswith("Nothing can be assigned right now.")
    assert "iOS build setup" in r["speech"]


def test_manual_assignment_by_name_with_read_back(as_user, skilled_world, db):  # noqa: F811
    mgr, project, _ = started_project(as_user, skilled_world)
    here = f"/projects/{project['id']}"
    r = say(mgr, "assign the order emails to Emp Web 2", path=here)
    assert r["outcome"] == "clarify" and "waiting on T1" in r["speech"]

    r = say(mgr, "assign the iOS build setup to emp web 2", path=here)
    assert r["speech"] == "Assign iOS build setup to Emp Web 2?"
    r = say(mgr, "yes")
    assert r["outcome"] == "failed" and "already has 1 active task" in r["speech"]  # workload rule

    r = say(mgr, "assign the iOS build setup to Ghost", path=here)
    assert r["outcome"] == "clarify" and r["speech"].lower().startswith("i couldn't find ghost")
    assert "Emp Web 1, Emp Web 2" in r["speech"]


def test_start_project_by_voice(as_user, skilled_world, db):  # noqa: F811
    mgr = as_user("manager_web")
    project, _ = make_project(mgr, skilled_world, backlog=BACKLOG, name="HR Portal")
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    r = say(mgr, "start the HR portal project")
    assert r["speech"] == "Start HR Portal? I will assign 2 tasks straight away."
    assert say(mgr, "yes")["speech"].startswith("Started. I assigned")
    db.expire_all()
    assert db.get(Project, project["id"]).status is ProjectStatus.ACTIVE


# ----------------------------------------------------------------------------- traces


def test_every_turn_is_traced_and_only_admins_can_read_traces(as_user, skilled_world, db):  # noqa: F811
    started_project(as_user, skilled_world)
    emp = as_user("emp_web_1")
    say(emp, "I've started the database schema")
    say(emp, "yes")
    traces = db.execute(select(AgentTrace).order_by(AgentTrace.created_at)).scalars().all()
    assert [t.outcome for t in traces[-2:]] == ["confirm", "done"]
    assert traces[-1].tool == "task.start"
    assert [s["step"] for s in traces[-1].steps] == ["understood", "pending_found", "executed"]

    assert as_user("manager_web").get("/voice/traces").status_code == 403
    listed = as_user("admin_a").get("/voice/traces").json()
    assert listed[0]["outcome"] == "done" and listed[0]["user"] == "Emp Web 1"
