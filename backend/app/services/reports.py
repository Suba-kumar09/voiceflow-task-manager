"""Team reports for managers: one source for the screen, voice answers and the daily digest.

Always scoped to the caller's managed teams (admins: the whole organisation) and always
states the period and time zone, as CLAUDE.md 4.11 requires.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.principal import Principal
from app.models import (
    ACTIVE_HOLD_STATUSES,
    MembershipRole,
    Organization,
    Task,
    TaskStatus,
    TaskStatusHistory,
    TeamMembership,
    User,
)
from app.models.common import utcnow
from app.services.errors import PermissionDeniedError

Period = Literal["today", "week"]
OPEN = (
    TaskStatus.UNASSIGNED,
    TaskStatus.ASSIGNED,
    TaskStatus.ACCEPTED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.BLOCKED,
    TaskStatus.PENDING_REVIEW,
)
DUE_SOON_HOURS = 24


@dataclass
class TaskLine:
    id: str
    key: str | None
    title: str
    assignee: str | None
    due_at: datetime | None
    status: str


@dataclass
class PersonLoad:
    id: str
    name: str
    active: int
    limit: int

    @property
    def state(self) -> str:
        if self.active > self.limit:
            return "overloaded"
        if self.active == self.limit:
            return "at limit"
        return "free" if self.active == 0 else "has capacity"


@dataclass
class TeamSummary:
    period: Period
    period_label: str
    timezone: str
    start: datetime
    completed: int
    in_progress: int
    blocked: int
    awaiting_review: int
    open_unassigned: int
    overdue: list[TaskLine] = field(default_factory=list)
    due_soon: list[TaskLine] = field(default_factory=list)
    people: list[PersonLoad] = field(default_factory=list)

    @property
    def overloaded(self) -> list[PersonLoad]:
        return [x for x in self.people if x.state == "overloaded"]

    @property
    def free(self) -> list[PersonLoad]:
        return [x for x in self.people if x.state in ("free", "has capacity")]


def _team_ids(db: Session, p: Principal) -> list[uuid.UUID] | None:
    """None = whole organisation (admin)."""
    if p.is_admin:
        return None
    if not p.managed_team_ids:
        raise PermissionDeniedError("Team reports are for managers.")
    return list(p.managed_team_ids)


def period_start(now_local: datetime, period: Period) -> datetime:
    day_start = datetime.combine(now_local.date(), time(0, 0), tzinfo=now_local.tzinfo)
    return day_start if period == "today" else day_start - timedelta(days=now_local.weekday())


def summary(
    db: Session, p: Principal, period: Period = "today", *, now: datetime | None = None
) -> TeamSummary:
    teams = _team_ids(db, p)
    org = db.get(Organization, p.organization_id)
    tz = org.timezone if org else "UTC"
    now = now or utcnow()
    local = now.astimezone(ZoneInfo(tz))
    start = period_start(local, period)

    def scoped(stmt):
        stmt = stmt.where(Task.organization_id == p.organization_id)
        return stmt if teams is None else stmt.where(Task.team_id.in_(teams))

    counts = dict(db.execute(scoped(select(Task.status, func.count()).group_by(Task.status))).all())
    completed = db.execute(
        scoped(
            select(func.count(func.distinct(TaskStatusHistory.task_id)))
            .join(Task, Task.id == TaskStatusHistory.task_id)
            .where(
                TaskStatusHistory.to_status == TaskStatus.COMPLETED,
                TaskStatusHistory.occurred_at >= start,
            )
        )
    ).scalar_one()

    names = dict(
        db.execute(
            select(User.id, User.display_name).where(User.organization_id == p.organization_id)
        ).all()
    )

    def line(t: Task) -> TaskLine:
        return TaskLine(
            str(t.id), t.external_key, t.title, names.get(t.assigned_to), t.due_at, t.status.value
        )

    dated = (
        db.execute(
            scoped(
                select(Task)
                .where(Task.status.in_(OPEN), Task.due_at.is_not(None))
                .order_by(Task.due_at)
            )
        )
        .scalars()
        .all()
    )
    overdue = [line(t) for t in dated if t.due_at < now]
    soon = [line(t) for t in dated if now <= t.due_at <= now + timedelta(hours=DUE_SOON_HOURS)]

    members_stmt = (
        select(User)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(
            TeamMembership.membership_role == MembershipRole.MEMBER,
            User.is_active.is_(True),
            User.organization_id == p.organization_id,
        )
        .distinct()
        .order_by(User.display_name)
    )
    if teams is not None:
        members_stmt = members_stmt.where(TeamMembership.team_id.in_(teams))
    members = db.execute(members_stmt).scalars().all()
    loads = (
        dict(
            db.execute(
                select(Task.assigned_to, func.count())
                .where(
                    Task.assigned_to.in_([u.id for u in members]),
                    Task.status.in_(ACTIVE_HOLD_STATUSES),
                )
                .group_by(Task.assigned_to)
            ).all()
        )
        if members
        else {}
    )

    return TeamSummary(
        period=period,
        period_label="today" if period == "today" else "this week",
        timezone=tz,
        start=start,
        completed=completed,
        in_progress=sum(
            counts.get(s, 0)
            for s in (TaskStatus.ASSIGNED, TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS)
        ),
        blocked=counts.get(TaskStatus.BLOCKED, 0),
        awaiting_review=counts.get(TaskStatus.PENDING_REVIEW, 0),
        open_unassigned=counts.get(TaskStatus.UNASSIGNED, 0),
        overdue=overdue,
        due_soon=soon,
        people=[
            PersonLoad(str(u.id), u.display_name, loads.get(u.id, 0), u.wip_limit) for u in members
        ],
    )


def completed_between(db: Session, p: Principal, start: datetime, end: datetime) -> int:
    """Tasks that reached COMPLETED in [start, end) within the caller's scope."""
    teams = _team_ids(db, p)
    stmt = (
        select(func.count(func.distinct(TaskStatusHistory.task_id)))
        .join(Task, Task.id == TaskStatusHistory.task_id)
        .where(
            Task.organization_id == p.organization_id,
            TaskStatusHistory.to_status == TaskStatus.COMPLETED,
            TaskStatusHistory.occurred_at >= start,
            TaskStatusHistory.occurred_at < end,
        )
    )
    if teams is not None:
        stmt = stmt.where(Task.team_id.in_(teams))
    return db.execute(stmt).scalar_one()


