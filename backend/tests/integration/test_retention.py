"""Retention deletes only what is past its period, and never audit events or tasks."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.models import AgentTrace, AuditEvent, Notification, NotificationKind, UserSession
from app.models.common import utcnow
from app.services import retention

pytestmark = pytest.mark.integration


def count(db, model, *where) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def test_retention_deletes_only_expired_records(as_user, world, db):
    emp = as_user("emp_web_1")
    for text in ("what is my task", "show my notifications", "help"):
        assert (
            emp.client.post(
                "/api/v1/voice/turns",
                json={"text": text},
                headers={"X-CSRF-Token": emp.csrf},
            ).status_code
            == 200
        )
    user_id = world["emp_web_1"]
    traces = (
        select(AgentTrace.id).where(AgentTrace.user_id == user_id).order_by(AgentTrace.created_at)
    )
    ids = list(db.execute(traces).scalars())
    assert len(ids) == 3
    now = utcnow()
    # One trace is 31 days old (past 30), one is 29 days old (kept), one is new.
    db.execute(
        update(AgentTrace)
        .where(AgentTrace.id == ids[0])
        .values(created_at=now - timedelta(days=31))
    )
    db.execute(
        update(AgentTrace)
        .where(AgentTrace.id == ids[1])
        .values(created_at=now - timedelta(days=29))
    )
    # Sessions that were signed out two days ago are deleted.
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id)
        .values(revoked_at=now - timedelta(days=2))
    )
    audits_before = count(db, AuditEvent)
    db.commit()

    stats = retention.run(db, now=now)
    db.commit()

    assert stats.traces >= 1
    assert count(db, AgentTrace, AgentTrace.id == ids[0]) == 0
    assert count(db, AgentTrace, AgentTrace.id.in_(ids[1:])) == 2
    assert count(db, UserSession, UserSession.user_id == user_id) == 0
    assert count(db, AuditEvent) == audits_before  # the audit trail is never pruned


def test_read_notifications_go_after_90_days_unread_ones_stay(db, world):
    now = utcnow()

    def note(title, created_days, read_days):
        n = Notification(
            organization_id=world["org_a"],
            recipient_user_id=world["emp_web_1"],
            kind=NotificationKind.TASK_ASSIGNED,
            title=title,
            created_at=now - timedelta(days=created_days),
            read_at=None if read_days is None else now - timedelta(days=read_days),
        )
        db.add(n)
        db.flush()
        return n.id

    old_read = note("read long ago", 120, 100)
    recent_read = note("read last month", 40, 30)
    old_unread = note("never read", 400, None)
    db.commit()

    stats = retention.run(db, now=now)
    db.commit()

    assert stats.notifications == 1
    assert count(db, Notification, Notification.id == old_read) == 0
    assert count(db, Notification, Notification.id.in_([recent_read, old_unread])) == 2
