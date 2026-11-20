"""Task API: creation, scoping, assignment, lifecycle, evidence and idempotency."""

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    AssignmentEndReason,
    AuditEvent,
    Task,
    TaskAssignment,
    TaskCompletionEvidence,
)

pytestmark = pytest.mark.integration


def new_task(api, world, team="team_web", **overrides):
    body = {"team_id": str(world[team]), "title": "Website testing", "priority": "HIGH"}
    body.update(overrides)
    return api.post("/tasks", json=body)


def created(api, world, **overrides) -> dict:
    resp = new_task(api, world, **overrides)
    assert resp.status_code == 201, resp.text
    return resp.json()


def assigned(api, world, user_key, **overrides) -> dict:
    task = created(api, world, **overrides)
    resp = api.post(f"/tasks/{task['id']}/assign", json={"assignee_id": str(world[user_key])})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ----------------------------------------------------------------------------- create


def test_manager_creates_task_in_task_pool(as_user, world, db):
    mgr = as_user("manager_web")
    task = created(mgr, world, due_at="2026-11-27T18:00:00+05:30")
    assert task["status"] == "UNASSIGNED"
    assert task["assignee"] is None
    assert task["priority"] == "HIGH"
    assert task["timezone"] == "Asia/Kolkata"
    assert task["version"] == 1

    history = mgr.get(f"/tasks/{task['id']}/history").json()
    assert [(h["action"], h["to_status"]) for h in history] == [("create", "UNASSIGNED")]
    assert db.execute(select(AuditEvent.action).where(AuditEvent.action == "task.create")).all()


def test_draft_then_publish(as_user, world):
    mgr = as_user("manager_web")
    task = created(mgr, world, publish=False)
    assert task["status"] == "DRAFT"
    assert mgr.post(f"/tasks/{task['id']}/publish").json()["status"] == "UNASSIGNED"


