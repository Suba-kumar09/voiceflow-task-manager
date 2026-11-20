"""Phase 4 end to end: backlog -> approve -> start -> parallel auto-assignment ->
completion notifies the manager -> next tasks assigned automatically."""

import threading

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Notification, Skill, Task, TaskAssignment, TaskStatus
from app.services import projects as project_service
from app.services.orchestrator import service as orchestrator
from tests.integration.test_task_concurrency import principal_for

pytestmark = pytest.mark.integration

BACKLOG = [
    {"key": "T1", "title": "Database schema", "priority": "HIGH", "required_skills": ["Python"]},
    {"key": "T2", "title": "UI mockups", "priority": "HIGH", "required_skills": ["React"]},
    {
        "key": "T3",
        "title": "Catalog API",
        "priority": "HIGH",
        "depends_on": ["T1"],
        "required_skills": ["Python"],
    },
    {
        "key": "T4",
        "title": "Product page",
        "priority": "MEDIUM",
        "depends_on": ["T2", "T3"],
        "required_skills": ["React"],
    },
    {"key": "T5", "title": "iOS build setup", "priority": "MEDIUM", "required_skills": ["iOS"]},
    {
        "key": "T6",
        "title": "Order emails",
        "priority": "LOW",
        "depends_on": ["T1"],
        "required_skills": ["Python"],
    },
]


@pytest.fixture
def skilled_world(db, world):
    """emp_web_1 = Python developer, emp_web_2 = React/testing. Nobody has iOS."""
    admin = principal_for(db, world["admin_a"])
    project_service.set_user_skills(db, admin, world["emp_web_1"], ["Python", "APIs"])
    project_service.set_user_skills(db, admin, world["emp_web_2"], ["React", "Testing"])
    db.add(Skill(organization_id=world["org_a"], name="iOS"))
    db.commit()
    return world


def make_project(mgr, world, backlog=BACKLOG, name="E-Commerce"):
    project = mgr.post(
        "/projects", json={"team_id": str(world["team_web"]), "name": name}, key=None
    ).json()
    resp = mgr.post(f"/projects/{project['id']}/backlog/import", json={"tasks": backlog})
    return project, resp


def tasks_by_key(db, project_id):
    db.expire_all()
    rows = db.execute(select(Task).where(Task.project_id == project_id)).scalars()
    return {t.external_key: t for t in rows}


def notes_for(db, user_id):
    db.expire_all()
    return (
        db.execute(
            select(Notification)
            .where(Notification.recipient_user_id == user_id)
            .order_by(Notification.created_at)
        )
        .scalars()
        .all()
    )


def started_project(as_user, skilled_world):
    mgr = as_user("manager_web")
    project, resp = make_project(mgr, skilled_world)
    assert resp.status_code == 201, resp.text
    assert mgr.post(f"/projects/{project['id']}/approve-backlog", key=None).status_code == 200
    start = mgr.post(f"/projects/{project['id']}/start", key=None)
    assert start.status_code == 200, start.text
    return mgr, project, start.json()


# ----------------------------------------------------------------------------- backlog


def test_validate_reports_warnings_and_saves_nothing(as_user, skilled_world, db):
    mgr = as_user("manager_web")
    project = mgr.post(
        "/projects", json={"team_id": str(skilled_world["team_web"]), "name": "P"}, key=None
    ).json()
    report = mgr.post(
        f"/projects/{project['id']}/backlog/validate", json={"tasks": BACKLOG}, key=None
    ).json()
    assert report["ok"] is True
    assert report["can_start_immediately"] == ["T1", "T2", "T5"]
    assert any("iOS" in w for w in report["warnings"])
    assert tasks_by_key(db, project["id"]) == {}


def test_invalid_backlog_is_refused_with_every_reason(as_user, skilled_world, db):
    mgr = as_user("manager_web")
    bad = [
        {"key": "T1", "title": "A", "priority": "HIGH", "depends_on": ["T2"]},
        {"key": "T2", "title": "B", "priority": "HIGH", "depends_on": ["T1"]},
    ]
    project, resp = make_project(mgr, skilled_world, backlog=bad)
    assert resp.status_code == 422
    assert resp.json()["errors"][0].startswith("Dependency loop:")
    assert tasks_by_key(db, project["id"]) == {}

    resp = mgr.post(
        f"/projects/{project['id']}/backlog/import",
        json={
            "tasks": [{"key": "T1", "title": "A", "priority": None, "required_skills": ["Cobol"]}]
        },
    )
    errors = " ".join(resp.json()["errors"])
    assert "priority None" in errors and "Cobol" in errors


