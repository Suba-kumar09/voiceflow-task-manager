"""Orchestrator: evaluates a whole project and assigns every ready task it safely can.

- Runs under a per-project PostgreSQL advisory lock: one evaluation per project at a time.
- Each assignment goes through tasks.service.system_assign (row locks, workload, dependencies).
- Never forces work: tasks nobody qualifies for become a manager decision, with a reason.
- The caller commits.
"""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session, aliased

from app.auth.principal import Principal
from app.models import (
    ACTIVE_HOLD_STATUSES,
    AssignmentEndReason,
    AuditOutcome,
    MembershipRole,
    Notification,
    NotificationKind,
    Project,
    ProjectStatus,
    Skill,
    Task,
    TaskAssignment,
    TaskDependency,
    TaskRequiredSkill,
    TaskStatus,
    TeamMembership,
    User,
    UserSkill,
)
from app.services.audit import record_audit
from app.services.errors import DomainError
from app.services.notifications import notify, team_manager_ids
from app.services.orchestrator.planner import Candidate, Outcome, Plan, ReadyTask, plan_assignments
from app.services.tasks import service as tasks

logger = logging.getLogger(__name__)

# Codes raised by pre-write checks: safe to skip that one task and continue.
_SKIPPABLE = {"invalid_transition", "capacity_exceeded", "dependencies_unmet", "rule_violation"}


@dataclass
class EvaluationResult:
    project_id: uuid.UUID
    assigned: list[dict] = field(default_factory=list)
    waiting_for_capacity: list[dict] = field(default_factory=list)
    needs_decision: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "project_id": str(self.project_id),
            "assigned": self.assigned,
            "waiting_for_capacity": self.waiting_for_capacity,
            "needs_decision": self.needs_decision,
            "skipped": self.skipped,
        }


def _lock_project(db: Session, project_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"project:{project_id}"},
    )


def ready_task_ids_query(project_id: uuid.UUID):
    """UNASSIGNED tasks in the project whose predecessors are all COMPLETED."""
    pred = aliased(Task)
    unmet = exists().where(
        TaskDependency.task_id == Task.id,
        TaskDependency.depends_on_task_id == pred.id,
        pred.status != TaskStatus.COMPLETED,
    )
    return select(Task.id).where(
        Task.project_id == project_id, Task.status == TaskStatus.UNASSIGNED, ~unmet
    )


def _skills_by_task(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, frozenset[str]]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(TaskRequiredSkill.task_id, func.lower(Skill.name))
        .join(Skill, Skill.id == TaskRequiredSkill.skill_id)
        .where(TaskRequiredSkill.task_id.in_(task_ids))
    ).all()
    out: dict[uuid.UUID, set[str]] = {}
    for tid, name in rows:
        out.setdefault(tid, set()).add(name)
    return {k: frozenset(v) for k, v in out.items()}


def ready_tasks(db: Session, project: Project) -> list[ReadyTask]:
    rows = (
        db.execute(select(Task).where(Task.id.in_(ready_task_ids_query(project.id))))
        .scalars()
        .all()
    )
    skills = _skills_by_task(db, [t.id for t in rows])
    declined: dict[uuid.UUID, set[uuid.UUID]] = {}
    if rows:
        for tid, uid in db.execute(
            select(TaskAssignment.task_id, TaskAssignment.assignee_id).where(
                TaskAssignment.task_id.in_([t.id for t in rows]),
                TaskAssignment.end_reason == AssignmentEndReason.DECLINED,
            )
        ).all():
            declined.setdefault(tid, set()).add(uid)
    return [
        ReadyTask(
            id=t.id,
            key=t.external_key or "",
            title=t.title,
            priority=t.priority.value,
            due_at=t.due_at,
            created_at=t.created_at,
            required_skills=skills.get(t.id, frozenset()),
            excluded=frozenset(declined.get(t.id, set())),
        )
        for t in rows
    ]


def candidates(db: Session, project: Project) -> list[Candidate]:
    """Active MEMBERs of the project's team (managers are not auto-assigned work)."""
    users = (
        db.execute(
            select(User)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .where(
                TeamMembership.team_id == project.team_id,
                TeamMembership.membership_role == MembershipRole.MEMBER,
                User.is_active.is_(True),
                User.organization_id == project.organization_id,
            )
            .order_by(User.id)
        )
        .scalars()
        .all()
    )
    if not users:
        return []
    ids = [u.id for u in users]
    skills: dict[uuid.UUID, set[str]] = {}
    for uid, name in db.execute(
        select(UserSkill.user_id, func.lower(Skill.name))
        .join(Skill, Skill.id == UserSkill.skill_id)
        .where(UserSkill.user_id.in_(ids))
    ).all():
        skills.setdefault(uid, set()).add(name)
    loads = dict(
        db.execute(
            select(Task.assigned_to, func.count())
            .where(Task.assigned_to.in_(ids), Task.status.in_(ACTIVE_HOLD_STATUSES))
            .group_by(Task.assigned_to)
        ).all()
    )
    history = {
        uid: (n, last)
        for uid, n, last in db.execute(
            select(
                TaskAssignment.assignee_id,
                func.count(),
                func.max(TaskAssignment.assigned_at),
            )
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(Task.project_id == project.id, TaskAssignment.assignee_id.in_(ids))
            .group_by(TaskAssignment.assignee_id)
        ).all()
    }
    return [
        Candidate(
            id=u.id,
            name=u.display_name,
            skills=frozenset(skills.get(u.id, set())),
            load=loads.get(u.id, 0),
            wip_limit=u.wip_limit,
            assigned_in_project=history.get(u.id, (0, None))[0],
            last_assigned_at=history.get(u.id, (0, None))[1],
        )
        for u in users
    ]