@pytest.mark.parametrize(
    "bad",
    [
        {"priority": None},  # priority is never guessed
        {"title": "   "},
        {"due_at": "2026-11-27T18:00:00"},  # no timezone: ambiguous
        {"estimated_effort_hours": 0},
    ],
)
def test_create_validation(as_user, world, bad):
    resp = new_task(as_user("manager_web"), world, **bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_requires_idempotency_key(as_user, world):
    mgr = as_user("manager_web")
    body = {"team_id": str(world["team_web"]), "title": "X", "priority": "LOW"}
    assert mgr.post("/tasks", json=body, key=None).status_code == 422


@pytest.mark.parametrize(
    ("user", "team", "status"),
    [
        ("manager_web", "team_mobile", 403),  # not their team
        ("emp_web_1", "team_web", 403),  # employees cannot create
        ("admin_a", "team_mobile", 201),  # admins can
        ("manager_b", "team_web", 404),  # other organization
    ],
)
def test_create_permissions(as_user, world, user, team, status):
    assert new_task(as_user(user), world, team=team).status_code == status


def test_create_needs_csrf(make_client, migrated_db_url, world):
    from tests.conftest import login

    client = make_client(migrated_db_url)
    login(client, "manager_web")
    resp = client.post(
        "/api/v1/tasks",
        json={"team_id": str(world["team_web"]), "title": "X", "priority": "LOW"},
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 403


# ----------------------------------------------------------------------------- idempotency


def test_retry_with_same_key_returns_same_task_and_creates_nothing_new(as_user, world, db):
    mgr = as_user("manager_web")
    body = {"team_id": str(world["team_web"]), "title": "API testing", "priority": "HIGH"}
    first = mgr.post("/tasks", json=body, key="retry-1")
    second = mgr.post("/tasks", json=body, key="retry-1")
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert db.execute(select(Task)).scalars().all().__len__() == 1


def test_same_key_different_request_is_refused(as_user, world):
    mgr = as_user("manager_web")
    base = {"team_id": str(world["team_web"]), "priority": "HIGH"}
    assert mgr.post("/tasks", json={**base, "title": "A"}, key="k").status_code == 201
    resp = mgr.post("/tasks", json={**base, "title": "B"}, key="k")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "idempotency_key_reused"


def test_keys_are_per_user(as_user, world):
    body = {"team_id": str(world["team_web"]), "title": "Same", "priority": "LOW"}
    a = as_user("manager_web").post("/tasks", json=body, key="shared")
    b = as_user("admin_a").post("/tasks", json=body, key="shared")
    assert a.json()["id"] != b.json()["id"]


# ----------------------------------------------------------------------------- listing scope


def test_listing_is_scoped_to_role(as_user, world):
    mgr_web, mgr_mobile = as_user("manager_web"), as_user("manager_mobile")
    web_task = assigned(mgr_web, world, "emp_web_1", title="Web task")
    created(mgr_web, world, title="Web pool task")
    created(mgr_mobile, world, team="team_mobile", title="Mobile task")

    def titles(api, path="/tasks"):
        return {t["title"] for t in api.get(path).json()["items"]}

    assert titles(mgr_web) == {"Web task", "Web pool task"}
    assert titles(mgr_mobile) == {"Mobile task"}
    assert titles(as_user("admin_a")) == {"Web task", "Web pool task", "Mobile task"}
    assert titles(as_user("emp_web_1")) == {"Web task"}
    assert titles(as_user("emp_web_2")) == set()
    assert titles(as_user("manager_b")) == set()
    assert titles(as_user("emp_web_1"), "/me/tasks") == {"Web task"}

    # Direct access follows the same rules.
    assert as_user("emp_web_2").get(f"/tasks/{web_task['id']}").status_code == 403
    assert as_user("manager_mobile").get(f"/tasks/{web_task['id']}").status_code == 403
    assert as_user("manager_b").get(f"/tasks/{web_task['id']}").status_code == 404


def test_list_filters_by_status(as_user, world):
    mgr = as_user("manager_web")
    assigned(mgr, world, "emp_web_1", title="Assigned one")
    created(mgr, world, title="Pool one")
    items = mgr.get("/tasks?status=UNASSIGNED").json()["items"]
    assert [t["title"] for t in items] == ["Pool one"]


def test_tasks_sorted_by_priority_then_due_date(as_user, world):
    mgr = as_user("manager_web")
    created(mgr, world, title="low", priority="LOW")
    created(mgr, world, title="urgent", priority="URGENT")
    created(mgr, world, title="high-late", priority="HIGH", due_at="2026-12-10T10:00:00+05:30")
    created(mgr, world, title="high-soon", priority="HIGH", due_at="2026-12-01T10:00:00+05:30")
    titles = [t["title"] for t in mgr.get("/tasks").json()["items"]]
    assert titles == ["urgent", "high-soon", "high-late", "low"]


# ----------------------------------------------------------------------------- assignment


def test_assign_records_assignment_history_and_audit(as_user, world, db):
    mgr = as_user("manager_web")
    task = assigned(mgr, world, "emp_web_1")
    assert task["status"] == "ASSIGNED"
    assert task["assignee"] == {"id": str(world["emp_web_1"]), "display_name": "Emp Web 1"}

    rows = db.execute(select(TaskAssignment)).scalars().all()
    assert len(rows) == 1 and rows[0].ended_at is None and rows[0].source.value == "MANUAL"
    actions = [h["action"] for h in mgr.get(f"/tasks/{task['id']}/history").json()]
    assert actions == ["create", "assign"]


@pytest.mark.parametrize(
    ("assignee", "message_part"),
    [
        ("emp_mobile", "not a member of this task's team"),
        ("inactive_emp", "not active"),
        ("emp_b", "not found in your organization"),
    ],
)
def test_assign_rejects_unsuitable_assignee(as_user, world, assignee, message_part):
    mgr = as_user("manager_web")
    task = created(mgr, world)
    resp = mgr.post(f"/tasks/{task['id']}/assign", json={"assignee_id": str(world[assignee])})
    assert resp.status_code == 422
    assert message_part in resp.json()["error"]["message"]


def test_workload_limit_and_audited_override(as_user, world, db):
    mgr = as_user("manager_web")
    assigned(mgr, world, "emp_web_1", title="First")
    second = created(mgr, world, title="Second")

    resp = mgr.post(f"/tasks/{second['id']}/assign", json={"assignee_id": str(world["emp_web_1"])})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "capacity_exceeded"

    resp = mgr.post(
        f"/tasks/{second['id']}/assign",
        json={"assignee_id": str(world["emp_web_1"]), "override_capacity": True},
    )
    assert resp.status_code == 200
    audit = db.execute(
        select(AuditEvent).where(
            AuditEvent.action == "task.assign", AuditEvent.target_id == second["id"]
        )
    ).scalar_one()
    assert audit.details["override_capacity"] is True


def test_completed_work_frees_capacity(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    first = assigned(mgr, world, "emp_web_1", title="First")
    emp.post(f"/tasks/{first['id']}/start")
    emp.post(f"/tasks/{first['id']}/request-completion")
    second = created(mgr, world, title="Second")
    resp = mgr.post(f"/tasks/{second['id']}/assign", json={"assignee_id": str(world["emp_web_1"])})
    assert resp.status_code == 200


def test_employee_cannot_assign(as_user, world):
    task = created(as_user("manager_web"), world)
    resp = as_user("emp_web_1").post(
        f"/tasks/{task['id']}/assign", json={"assignee_id": str(world["emp_web_1"])}
    )
    assert resp.status_code == 403


def test_cannot_assign_an_already_assigned_task(as_user, world):
    mgr = as_user("manager_web")
    task = assigned(mgr, world, "emp_web_1")
    resp = mgr.post(f"/tasks/{task['id']}/assign", json={"assignee_id": str(world["emp_web_2"])})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_transition"


def test_reassign_closes_old_assignment(as_user, world, db):
    mgr = as_user("manager_web")
    task = assigned(mgr, world, "emp_web_1")
    no_reason = mgr.post(
        f"/tasks/{task['id']}/reassign", json={"assignee_id": str(world["emp_web_2"]), "reason": ""}
    )
    assert no_reason.status_code == 422

    resp = mgr.post(
        f"/tasks/{task['id']}/reassign",
        json={"assignee_id": str(world["emp_web_2"]), "reason": "Emp 1 is on leave"},
    )
    assert resp.status_code == 200
    assert resp.json()["assignee"]["id"] == str(world["emp_web_2"])
    rows = db.execute(select(TaskAssignment).order_by(TaskAssignment.assigned_at)).scalars().all()
    assert [r.end_reason for r in rows] == [AssignmentEndReason.REASSIGNED, None]
    assert as_user("emp_web_1").get(f"/tasks/{task['id']}").status_code == 403


# ----------------------------------------------------------------------------- lifecycle


def test_simple_task_completes_without_review(as_user, world, db):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1")
    assert emp.post(f"/tasks/{task['id']}/accept").json()["status"] == "ACCEPTED"
    assert emp.post(f"/tasks/{task['id']}/start").json()["status"] == "IN_PROGRESS"
    done = emp.post(f"/tasks/{task['id']}/request-completion").json()
    assert done["status"] == "COMPLETED"
    assert done["assignee"]["id"] == str(world["emp_web_1"])  # who did the work is kept

    row = db.execute(select(TaskAssignment)).scalar_one()
    assert row.end_reason is AssignmentEndReason.COMPLETED
    actions = [h["action"] for h in emp.get(f"/tasks/{task['id']}/history").json()]
    assert actions == ["create", "assign", "accept", "start", "request_completion"]


def test_review_flow_reject_then_approve(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1", evidence_policy="MANAGER_APPROVAL")
    tid = task["id"]
    emp.post(f"/tasks/{tid}/start")
    assert emp.post(f"/tasks/{tid}/request-completion").json()["status"] == "PENDING_REVIEW"

    assert emp.post(f"/tasks/{tid}/approve-completion").status_code == 403  # no self-approval
    assert mgr.post(f"/tasks/{tid}/reject-completion").json()["error"]["code"] == "reason_required"

    rejected = mgr.post(f"/tasks/{tid}/reject-completion", json={"reason": "Tests are failing"})
    assert rejected.json()["status"] == "IN_PROGRESS"
    emp.post(f"/tasks/{tid}/request-completion")
    assert mgr.post(f"/tasks/{tid}/approve-completion").json()["status"] == "COMPLETED"

    history = mgr.get(f"/tasks/{tid}/history").json()
    assert any(h["reason"] == "Tests are failing" for h in history)


def test_note_evidence_required_and_stored(as_user, world, db):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1", evidence_policy="NOTE")
    emp.post(f"/tasks/{task['id']}/start")
    missing = emp.post(f"/tasks/{task['id']}/request-completion")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "evidence_required"

    ok = emp.post(
        f"/tasks/{task['id']}/request-completion", json={"note": "All 40 test cases pass."}
    )
    assert ok.json()["status"] == "PENDING_REVIEW"
    ev = db.execute(select(TaskCompletionEvidence)).scalar_one()
    assert ev.kind.value == "NOTE" and ev.content == "All 40 test cases pass."


def test_link_evidence_must_be_a_real_url(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1", evidence_policy="LINK")
    emp.post(f"/tasks/{task['id']}/start")
    bad = emp.post(f"/tasks/{task['id']}/request-completion", json={"link": "javascript:alert(1)"})
    assert bad.status_code == 422
    good = emp.post(
        f"/tasks/{task['id']}/request-completion",
        json={"link": "https://git.example.com/pr/42"},
    )
    assert good.json()["status"] == "PENDING_REVIEW"


def test_cannot_complete_work_that_was_never_started(as_user, world):
    task = assigned(as_user("manager_web"), world, "emp_web_1")
    resp = as_user("emp_web_1").post(f"/tasks/{task['id']}/request-completion")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_transition"


def test_employee_cannot_act_on_someone_elses_task(as_user, world, db):
    task = assigned(as_user("manager_web"), world, "emp_web_1")
    resp = as_user("emp_web_2").post(f"/tasks/{task['id']}/start")
    assert resp.status_code == 403
    denied = db.execute(select(AuditEvent).where(AuditEvent.action == "task.start")).scalar_one()
    assert denied.outcome.value == "DENIED"


def test_manager_cannot_claim_employee_work_is_done(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1")
    emp.post(f"/tasks/{task['id']}/start")
    assert mgr.post(f"/tasks/{task['id']}/request-completion").status_code == 403


def test_block_and_resume(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1")
    emp.post(f"/tasks/{task['id']}/start")
    assert emp.post(f"/tasks/{task['id']}/block").status_code == 422  # reason needed
    blocked = emp.post(f"/tasks/{task['id']}/block", json={"reason": "API server is down"})
    assert blocked.json()["status"] == "BLOCKED"
    assert mgr.post(f"/tasks/{task['id']}/resume").json()["status"] == "IN_PROGRESS"


def test_decline_returns_task_to_pool(as_user, world, db):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1")
    assert emp.post(f"/tasks/{task['id']}/decline").status_code == 422
    resp = emp.post(f"/tasks/{task['id']}/decline", json={"reason": "No access to staging"})
    assert resp.json()["status"] == "UNASSIGNED"
    assert resp.json()["assignee"] is None
    row = db.execute(select(TaskAssignment)).scalar_one()
    assert row.end_reason is AssignmentEndReason.DECLINED


def test_cancel_rules(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    pool = created(mgr, world, title="pool")
    assert (
        mgr.post(f"/tasks/{pool['id']}/cancel", json={"reason": "Out of scope"}).json()["status"]
        == "CANCELLED"
    )

    started = assigned(mgr, world, "emp_web_1", title="started")
    emp.post(f"/tasks/{started['id']}/start")
    resp = mgr.post(f"/tasks/{started['id']}/cancel", json={"reason": "x"})
    assert resp.status_code == 409


def test_current_task_prefers_work_in_progress(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    assert emp.get("/me/tasks/current").json() == {"task": None}

    urgent_new = created(mgr, world, title="urgent new", priority="URGENT")
    mgr.post(f"/tasks/{urgent_new['id']}/assign", json={"assignee_id": str(world["emp_web_1"])})
    in_progress = created(mgr, world, title="in progress", priority="LOW")
    mgr.post(
        f"/tasks/{in_progress['id']}/assign",
        json={"assignee_id": str(world["emp_web_1"]), "override_capacity": True},
    )
    emp.post(f"/tasks/{in_progress['id']}/start")
    assert emp.get("/me/tasks/current").json()["task"]["title"] == "in progress"


# ----------------------------------------------------------------------------- editing


def test_edit_uses_optimistic_concurrency(as_user, world):
    mgr = as_user("manager_web")
    task = created(mgr, world)
    ok = mgr.patch(f"/tasks/{task['id']}", json={"version": 1, "priority": "URGENT"})
    assert ok.status_code == 200
    assert ok.json()["priority"] == "URGENT" and ok.json()["version"] == 2

    stale = mgr.patch(f"/tasks/{task['id']}", json={"version": 1, "title": "Old view"})
    assert stale.status_code == 409


def test_employee_cannot_edit_and_finished_tasks_are_frozen(as_user, world):
    mgr, emp = as_user("manager_web"), as_user("emp_web_1")
    task = assigned(mgr, world, "emp_web_1")
    assert (
        emp.patch(f"/tasks/{task['id']}", json={"version": 2, "title": "Mine"}).status_code == 403
    )
    emp.post(f"/tasks/{task['id']}/start")
    done = emp.post(f"/tasks/{task['id']}/request-completion").json()
    resp = mgr.patch(
        f"/tasks/{task['id']}", json={"version": done["version"], "title": "Late edit"}
    )
    assert resp.status_code == 422


def test_unknown_task_is_404(as_user, world):
    assert as_user("manager_web").get(f"/tasks/{uuid.uuid4()}").status_code == 404
