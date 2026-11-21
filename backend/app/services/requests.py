"""Deadline extension requests and progress updates.

The deadline changes ONLY when an authorized manager approves (CLAUDE.md 4.10).
Services never commit; the caller commits once.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.dates import spoken
from app.auth.principal import Principal
from app.models import (
    AuditOutcome,
    DeadlineExtensionRequest,
    ExtensionStatus,
    NotificationKind,
    Task,
    TaskProgressUpdate,
    TaskStatus,
    TaskStatusHistory,
    User,
)
from app.models.common import utcnow
from app.services.audit import record_audit
from app.services.errors import ConflictError, NotFoundError, RuleViolationError
from app.services.notifications import notify, notify_team_managers
from app.services.tasks import service as task_svc
from app.services.tasks.lifecycle import ActorKind

ACTIVE = (TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)


def _name(db: Session, user_id) -> str:
    u = db.get(User, user_id)
    return u.display_name if u else "Someone"


def _own_active_task(db: Session, p: Principal, task_id: uuid.UUID, action: str) -> Task:
    task = task_svc._load_task(db, p, task_id, lock=True)
    if task.assigned_to != p.user_id:
        task_svc._deny(db, p, task.id, action, "Only the person assigned to this task can do that.")
    if task.status not in ACTIVE:
        raise ConflictError(
            f"This task is {task.status.value.lower().replace('_', ' ')}.",
            code="invalid_transition",
        )
    return task


# ----------------------------------------------------------------------------- extensions


def request_extension(
    db: Session, p: Principal, task_id: uuid.UUID, new_due: datetime, reason: str
) -> DeadlineExtensionRequest:
    task = _own_active_task(db, p, task_id, "extension_request")
    reason = (reason or "").strip()
    if not reason:
        raise RuleViolationError("Please give a reason for the extension.", code="reason_required")
    if new_due.tzinfo is None:
        raise RuleViolationError("The new date must include a timezone.")
    if new_due <= utcnow():
        raise RuleViolationError("The new date must be in the future.", code="date_invalid")
    if task.due_at and new_due <= task.due_at:
        raise RuleViolationError(
            f"The new date must be later than the current due date, {spoken(task.due_at, task.timezone)}.",
            code="date_invalid",
        )
    req = DeadlineExtensionRequest(
        organization_id=task.organization_id,
        task_id=task.id,
        requested_by=p.user_id,
        previous_due_at=task.due_at,
        requested_due_at=new_due,
        reason=reason,
        status=ExtensionStatus.PENDING,
    )
    db.add(req)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "There is already a pending extension request for this task.", code="extension_pending"
        ) from exc
    record_audit(
        db,
        action="task.extension_request",
        outcome=AuditOutcome.SUCCESS,
        organization_id=task.organization_id,
        actor_user_id=p.user_id,
        target_type="task",
        target_id=task.id,
        details={"requested_due_at": new_due.isoformat()},
    )
    notify_team_managers(
        db,
        organization_id=task.organization_id,
        team_id=task.team_id,
        kind=NotificationKind.EXTENSION_REQUESTED,
        title=f"{_name(db, p.user_id)} asks for more time on {task.title}",
        body=f"Until {spoken(new_due, task.timezone)}. Reason: “{reason}”",
        task_id=task.id,
        project_id=task.project_id,
    )
    db.flush()
    return req


def decide_extension(
    db: Session, p: Principal, request_id: uuid.UUID, *, approve: bool, note: str | None = None
) -> DeadlineExtensionRequest:
    req = db.execute(
        select(DeadlineExtensionRequest)
        .where(DeadlineExtensionRequest.id == request_id)
        .with_for_update()
    ).scalar_one_or_none()
    if req is None or req.organization_id != p.organization_id:
        raise NotFoundError("Extension request not found.")
    task = task_svc._load_task(db, p, req.task_id, lock=True)
    if ActorKind.MANAGER not in task_svc.actor_kinds(p, task):
        task_svc._deny(
            db, p, task.id, "extension_decide", "Only a manager of this team can decide."
        )
    if req.status is not ExtensionStatus.PENDING:
        raise ConflictError(f"This request was already {req.status.value.lower()}.")

    note = (note or "").strip() or None
    req.status = ExtensionStatus.APPROVED if approve else ExtensionStatus.DENIED
    req.decided_by, req.decided_at, req.decision_note = p.user_id, utcnow(), note
    if approve:
        task.due_at = req.requested_due_at
        db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=task.status,
                to_status=task.status,
                action="extend_deadline",
                actor_user_id=p.user_id,
                reason=req.reason,
                details={
                    "previous_due_at": req.previous_due_at.isoformat()
                    if req.previous_due_at
                    else None,
                    "new_due_at": req.requested_due_at.isoformat(),
                },
            )
        )
    record_audit(
        db,
        action="task.extension_" + ("approve" if approve else "deny"),
        outcome=AuditOutcome.SUCCESS,
        organization_id=task.organization_id,
        actor_user_id=p.user_id,
        target_type="task",
        target_id=task.id,
        details={"request_id": str(req.id)},
    )
    when = spoken(req.requested_due_at, task.timezone)
    notify(
        db,
        organization_id=task.organization_id,
        recipient_id=req.requested_by,
        kind=NotificationKind.EXTENSION_APPROVED if approve else NotificationKind.EXTENSION_DENIED,
        title=(
            f"More time approved for {task.title}"
            if approve
            else f"Extension for {task.title} was not approved"
        ),
        body=(f"New due date: {when}." if approve else "The due date stays the same.")
        + (f" {_name(db, p.user_id)}: “{note}”" if note else ""),
        task_id=task.id,
        project_id=task.project_id,
    )
    db.flush()
    return req


def list_extensions(
    db: Session, p: Principal, *, pending_only: bool = True, project_id: uuid.UUID | None = None
) -> list[tuple[DeadlineExtensionRequest, Task]]:
    stmt = (
        select(DeadlineExtensionRequest, Task)
        .join(Task, Task.id == DeadlineExtensionRequest.task_id)
        .where(DeadlineExtensionRequest.organization_id == p.organization_id)
    )
    if pending_only:
        stmt = stmt.where(DeadlineExtensionRequest.status == ExtensionStatus.PENDING)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if not p.is_admin:
        # Managers: their teams' requests. Everyone: their own requests.
        own = DeadlineExtensionRequest.requested_by == p.user_id
        stmt = (
            stmt.where(own | Task.team_id.in_(p.managed_team_ids))
            if p.managed_team_ids
            else stmt.where(own)
        )
    return list(db.execute(stmt.order_by(DeadlineExtensionRequest.created_at)).all())


def pending_by_task(
    db: Session, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DeadlineExtensionRequest]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(DeadlineExtensionRequest).where(
            DeadlineExtensionRequest.task_id.in_(task_ids),
            DeadlineExtensionRequest.status == ExtensionStatus.PENDING,
        )
    ).scalars()
    return {r.task_id: r for r in rows}


# ----------------------------------------------------------------------------- progress


def report_progress(
    db: Session, p: Principal, task_id: uuid.UUID, *, percent: int | None, note: str | None
) -> TaskProgressUpdate:
    task = _own_active_task(db, p, task_id, "progress")
    note = (note or "").strip() or None
    if percent is None and note is None:
        raise RuleViolationError("Give a percentage, a short note, or both.")
    if percent is not None and not 0 <= percent <= 100:
        raise RuleViolationError("Progress must be between 0 and 100 percent.")
    row = TaskProgressUpdate(task_id=task.id, user_id=p.user_id, percent=percent, note=note)
    db.add(row)
    record_audit(
        db,
        action="task.progress",
        outcome=AuditOutcome.SUCCESS,
        organization_id=task.organization_id,
        actor_user_id=p.user_id,
        target_type="task",
        target_id=task.id,
        details={"percent": percent},
    )
    db.flush()
    return row


def latest_progress(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, TaskProgressUpdate]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(TaskProgressUpdate)
        .where(TaskProgressUpdate.task_id.in_(task_ids))
        .order_by(TaskProgressUpdate.task_id, TaskProgressUpdate.created_at.desc())
        .distinct(TaskProgressUpdate.task_id)
    ).scalars()
    return {r.task_id: r for r in rows}