# ----------------------------------------------------------------------------- spoken forms


def _names(items: list[str], limit: int = 4) -> str:
    items = items[:limit]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def summary_speech(s: TeamSummary) -> str:
    when = "Today" if s.period == "today" else "This week"
    parts = [
        f"{when} ({s.timezone} time), {s.completed} task{'s were' if s.completed != 1 else ' was'} completed.",
        f"{s.in_progress} in progress, {s.awaiting_review} awaiting your review and {s.blocked} blocked.",
    ]
    if s.overdue:
        parts.append(
            f"{len(s.overdue)} overdue: "
            + _names([f"{t.title} ({t.assignee or 'not assigned'})" for t in s.overdue])
            + "."
        )
    else:
        parts.append("Nothing is overdue.")
    if s.due_soon:
        parts.append(f"{len(s.due_soon)} due in the next 24 hours.")
    if s.overloaded:
        parts.append("Overloaded: " + _names([x.name for x in s.overloaded]) + ".")
    return " ".join(parts)


def overdue_speech(s: TeamSummary) -> str:
    if not s.overdue:
        return "Nothing is overdue right now."
    by_person: dict[str, list[str]] = {}
    for t in s.overdue:
        by_person.setdefault(t.assignee or "Not assigned", []).append(t.title)
    return f"{len(s.overdue)} overdue task{'s' if len(s.overdue) != 1 else ''}. " + " ".join(
        f"{who}: {_names(titles)}." for who, titles in by_person.items()
    )


def workload_speech(s: TeamSummary) -> str:
    if not s.people:
        return "There is no one in your teams yet."
    over = [f"{x.name} ({x.active} of {x.limit})" for x in s.overloaded]
    full = [x.name for x in s.people if x.state == "at limit"]
    free = [x.name for x in s.free]
    parts = []
    parts.append(("Overloaded: " + _names(over) + ".") if over else "No one is overloaded.")
    if full:
        parts.append("At their limit: " + _names(full) + ".")
    parts.append(
        ("Has room for more work: " + _names(free) + ".") if free else "No one has spare capacity."
    )
    return " ".join(parts)


def completed_speech(s: TeamSummary) -> str:
    return f"{s.completed} task{'s were' if s.completed != 1 else ' was'} completed {s.period_label} ({s.timezone} time)."