def test_only_managers_of_the_team_manage_projects(as_user, skilled_world):
    team = str(skilled_world["team_web"])
    assert (
        as_user("emp_web_1")
        .post("/projects", json={"team_id": team, "name": "X"}, key=None)
        .status_code
        == 403
    )
    assert (
        as_user("manager_mobile")
        .post("/projects", json={"team_id": team, "name": "X"}, key=None)
        .status_code
        == 403
    )
    assert (
        as_user("manager_b")
        .post("/projects", json={"team_id": team, "name": "X"}, key=None)
        .status_code
        == 404
    )


def test_cannot_start_before_backlog_is_approved(as_user, skilled_world):
    mgr = as_user("manager_web")
    project, _ = make_project(mgr, skilled_world)
    resp = mgr.post(f"/projects/{project['id']}/start", key=None)
    assert resp.status_code == 409


# ----------------------------------------------------------------------------- orchestration


def test_start_assigns_independent_ready_tasks_in_parallel(as_user, skilled_world, db):
    w = skilled_world
    mgr, project, result = started_project(as_user, w)

    assert {(a["key"], a["assignee_name"]) for a in result["assigned"]} == {
        ("T1", "Emp Web 1"),
        ("T2", "Emp Web 2"),
    }
    assert [d["key"] for d in result["needs_decision"]] == ["T5"]
    assert result["needs_decision"][0]["reason"] == "No one on the team has ios."

    t = tasks_by_key(db, project["id"])
    assert t["T1"].assigned_to == w["emp_web_1"] and t["T2"].assigned_to == w["emp_web_2"]
    for key in ("T3", "T4", "T6"):  # waiting on dependencies: never assigned early
        assert t[key].status is TaskStatus.UNASSIGNED

    progress = mgr.get(f"/projects/{project['id']}/progress").json()
    assert progress["in_progress"] == 2
    assert progress["waiting_on_dependencies"] == 3
    assert progress["ready_to_assign"] == 0
    assert [d["key"] for d in progress["needs_decision"]] == ["T5"]

    kinds = [n.kind.value for n in notes_for(db, w["manager_web"])]
    assert "PROJECT_SUMMARY" in kinds and "NEEDS_DECISION" in kinds
    assert [n.title for n in notes_for(db, w["emp_web_1"])] == ["New task: Database schema"]

    rows = db.execute(select(TaskAssignment)).scalars().all()
    assert {r.source.value for r in rows} == {"ORCHESTRATOR"}


def test_completion_notifies_manager_and_assigns_next_task(as_user, skilled_world, db):
    w = skilled_world
    mgr, project, _ = started_project(as_user, w)
    t = tasks_by_key(db, project["id"])
    emp1 = as_user("emp_web_1")

    emp1.post(f"/tasks/{t['T1'].id}/start")
    done = emp1.post(f"/tasks/{t['T1'].id}/request-completion")
    assert done.json()["status"] == "COMPLETED"

    manager_titles = [n.title for n in notes_for(db, w["manager_web"])]
    assert "Emp Web 1 completed Database schema" in manager_titles

    t = tasks_by_key(db, project["id"])
    # T3 (HIGH) and T6 (LOW) both became ready; Emp Web 1 can hold one: T3 wins on priority.
    assert t["T3"].status is TaskStatus.ASSIGNED and t["T3"].assigned_to == w["emp_web_1"]
    assert t["T6"].status is TaskStatus.UNASSIGNED
    assert "New task: Catalog API" in [n.title for n in notes_for(db, w["emp_web_1"])]

    # T4 still waits for T3 even though Emp Web 2 (React) finishes T2.
    emp2 = as_user("emp_web_2")
    emp2.post(f"/tasks/{t['T2'].id}/start")
    emp2.post(f"/tasks/{t['T2'].id}/request-completion")
    assert tasks_by_key(db, project["id"])["T4"].status is TaskStatus.UNASSIGNED

    # Re-running evaluation changes nothing (idempotent).
    again = mgr.post(f"/projects/{project['id']}/assign-ready").json()
    assert again["assigned"] == []
    assert [x["key"] for x in again["waiting_for_capacity"]] == ["T6"]


