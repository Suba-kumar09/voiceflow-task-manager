"""Create and read in-app notifications. Written in the caller's transaction, so a
notification exists only if the change it describes was committed."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import MembershipRole, Notification, NotificationKind, TeamMembership, User
from app.models.common import utcnow


def notify(
    db: Session,
    *,
    organization_id: uuid.UUID,
    recipient_id: uuid.UUID,
    kind: NotificationKind,
    title: str,
    body: str = "",
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> None:
    db.add(
        Notification(
            organization_id=organization_id,
            recipient_user_id=recipient_id,
            kind=kind,
            title=title[:200],
            body=body,
            task_id=task_id,
            project_id=project_id,
        )
    )


def team_manager_ids(db: Session, team_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.execute(
            select(TeamMembership.user_id)
            .join(User, User.id == TeamMembership.user_id)
            .where(
                TeamMembership.team_id == team_id,
                TeamMembership.membership_role == MembershipRole.MANAGER,
                User.is_active.is_(True),
            )
            .order_by(TeamMembership.user_id)
        ).scalars()
    )


def notify_team_managers(
    db: Session, *, organization_id, team_id, kind, title, body="", task_id=None, project_id=None
) -> None:
    for manager_id in team_manager_ids(db, team_id):
        notify(
            db,
            organization_id=organization_id,
            recipient_id=manager_id,
            kind=kind,
            title=title,
            body=body,
            task_id=task_id,
            project_id=project_id,
        )


def list_for(
    db: Session, user_id: uuid.UUID, *, unread_only: bool, limit: int, offset: int
) -> tuple[list[Notification], int, int]:
    base = select(Notification).where(Notification.recipient_user_id == user_id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_user_id == user_id, Notification.read_at.is_(None))
    ).scalar_one()
    rows = db.execute(
        base.order_by(Notification.created_at.desc(), Notification.id).limit(limit).offset(offset)
    ).scalars()
    return list(rows), total, unread


def mark_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    """Only the recipient can mark their own notification. Returns False if not theirs."""
    result = db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.recipient_user_id == user_id)
        .values(read_at=func.coalesce(Notification.read_at, utcnow()))
    )
    return result.rowcount == 1
