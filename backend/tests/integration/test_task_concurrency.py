"""Two workers at the same time must never double-assign (CLAUDE.md section 9).

These tests use separate database sessions in separate threads against real PostgreSQL.
"""

import threading
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.principal import Principal
from app.models import (
    AssignmentSource,
    MembershipRole,
    Task,
    TaskAssignment,
    TaskPriority,
    TeamMembership,
    User,
)
from app.services.errors import DomainError
from app.services.tasks import service

pytestmark = pytest.mark.integration


def principal_for(db: Session, user_id: uuid.UUID) -> Principal:
    user = db.get(User, user_id)
    rows = db.execute(
        select(TeamMembership.team_id, TeamMembership.membership_role).where(
            TeamMembership.user_id == user_id
        )
    ).all()
    return Principal(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        session_id=uuid.uuid4(),
        csrf_token="test",
        member_team_ids=frozenset(t for t, _ in rows),
        managed_team_ids=frozenset(t for t, r in rows if r is MembershipRole.MANAGER),
    )


def make_task(db: Session, world, title: str) -> uuid.UUID:
    p = principal_for(db, world["manager_web"])
    task = service.create_task(
        db, p, service.NewTask(team_id=world["team_web"], title=title, priority=TaskPriority.HIGH)
    )
    db.commit()
    return task.id


def race(engine, jobs) -> list[str]:
    """Run each job in its own thread and session, released together by a barrier."""
    barrier = threading.Barrier(len(jobs))
    results: list[str] = []
    lock = threading.Lock()

    def worker(job):
        with Session(engine, expire_on_commit=False) as s:
            barrier.wait()
            try:
                job(s)
                s.commit()
                outcome = "ok"
            except DomainError as exc:
                s.rollback()
                outcome = exc.code
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return sorted(results)


@pytest.mark.parametrize("attempt", range(5))  # repeat: races are probabilistic
def test_same_task_assigned_by_two_managers_at_once(db, world, migrated_db_url, attempt):
    task_id = make_task(db, world, f"race {attempt}")
    engine = create_engine(migrated_db_url, pool_size=4)
    try:

        def assign_to(user_key):
            def job(s):
                p = principal_for(
                    s, world["admin_a"] if user_key == "emp_web_2" else world["manager_web"]
                )
                service.assign_task(s, p, task_id, world[user_key])

            return job

        results = race(engine, [assign_to("emp_web_1"), assign_to("emp_web_2")])
    finally:
        engine.dispose()

    assert results == ["invalid_transition", "ok"]
    open_rows = (
        db.execute(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task_id, TaskAssignment.ended_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    assert len(open_rows) == 1


@pytest.mark.parametrize("attempt", range(5))
def test_two_tasks_cannot_overload_one_person_at_once(db, world, migrated_db_url, attempt):
    t1, t2 = make_task(db, world, f"a{attempt}"), make_task(db, world, f"b{attempt}")
    engine = create_engine(migrated_db_url, pool_size=4)
    try:

        def assign(task_id):
            def job(s):
                p = principal_for(s, world["manager_web"])
                service.assign_task(s, p, task_id, world["emp_web_1"])

            return job

        results = race(engine, [assign(t1), assign(t2)])
    finally:
        engine.dispose()

    assert results == ["capacity_exceeded", "ok"]  # WIP limit is 1
    held = db.execute(select(Task).where(Task.assigned_to == world["emp_web_1"])).scalars().all()
    assert len(held) == 1


def test_database_refuses_a_second_open_assignment(db, world):
    """Last line of defence: even buggy code cannot create two open assignments."""
    task_id = make_task(db, world, "db guard")
    for user_key in ("emp_web_1", "emp_web_2"):
        db.add(
            TaskAssignment(
                task_id=task_id, assignee_id=world[user_key], source=AssignmentSource.MANUAL
            )
        )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_refuses_owner_status_mismatch(db, world):
    task_id = make_task(db, world, "check constraint")
    task = db.get(Task, task_id)
    task.assigned_to = world["emp_web_1"]  # UNASSIGNED with an owner is impossible
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