def test_review_flow_note_reaches_manager_and_approval_unlocks_work(as_user, skilled_world, db):
    w = skilled_world
    backlog = [
        {
            "key": "A",
            "title": "Product listing page",
            "priority": "HIGH",
            "required_skills": ["React"],
            "evidence_policy": "NOTE",
        },
        {
            "key": "B",
            "title": "Wishlist page",
            "priority": "HIGH",
            "required_skills": ["React"],
            "depends_on": ["A"],
        },
    ]
    mgr = as_user("manager_web")
    project, resp = make_project(mgr, w, backlog=backlog)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    mgr.post(f"/projects/{project['id']}/start", key=None)
    t = tasks_by_key(db, project["id"])
    emp2 = as_user("emp_web_2")
    emp2.post(f"/tasks/{t['A'].id}/start")
    sent = emp2.post(
        f"/tasks/{t['A'].id}/request-completion",
        json={"note": "All products show price, stock and images."},
    )
    assert sent.json()["status"] == "PENDING_REVIEW"

    note = [n for n in notes_for(db, w["manager_web"]) if n.kind.value == "COMPLETION_SUBMITTED"][0]
    assert note.title == "Emp Web 2 completed Product listing page"
    assert "All products show price, stock and images." in note.body
    assert tasks_by_key(db, project["id"])["B"].status is TaskStatus.UNASSIGNED  # not yet approved

    assert mgr.post(f"/tasks/{t['A'].id}/approve-completion").json()["status"] == "COMPLETED"
    assert (
        "approved Product listing page"
        in notes_for(db, w["emp_web_2"])[-2].title + notes_for(db, w["emp_web_2"])[-1].title
    )
    b = tasks_by_key(db, project["id"])["B"]
    assert b.status is TaskStatus.ASSIGNED and b.assigned_to == w["emp_web_2"]


def test_manual_assignment_cannot_skip_dependencies(as_user, skilled_world, db):
    mgr, project, _ = started_project(as_user, skilled_world)
    t3 = tasks_by_key(db, project["id"])["T3"]
    resp = mgr.post(f"/tasks/{t3.id}/assign", json={"assignee_id": str(skilled_world["emp_web_2"])})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "dependencies_unmet"
    assert "T1" in resp.json()["error"]["message"]


def test_declined_task_is_not_handed_back_to_the_same_person(as_user, skilled_world, db):
    w = skilled_world
    mgr, project, _ = started_project(as_user, w)
    t1 = tasks_by_key(db, project["id"])["T1"]
    resp = as_user("emp_web_1").post(
        f"/tasks/{t1.id}/decline", json={"reason": "No database access"}
    )
    assert resp.status_code == 200
    t1 = tasks_by_key(db, project["id"])["T1"]
    assert t1.status is TaskStatus.UNASSIGNED and t1.assigned_to is None
    plan = mgr.get(f"/projects/{project['id']}/assignment-plan").json()
    t1_plan = [i for i in plan if i["key"] == "T1"][0]
    assert t1_plan["outcome"] == "NO_QUALIFIED"
    assert "declined" in t1_plan["reason"]
    assert "Emp Web 1 declined Database schema" in [
        n.title for n in notes_for(db, w["manager_web"])
    ]


def test_assignment_plan_is_a_dry_run(as_user, skilled_world, db):
    mgr = as_user("manager_web")
    project, _ = make_project(mgr, skilled_world)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    plan = mgr.get(f"/projects/{project['id']}/assignment-plan").json()
    assert [(i["key"], i["outcome"]) for i in plan] == [
        ("T1", "ASSIGN"),
        ("T2", "ASSIGN"),
        ("T5", "NO_QUALIFIED"),
    ]
    assert all(t.status is TaskStatus.UNASSIGNED for t in tasks_by_key(db, project["id"]).values())
    assert as_user("emp_web_1").get(f"/projects/{project['id']}/assignment-plan").status_code == 403


