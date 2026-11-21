"""Reminders: due soon, overdue and the managers' daily digest.

Run by the background worker (app/workers/reminders.py). Guarantees:
- each reminder is sent at most once (`reminder_log` unique (user, kind, key));
- nobody is notified during their quiet hours — the reminder is simply sent on a later run;
- moving a deadline (approved extension) creates a new occasion, so a fresh reminder follows.
The caller commits.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.principal import Principal
from app.models import (
    ACTIVE_HOLD_STATUSES,
    MembershipRole,
    NotificationKind,
    Organization,
    ReminderLog,
    Task,
    TeamMembership,
    User,
    UserRole,
)
from app.models.common import utcnow
from app.services import reports
from app.services.notifications import notify

DIGEST_HOUR = 9  # local time


@dataclass
class RunStats:
    due_soon: int = 0
    overdue: int = 0
    digests: int = 0
    deferred_quiet: int = 0


def in_quiet_hours(user: User, local_now: datetime) -> bool:
    if user.quiet_start is None or user.quiet_end is None or user.quiet_start == user.quiet_end:
        return False
    t = local_now.time().replace(tzinfo=None)
    start, end = user.quiet_start, user.quiet_end
    return start <= t < end if start < end else (t >= start or t < end)  # may cross midnight


def _claim(db: Session, user_id, kind: NotificationKind, key: str) -> bool:
    """Record the reminder; False if it was already sent (concurrency-safe)."""
    result = db.execute(
        insert(ReminderLog)
        .values(user_id=user_id, kind=kind, key=key)
        .on_conflict_do_nothing(constraint="uq_reminder_log_once")
        .returning(ReminderLog.id)
    )
    return result.first() is not None


def _local(dt: datetime, tz: str) -> str:
    local = dt.astimezone(ZoneInfo(tz))
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')}, {local.strftime('%I:%M %p').lstrip('0')}"


def run(db: Session, *, now: datetime | None = None) -> RunStats:
    now = now or utcnow()
    stats = RunStats()
    users = {u.id: u for u in db.execute(select(User).where(User.is_active.is_(True))).scalars()}
    org_tz = dict(db.execute(select(Organization.id, Organization.timezone)).all())

    def send(user_id, kind, key, **note) -> bool:
        user = users.get(user_id)
        if user is None:
            return False
        if in_quiet_hours(user, now.astimezone(ZoneInfo(org_tz.get(user.organization_id, "UTC")))):
            stats.deferred_quiet += 1
            return False
        if not _claim(db, user_id, kind, key):
            return False
        notify(db, organization_id=user.organization_id, recipient_id=user_id, kind=kind, **note)
        return True

    managers_by_team: dict = {}
    for team_id, uid in db.execute(
        select(TeamMembership.team_id, TeamMembership.user_id).where(
            TeamMembership.membership_role == MembershipRole.MANAGER
        )
    ).all():
        managers_by_team.setdefault(team_id, []).append(uid)

    # ---- due soon / overdue (tasks someone is holding)
    tasks = (
        db.execute(
            select(Task).where(
                Task.status.in_(ACTIVE_HOLD_STATUSES),
                Task.due_at.is_not(None),
                Task.assigned_to.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    for t in tasks:
        key = f"{t.id}:{t.due_at.isoformat()}"
        common = {"task_id": t.id, "project_id": t.project_id}
        owner = users.get(t.assigned_to)
        if t.due_at < now:
            if send(
                t.assigned_to,
                NotificationKind.OVERDUE,
                key,
                title=f"{t.title} is overdue",
                body=f"It was due {_local(t.due_at, t.timezone)}. If you need more time, ask for an extension.",
                **common,
            ):
                stats.overdue += 1
            for m in managers_by_team.get(t.team_id, []):
                send(
                    m,
                    NotificationKind.OVERDUE,
                    key,
                    title=f"{t.title} is overdue",
                    body=f"Held by {owner.display_name if owner else 'someone'}; it was due {_local(t.due_at, t.timezone)}.",
                    **common,
                )
        elif t.due_at <= now + timedelta(hours=reports.DUE_SOON_HOURS):
            if send(
                t.assigned_to,
                NotificationKind.DUE_SOON,
                key,
                title=f"{t.title} is due soon",
                body=f"Due {_local(t.due_at, t.timezone)}.",
                **common,
            ):
                stats.due_soon += 1

    # ---- daily digest for managers, once per local day after DIGEST_HOUR
    manager_ids = {uid for ids in managers_by_team.values() for uid in ids}
    for uid in sorted(manager_ids, key=str):
        user = users.get(uid)
        if user is None:
            continue
        tz = org_tz.get(user.organization_id, "UTC")
        local = now.astimezone(ZoneInfo(tz))
        if local.time() < time(DIGEST_HOUR, 0):
            continue
        p = _principal_for(db, user)
        s = reports.summary(db, p, "today", now=now)
        yesterday_done = reports.completed_between(db, p, s.start - timedelta(days=1), s.start)
        body = (
            f"Completed yesterday: {yesterday_done}. In progress: {s.in_progress}. "
            f"Awaiting your review: {s.awaiting_review}. Blocked: {s.blocked}. Overdue: {len(s.overdue)}. "
            f"Due in the next 24 hours: {len(s.due_soon)}."
            + (f" Overloaded: {', '.join(x.name for x in s.overloaded)}." if s.overloaded else "")
        )
        if send(
            uid,
            NotificationKind.DAILY_DIGEST,
            f"digest:{local.date().isoformat()}",
            title=f"Daily summary for {local.strftime('%A')} {local.day} {local.strftime('%B')}",
            body=body,
        ):
            stats.digests += 1

    db.flush()
    return stats


def _principal_for(db: Session, user: User) -> Principal:
    rows = db.execute(
        select(TeamMembership.team_id, TeamMembership.membership_role).where(
            TeamMembership.user_id == user.id
        )
    ).all()
    return Principal(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role if isinstance(user.role, UserRole) else UserRole(user.role),
        session_id=user.id,
        csrf_token="worker",  # noqa: S106 - not a secret; the worker has no browser session
        member_team_ids=frozenset(t for t, _ in rows),
        managed_team_ids=frozenset(t for t, r in rows if r is MembershipRole.MANAGER),
    )