def build_plan(db: Session, project: Project) -> Plan:
    return plan_assignments(ready_tasks(db, project), candidates(db, project))


def _item_view(item) -> dict:
    view = {
        "task_id": str(item.task.id),
        "key": item.task.key,
        "title": item.task.title,
        "priority": item.task.priority,
        "reason": item.reason,
    }
    if item.assignee:
        view["assignee_id"] = str(item.assignee.id)
        view["assignee_name"] = item.assignee.name
    return view


def plan_view(plan: Plan) -> list[dict]:
    return [{**_item_view(i), "outcome": i.outcome.value} for i in plan.items]


def _already_flagged(db: Session, task_id: uuid.UUID) -> bool:
    return (
        db.execute(
            select(Notification.id).where(
                Notification.task_id == task_id,
                Notification.kind == NotificationKind.NEEDS_DECISION,
                Notification.read_at.is_(None),
            )
        ).first()
        is not None
    )


def evaluate(
    db: Session, project_id: uuid.UUID, *, requested_by: Principal | None = None
) -> EvaluationResult:
    """Assign every ready task that can be assigned. Idempotent: re-running changes nothing new."""
    _lock_project(db, project_id)
    project = db.get(Project, project_id)
    result = EvaluationResult(project_id=project_id)
    if project is None or project.status is not ProjectStatus.ACTIVE:
        return result

    plan = build_plan(db, project)
    for item in plan.items:
        view = _item_view(item)
        if item.outcome is Outcome.ASSIGN:
            try:
                tasks.system_assign(
                    db,
                    item.task.id,
                    item.assignee.id,
                    reason=item.reason,
                    requested_by=requested_by,
                )
                result.assigned.append(view)
            except DomainError as exc:
                if exc.code not in _SKIPPABLE:
                    raise
                result.skipped.append({**view, "why": exc.message})
        elif item.outcome is Outcome.NO_CAPACITY:
            result.waiting_for_capacity.append(view)
        else:
            result.needs_decision.append(view)
            if not _already_flagged(db, item.task.id):
                for manager_id in team_manager_ids(db, project.team_id):
                    notify(
                        db,
                        organization_id=project.organization_id,
                        recipient_id=manager_id,
                        kind=NotificationKind.NEEDS_DECISION,
                        title=f"{item.task.title} needs your decision",
                        body=item.reason,
                        task_id=item.task.id,
                        project_id=project.id,
                    )

    if result.assigned:
        names = ", ".join(f"{a['title']} → {a['assignee_name']}" for a in result.assigned)
        for manager_id in team_manager_ids(db, project.team_id):
            notify(
                db,
                organization_id=project.organization_id,
                recipient_id=manager_id,
                kind=NotificationKind.PROJECT_SUMMARY,
                title=f"{project.name}: {len(result.assigned)} "
                + ("task assigned" if len(result.assigned) == 1 else "tasks assigned"),
                body=names,
                project_id=project.id,
            )
    record_audit(
        db,
        action="project.evaluate",
        outcome=AuditOutcome.SUCCESS,
        organization_id=project.organization_id,
        actor_user_id=requested_by.user_id if requested_by else None,
        target_type="project",
        target_id=project.id,
        details={
            "assigned": len(result.assigned),
            "waiting_for_capacity": len(result.waiting_for_capacity),
            "needs_decision": len(result.needs_decision),
            "skipped": len(result.skipped),
        },
    )
    db.flush()
    return result


def reevaluate_after_task_change(db: Session, task_id: uuid.UUID) -> list[EvaluationResult]:
    """Called after a task change has been COMMITTED.

    A finished, declined or cancelled task can unlock dependent work AND free a person who may
    be needed by any active project of the same team, so every active project of the team is
    re-evaluated (oldest first, deterministic). Each project runs in its own transaction; a
    failure is logged and rolled back and never undoes the user's committed change."""
    task = db.get(Task, task_id)
    if task is None:
        return []
    project_ids = list(
        db.execute(
            select(Project.id)
            .where(Project.team_id == task.team_id, Project.status == ProjectStatus.ACTIVE)
            .order_by(Project.created_at, Project.id)
        ).scalars()
    )
    results = []
    for project_id in project_ids:
        try:
            results.append(evaluate(db, project_id))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Project re-evaluation failed",
                extra={"data": {"task_id": str(task_id), "project_id": str(project_id)}},
            )
    return results