def test_two_evaluations_at_once_never_double_assign(as_user, skilled_world, db, migrated_db_url):
    mgr = as_user("manager_web")
    project, _ = make_project(mgr, skilled_world)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    # Activate without evaluating, so the two racing evaluations do the work.
    from app.models import Project, ProjectStatus

    db.get(Project, project["id"]).status = ProjectStatus.ACTIVE
    db.commit()

    engine = create_engine(migrated_db_url, pool_size=4)
    barrier = threading.Barrier(2)
    results = []

    def run():
        with Session(engine) as s:
            barrier.wait()
            r = orchestrator.evaluate(s, project["id"])
            s.commit()
            results.append(len(r.assigned))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    engine.dispose()

    assert sorted(results) == [0, 2]
    db.expire_all()
    open_rows = (
        db.execute(select(TaskAssignment).where(TaskAssignment.ended_at.is_(None))).scalars().all()
    )
    assert len(open_rows) == 2


def test_person_freed_by_other_work_gets_the_waiting_project_task(as_user, skilled_world, db):
    w = skilled_world
    mgr = as_user("manager_web")
    side = mgr.post(
        "/tasks", json={"team_id": str(w["team_web"]), "title": "Hotfix", "priority": "URGENT"}
    ).json()
    mgr.post(f"/tasks/{side['id']}/assign", json={"assignee_id": str(w["emp_web_1"])})

    project, _ = make_project(mgr, w)
    mgr.post(f"/projects/{project['id']}/approve-backlog", key=None)
    result = mgr.post(f"/projects/{project['id']}/start", key=None).json()
    assert [x["key"] for x in result["waiting_for_capacity"]] == ["T1"]  # Emp Web 1 is busy

    emp1 = as_user("emp_web_1")
    emp1.post(f"/tasks/{side['id']}/start")
    emp1.post(f"/tasks/{side['id']}/request-completion")  # not part of the project

    t1 = tasks_by_key(db, project["id"])["T1"]
    assert t1.status is TaskStatus.ASSIGNED and t1.assigned_to == w["emp_web_1"]


def test_project_task_list_shows_dependencies_and_skills(as_user, skilled_world):
    mgr, project, _ = started_project(as_user, skilled_world)
    items = mgr.get(f"/tasks?project_id={project['id']}&limit=200").json()["items"]
    by_key = {t["external_key"]: t for t in items}
    assert set(by_key) == {"T1", "T2", "T3", "T4", "T5", "T6"}
    assert by_key["T4"]["depends_on"] == ["T2", "T3"]
    assert by_key["T4"]["required_skills"] == ["React"]
    # An employee filtering by project still only sees their own tasks.
    mine = as_user("emp_web_1").get(f"/tasks?project_id={project['id']}").json()["items"]
    assert [t["external_key"] for t in mine] == ["T1"]


def test_project_team_view_is_for_managers_only(as_user, skilled_world):
    mgr, project, _ = started_project(as_user, skilled_world)
    team = {m["display_name"]: m for m in mgr.get(f"/projects/{project['id']}/team").json()}
    emp1 = team["Emp Web 1"]
    assert emp1["skills"] == ["APIs", "Python"]
    assert emp1["active_tasks"] == 1 and emp1["wip_limit"] == 1
    assert emp1["current_task"]["key"] == "T1"
    assert team["Manager Web"]["membership_role"] == "MANAGER"
    assert as_user("emp_web_1").get(f"/projects/{project['id']}/team").status_code == 403


# ----------------------------------------------------------------------------- notifications


def test_notifications_are_private_and_can_be_marked_read(as_user, skilled_world, db):
    started_project(as_user, skilled_world)
    emp1 = as_user("emp_web_1")
    page = emp1.get("/notifications").json()
    assert page["unread"] == 1 and page["items"][0]["title"] == "New task: Database schema"

    manager_note = notes_for(db, skilled_world["manager_web"])[0]
    assert emp1.post(f"/notifications/{manager_note.id}/read", key=None).status_code == 404

    nid = page["items"][0]["id"]
    assert emp1.post(f"/notifications/{nid}/read", key=None).status_code == 204
    assert emp1.get("/notifications").json()["unread"] == 0
