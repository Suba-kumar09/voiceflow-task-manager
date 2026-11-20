"""Task service: the only code that changes tasks.

Rules:
- Services never commit; the caller (API / idempotency helper) commits once, so every change,
  its history row and its audit event succeed or fail together.
- Exception: a permission denial is audited and committed before raising.
- Rows are locked (SELECT ... FOR UPDATE) before any state change.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.exc import StaleDataError

from app.auth.principal import Principal
from app.models import (
    ACTIVE_HOLD_STATUSES,
    AssignmentEndReason,
    AssignmentSource,
    AuditOutcome,
    EvidenceKind,
    EvidencePolicy,
    NotificationKind,
    Organization,
    Project,
    Task,
    TaskAssignment,
    TaskCompletionEvidence,
    TaskDependency,
    TaskPriority,
    TaskStatus,
    TaskStatusHistory,
    Team,
    TeamMembership,
    User,
)
from app.models.common import utcnow
from app.services.audit import record_audit
from app.services.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RuleViolationError,
)
from app.services.notifications import notify, notify_team_managers
from app.services.tasks import lifecycle
from app.services.tasks.lifecycle import Action, ActorKind, TransitionRefused

PRIORITY_RANK = {
    TaskPriority.URGENT: 4,
    TaskPriority.HIGH: 3,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 1,
}


# ----------------------------------------------------------------------------- helpers


def actor_kinds(p: Principal, task: Task) -> set[ActorKind]:
    kinds: set[ActorKind] = set()
    if p.is_admin or task.team_id in p.managed_team_ids:
        kinds.add(ActorKind.MANAGER)
    if task.assigned_to is not None and task.assigned_to == p.user_id:
        kinds.add(ActorKind.ASSIGNEE)
    return kinds


def _deny(db: Session, p: Principal, task_id: uuid.UUID, action: str, message: str) -> None:
    record_audit(
        db,
        action=f"task.{action}",
        outcome=AuditOutcome.DENIED,
        organization_id=p.organization_id,
        actor_user_id=p.user_id,
        target_type="task",
        target_id=task_id,
    )
    db.commit()
    raise PermissionDeniedError(message)


def _load_task(db: Session, p: Principal, task_id: uuid.UUID, *, lock: bool) -> Task:
    stmt = select(Task).where(Task.id == task_id)
    if lock:
        stmt = stmt.with_for_update()
    task = db.execute(stmt).scalar_one_or_none()
    # Another organization's task is indistinguishable from a missing one.
    if task is None or task.organization_id != p.organization_id:
        raise NotFoundError("Task not found.")
    return task


def _history(
    db: Session,
    task: Task,
    *,
    action: str,
    from_status: TaskStatus | None,
    actor_user_id: uuid.UUID | None,
    reason: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        TaskStatusHistory(
            task_id=task.id,
            from_status=from_status,
            to_status=task.status,
            action=action,
            actor_user_id=actor_user_id,
            reason=reason,
            details=details or {},
        )
    )


def _audit(db: Session, p: Principal | None, task: Task, action: str, details: dict) -> None:
    record_audit(
        db,
        action=f"task.{action}",
        outcome=AuditOutcome.SUCCESS,
        organization_id=task.organization_id,
        actor_user_id=p.user_id if p else None,
        target_type="task",
        target_id=task.id,
        details=details,
    )


def _open_assignment(db: Session, task_id: uuid.UUID) -> TaskAssignment | None:
    return db.execute(
        select(TaskAssignment).where(
            TaskAssignment.task_id == task_id, TaskAssignment.ended_at.is_(None)
        )
    ).scalar_one_or_none()


def _close_assignment(db: Session, task_id: uuid.UUID, reason: AssignmentEndReason) -> None:
    open_ = _open_assignment(db, task_id)
    if open_ is not None:
        open_.ended_at = utcnow()
        open_.end_reason = reason


def _flush(db: Session) -> None:
    """Flush pending writes, turning concurrency clashes into a clean 409."""
    try:
        db.flush()
    except StaleDataError as exc:
        db.rollback()
        raise ConflictError("The task was changed by someone else. Please retry.") from exc
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("The task was changed by someone else. Please retry.") from exc


def _clean(text: str | None) -> str | None:
    return text.strip() if text and text.strip() else None


# ----------------------------------------------------------------------------- create / read


@dataclass(frozen=True)
class NewTask:
    team_id: uuid.UUID
    title: str
    priority: TaskPriority
    project_id: uuid.UUID | None = None
    external_key: str | None = None
    description: str = ""
    acceptance_criteria: str = ""
    due_at: datetime | None = None
    estimated_effort_hours: Decimal | None = None
    requires_approval: bool = False
    evidence_policy: EvidencePolicy = EvidencePolicy.NONE
    publish: bool = True  # True = straight into the task pool (UNASSIGNED); False = DRAFT


def create_task(db: Session, p: Principal, data: NewTask) -> Task:
    team = db.get(Team, data.team_id)
    if team is None or team.organization_id != p.organization_id:
        raise NotFoundError("Team not found.")
    if not (p.is_admin or team.id in p.managed_team_ids):
        _deny(db, p, team.id, "create", "You can only create tasks for teams you manage.")
    if data.project_id is not None:
        project = db.get(Project, data.project_id)
        if project is None or project.organization_id != p.organization_id:
            raise NotFoundError("Project not found.")
        if project.team_id != team.id:
            raise RuleViolationError("The project belongs to a different team.")

    org = db.get(Organization, p.organization_id)
    task = Task(
        organization_id=p.organization_id,
        team_id=team.id,
        project_id=data.project_id,
        external_key=_clean(data.external_key),
        title=data.title.strip(),
        description=data.description.strip(),
        acceptance_criteria=data.acceptance_criteria.strip(),
        priority=data.priority,
        status=TaskStatus.UNASSIGNED if data.publish else TaskStatus.DRAFT,
        created_by=p.user_id,
        due_at=data.due_at,
        timezone=org.timezone if org else "UTC",
        estimated_effort_hours=data.estimated_effort_hours,
        requires_approval=data.requires_approval,
        evidence_policy=data.evidence_policy,
    )
    db.add(task)
    _flush(db)
    _history(db, task, action="create", from_status=None, actor_user_id=p.user_id)
    _audit(db, p, task, "create", {"status": task.status.value, "priority": task.priority.value})
    _flush(db)
    return task


def get_task(db: Session, p: Principal, task_id: uuid.UUID) -> Task:
    task = _load_task(db, p, task_id, lock=False)
    if not actor_kinds(p, task):
        _deny(db, p, task.id, "view", "You do not have access to this task.")
    return task


def list_tasks(
    db: Session,
    p: Principal,
    *,
    statuses: Sequence[TaskStatus] = (),
    team_id: uuid.UUID | None = None,
    assigned_to_me: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Task], int]:
    stmt = select(Task).where(Task.organization_id == p.organization_id)
    if assigned_to_me:
        stmt = stmt.where(Task.assigned_to == p.user_id)
    elif not p.is_admin:
        # Managers: their teams' tasks plus anything assigned to them. Employees: only their own.
        stmt = stmt.where(
            or_(Task.team_id.in_(p.managed_team_ids), Task.assigned_to == p.user_id)
            if p.managed_team_ids
            else Task.assigned_to == p.user_id
        )
    if statuses:
        stmt = stmt.where(Task.status.in_(statuses))
    if team_id is not None:
        stmt = stmt.where(Task.team_id == team_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rank = case(PRIORITY_RANK, value=Task.priority, else_=0)
    rows = db.execute(
        stmt.order_by(rank.desc(), Task.due_at.asc().nulls_last(), Task.created_at, Task.id)
        .limit(limit)
        .offset(offset)
    ).scalars()
    return list(rows), total


_CURRENT_ORDER = {
    TaskStatus.IN_PROGRESS: 0,
    TaskStatus.BLOCKED: 1,
    TaskStatus.ACCEPTED: 2,
    TaskStatus.ASSIGNED: 3,
}


def current_task(db: Session, p: Principal) -> Task | None:
    """The task an employee should hear about first: in-progress, then blocked, then new."""
    tasks, _ = list_tasks(
        db, p, statuses=list(_CURRENT_ORDER), assigned_to_me=True, limit=200, offset=0
    )
    if not tasks:
        return None
    return min(
        tasks,
        key=lambda t: (
            _CURRENT_ORDER[t.status],
            -PRIORITY_RANK[t.priority],
            t.due_at is None,
            t.due_at or t.created_at,
            t.created_at,
        ),
    )


def history(db: Session, p: Principal, task_id: uuid.UUID) -> list[TaskStatusHistory]:
    get_task(db, p, task_id)  # enforces access
    return list(
        db.execute(
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id == task_id)
            .order_by(TaskStatusHistory.occurred_at, TaskStatusHistory.id)
        ).scalars()
    )


# ----------------------------------------------------------------------------- edit


_EDITABLE = {
    "title",
    "description",
    "acceptance_criteria",
    "priority",
    "due_at",
    "estimated_effort_hours",
    "requires_approval",
    "evidence_policy",
}
_FINAL = (TaskStatus.COMPLETED, TaskStatus.CANCELLED)


def update_task(
    db: Session, p: Principal, task_id: uuid.UUID, expected_version: int, changes: dict
) -> Task:
    task = _load_task(db, p, task_id, lock=True)
    if ActorKind.MANAGER not in actor_kinds(p, task):
        _deny(db, p, task.id, "update", "Only a manager of this team can edit the task.")
    if task.version != expected_version:
        raise ConflictError(
            f"The task was changed by someone else (now version {task.version}). Reload and retry."
        )
    if task.status in _FINAL:
        raise RuleViolationError(f"A {task.status.value} task cannot be edited.")
    unknown = set(changes) - _EDITABLE
    if unknown:
        raise RuleViolationError(f"These fields cannot be edited: {', '.join(sorted(unknown))}.")

    before = {k: getattr(task, k) for k in changes}
    for key, value in changes.items():
        setattr(task, key, value.strip() if isinstance(value, str) else value)
    _flush(db)
    _history(
        db,
        task,
        action="update",
        from_status=task.status,
        actor_user_id=p.user_id,
        details={"changed": sorted(changes)},
    )
    _audit(db, p, task, "update", {"changed": sorted(changes), "before": _jsonable(before)})
    _flush(db)
    return task


def _jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else str(v)) for k, v in d.items()}


# ----------------------------------------------------------------------------- assignment


def _check_assignee(
    db: Session, task: Task, assignee_id: uuid.UUID, *, override_capacity: bool
) -> User:
    # Lock the person too, so concurrent assignments cannot both pass the WIP check.
    assignee = db.execute(
        select(User).where(User.id == assignee_id).with_for_update()
    ).scalar_one_or_none()
    if assignee is None or assignee.organization_id != task.organization_id:
        raise RuleViolationError("That employee was not found in your organization.")
    if not assignee.is_active:
        raise RuleViolationError(f"{assignee.display_name} is not active.")
    in_team = db.execute(
        select(TeamMembership.id).where(
            TeamMembership.team_id == task.team_id, TeamMembership.user_id == assignee.id
        )
    ).first()
    if in_team is None:
        raise RuleViolationError(f"{assignee.display_name} is not a member of this task's team.")

    held = db.execute(
        select(func.count())
        .select_from(Task)
        .where(Task.assigned_to == assignee.id, Task.status.in_(ACTIVE_HOLD_STATUSES))
    ).scalar_one()
    if held >= assignee.wip_limit and not override_capacity:
        raise ConflictError(
            f"{assignee.display_name} already has {held} active task(s) "
            f"(limit {assignee.wip_limit}).",
            code="capacity_exceeded",
        )
    return assignee


def unmet_dependencies(db: Session, task_id: uuid.UUID) -> list[str]:
    """Keys/titles of predecessor tasks that are not COMPLETED yet."""
    pred = aliased(Task)
    rows = db.execute(
        select(pred.external_key, pred.title)
        .join(TaskDependency, TaskDependency.depends_on_task_id == pred.id)
        .where(TaskDependency.task_id == task_id, pred.status != TaskStatus.COMPLETED)
        .order_by(pred.external_key, pred.title)
    ).all()
    return [k or t for k, t in rows]


def _require_dependencies_met(db: Session, task: Task) -> None:
    """Checked before anything else: no one may start work whose predecessors are unfinished."""
    waiting_on = unmet_dependencies(db, task.id)
    if waiting_on:
        raise RuleViolationError(
            "This task cannot be assigned yet. It is waiting on: " + ", ".join(waiting_on) + ".",
            code="dependencies_unmet",
        )


def _apply_assignment(
    db: Session,
    task: Task,
    assignee: User,
    *,
    source: AssignmentSource,
    actor: Principal | None,
    details: dict,
) -> None:
    """The single place a task becomes ASSIGNED (manual and orchestrator paths).
    Callers must run _require_dependencies_met and _check_assignee first."""
    previous = task.status
    task.status = TaskStatus.ASSIGNED
    task.assigned_to = assignee.id
    db.add(
        TaskAssignment(
            task_id=task.id,
            assignee_id=assignee.id,
            source=source,
            assigned_by=actor.user_id if actor else None,
        )
    )
    _flush(db)
    full = {"assignee_id": str(assignee.id), "source": source.value, **details}
    _history(
        db,
        task,
        action=Action.ASSIGN.value,
        from_status=previous,
        actor_user_id=actor.user_id if actor else None,
        details=full,
    )
    _audit(db, actor, task, Action.ASSIGN.value, full)
    by = "your manager" if actor else "VoiceFlow"
    notify(
        db,
        organization_id=task.organization_id,
        recipient_id=assignee.id,
        kind=NotificationKind.TASK_ASSIGNED,
        title=f"New task: {task.title}",
        body=f"Assigned by {by}. {task.priority.value.capitalize()} priority."
        + (f" {details['reason']}" if details.get("reason") else ""),
        task_id=task.id,
        project_id=task.project_id,
    )
    _flush(db)


def assign_task(
    db: Session,
    p: Principal,
    task_id: uuid.UUID,
    assignee_id: uuid.UUID,
    *,
    override_capacity: bool = False,
) -> Task:
    """Manual assignment by a manager (the exception path)."""
    task = _load_task(db, p, task_id, lock=True)
    try:
        lifecycle.check(Action.ASSIGN, task.status, actor_kinds(p, task), None)
    except TransitionRefused as exc:
        _raise_refusal(db, p, task, Action.ASSIGN, exc)

    _require_dependencies_met(db, task)
    assignee = _check_assignee(db, task, assignee_id, override_capacity=override_capacity)
    _apply_assignment(
        db,
        task,
        assignee,
        source=AssignmentSource.MANUAL,
        actor=p,
        details={"override_capacity": override_capacity},
    )
    return task


def system_assign(
    db: Session,
    task_id: uuid.UUID,
    assignee_id: uuid.UUID,
    *,
    reason: str,
    requested_by: Principal | None = None,
) -> Task:
    """Orchestrator assignment. Re-checks everything under row locks; never overrides capacity."""
    task = db.execute(select(Task).where(Task.id == task_id).with_for_update()).scalar_one()
    try:
        lifecycle.check(Action.ASSIGN, task.status, {ActorKind.SYSTEM}, None)
    except TransitionRefused as exc:
        raise ConflictError(exc.message, code=exc.code) from exc
    _require_dependencies_met(db, task)
    assignee = _check_assignee(db, task, assignee_id, override_capacity=False)
    _apply_assignment(
        db,
        task,
        assignee,
        source=AssignmentSource.ORCHESTRATOR,
        actor=None,
        details={
            "reason": reason,
            **({"requested_by": str(requested_by.user_id)} if requested_by else {}),
        },
    )
    return task


def reassign_task(
    db: Session,
    p: Principal,
    task_id: uuid.UUID,
    assignee_id: uuid.UUID,
    reason: str,
    *,
    override_capacity: bool = False,
) -> Task:
    task = _load_task(db, p, task_id, lock=True)
    try:
        lifecycle.check(Action.REASSIGN, task.status, actor_kinds(p, task), reason)
    except TransitionRefused as exc:
        _raise_refusal(db, p, task, Action.REASSIGN, exc)
    if task.assigned_to == assignee_id:
        raise RuleViolationError("The task is already assigned to that employee.")

    assignee = _check_assignee(db, task, assignee_id, override_capacity=override_capacity)
    previous_status, previous_assignee = task.status, task.assigned_to
    _close_assignment(db, task.id, AssignmentEndReason.REASSIGNED)
    _flush(db)  # close the old row before opening the new one (one-open-assignment index)
    task.status = TaskStatus.ASSIGNED
    task.assigned_to = assignee.id
    db.add(
        TaskAssignment(
            task_id=task.id,
            assignee_id=assignee.id,
            source=AssignmentSource.MANUAL,
            assigned_by=p.user_id,
        )
    )
    _flush(db)
    details = {"from_assignee_id": str(previous_assignee), "to_assignee_id": str(assignee.id)}
    _history(
        db,
        task,
        action=Action.REASSIGN.value,
        from_status=previous_status,
        actor_user_id=p.user_id,
        reason=reason.strip(),
        details=details,
    )
    _audit(db, p, task, Action.REASSIGN.value, details)
    _flush(db)
    return task


# ----------------------------------------------------------------------------- transitions


def _raise_refusal(
    db: Session, p: Principal, task: Task, action: Action, exc: TransitionRefused
) -> None:
    if exc.code == "forbidden":
        if not actor_kinds(p, task):
            _deny(db, p, task.id, action.value, "You do not have access to this task.")
        _deny(db, p, task.id, action.value, exc.message)
    if exc.code == "invalid_transition":
        raise ConflictError(exc.message, code="invalid_transition")
    raise RuleViolationError(exc.message, code=exc.code)


def _validate_link(link: str) -> str:
    parsed = urlparse(link.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuleViolationError("The evidence link must be a full http(s) URL.")
    return link.strip()


_SIMPLE_ACTIONS = {
    Action.PUBLISH,
    Action.UNASSIGN,
    Action.ACCEPT,
    Action.DECLINE,
    Action.START,
    Action.BLOCK,
    Action.RESUME,
    Action.REQUEST_COMPLETION,
    Action.APPROVE_COMPLETION,
    Action.REJECT_COMPLETION,
    Action.CANCEL,
}


def transition(
    db: Session,
    p: Principal,
    task_id: uuid.UUID,
    action: Action,
    *,
    reason: str | None = None,
    note: str | None = None,
    link: str | None = None,
) -> Task:
    if action not in _SIMPLE_ACTIONS:
        raise RuleViolationError(f"Use the dedicated endpoint for {action.value}.")
    task = _load_task(db, p, task_id, lock=True)
    try:
        lifecycle.check(action, task.status, actor_kinds(p, task), reason)
    except TransitionRefused as exc:
        _raise_refusal(db, p, task, action, exc)

    previous = task.status
    reason = _clean(reason)
    details: dict = {}

    if action is Action.PUBLISH:
        task.status = TaskStatus.UNASSIGNED
    elif action in (Action.UNASSIGN, Action.DECLINE):
        end = (
            AssignmentEndReason.DECLINED
            if action is Action.DECLINE
            else AssignmentEndReason.UNASSIGNED
        )
        details["previous_assignee_id"] = str(task.assigned_to)
        _close_assignment(db, task.id, end)
        task.status = TaskStatus.UNASSIGNED
        task.assigned_to = None
    elif action is Action.ACCEPT:
        task.status = TaskStatus.ACCEPTED
    elif action in (Action.START, Action.RESUME, Action.REJECT_COMPLETION):
        task.status = TaskStatus.IN_PROGRESS
    elif action is Action.BLOCK:
        task.status = TaskStatus.BLOCKED
    elif action is Action.REQUEST_COMPLETION:
        details.update(_record_evidence(db, p, task, note=note, link=link))
        task.status = lifecycle.completion_target(task.requires_approval, task.evidence_policy)
        if task.status is TaskStatus.COMPLETED:
            _close_assignment(db, task.id, AssignmentEndReason.COMPLETED)
    elif action is Action.APPROVE_COMPLETION:
        task.status = TaskStatus.COMPLETED
        _close_assignment(db, task.id, AssignmentEndReason.COMPLETED)
    elif action is Action.CANCEL:
        if task.assigned_to is not None:
            details["previous_assignee_id"] = str(task.assigned_to)
            _close_assignment(db, task.id, AssignmentEndReason.CANCELLED)
            task.assigned_to = None
        task.status = TaskStatus.CANCELLED

    _flush(db)
    _history(
        db,
        task,
        action=action.value,
        from_status=previous,
        actor_user_id=p.user_id,
        reason=reason,
        details=details,
    )
    _audit(db, p, task, action.value, {"from": previous.value, "to": task.status.value, **details})
    _notify_for_transition(
        db,
        p,
        task,
        action,
        previous_assignee=details.get("previous_assignee_id"),
        reason=reason,
        note=note,
    )
    _flush(db)
    # After commit, the API asks the orchestrator to re-evaluate the project (see api/v1/tasks).
    return task


def _person_name(db: Session, user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return "Someone"
    user = db.get(User, user_id)
    return user.display_name if user else "Someone"


def _notify_for_transition(
    db: Session,
    p: Principal,
    task: Task,
    action: Action,
    *,
    previous_assignee: str | None,
    reason: str | None,
    note: str | None,
) -> None:
    """Tell the right people about a change, in the same transaction as the change."""
    who = _person_name(db, p.user_id)
    common = {
        "organization_id": task.organization_id,
        "task_id": task.id,
        "project_id": task.project_id,
    }
    if action is Action.REQUEST_COMPLETION:
        if task.status is TaskStatus.PENDING_REVIEW:
            body = "Waiting for your review."
            if note and note.strip():
                body = f"Their note: “{note.strip()}” " + body
            notify_team_managers(
                db,
                team_id=task.team_id,
                kind=NotificationKind.COMPLETION_SUBMITTED,
                title=f"{who} completed {task.title}",
                body=body,
                **common,
            )
        else:
            notify_team_managers(
                db,
                team_id=task.team_id,
                kind=NotificationKind.COMPLETION_SUBMITTED,
                title=f"{who} completed {task.title}",
                body="No review was required; the task is completed.",
                **common,
            )
    elif action is Action.APPROVE_COMPLETION and task.assigned_to:
        notify(
            db,
            recipient_id=task.assigned_to,
            kind=NotificationKind.COMPLETION_APPROVED,
            title=f"{who} approved {task.title}",
            body="The task is now completed.",
            **common,
        )
    elif action is Action.REJECT_COMPLETION and task.assigned_to:
        notify(
            db,
            recipient_id=task.assigned_to,
            kind=NotificationKind.COMPLETION_REJECTED,
            title=f"{task.title} needs more work",
            body=f"{who}: “{reason}”",
            **common,
        )
    elif action is Action.BLOCK:
        notify_team_managers(
            db,
            team_id=task.team_id,
            kind=NotificationKind.TASK_BLOCKED,
            title=f"{task.title} is blocked",
            body=f"{who}: “{reason}”",
            **common,
        )
    elif action is Action.DECLINE:
        notify_team_managers(
            db,
            team_id=task.team_id,
            kind=NotificationKind.TASK_DECLINED,
            title=f"{who} declined {task.title}",
            body=f"Reason: “{reason}”. The task is back in the pool.",
            **common,
        )


def _record_evidence(
    db: Session, p: Principal, task: Task, *, note: str | None, link: str | None
) -> dict:
    note, link = _clean(note), _clean(link)
    if task.evidence_policy is EvidencePolicy.NOTE and not note:
        raise RuleViolationError(
            "This task needs a short completion note.", code="evidence_required"
        )
    if task.evidence_policy is EvidencePolicy.LINK and not link:
        raise RuleViolationError(
            "This task needs a link as evidence (for example the merged pull request).",
            code="evidence_required",
        )
    recorded = []
    if note:
        db.add(
            TaskCompletionEvidence(
                task_id=task.id, submitted_by=p.user_id, kind=EvidenceKind.NOTE, content=note
            )
        )
        recorded.append("NOTE")
    if link:
        db.add(
            TaskCompletionEvidence(
                task_id=task.id,
                submitted_by=p.user_id,
                kind=EvidenceKind.LINK,
                content=_validate_link(link),
            )
        )
        recorded.append("LINK")
    return {"evidence": recorded} if recorded else {}
