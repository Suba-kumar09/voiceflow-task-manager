"""Data retention (Phase 10): delete records that are only kept for a while.

What is deleted, and when (settings in app/core/config.py, VOICEFLOW_RETENTION_*):
- agent traces (they hold what people said) .......... after `retention_trace_days` (30)
- read notifications .................................. after `retention_notification_days` (90)
- finished sign-in sessions (expired or signed out) ... 1 day after they ended
- expired voice confirmations ("say yes to ...") ...... 1 day after they expired
- stored replies for retried requests (idempotency) ... after 7 days (retries come within seconds)

Never deleted here: tasks, projects, assignments, history, extension requests, progress updates,
the reminder log (it stops a reminder being sent twice) and audit events (the authoritative
record of who changed what). Unread notifications are kept until they are read.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AgentTrace, Notification, UserSession
from app.models.agent import AgentPendingAction
from app.models.common import utcnow
from app.models.tasks import IdempotencyRecord

ENDED_GRACE = timedelta(days=1)
IDEMPOTENCY_DAYS = 7


@dataclass
class RetentionStats:
    traces: int = 0
    notifications: int = 0
    sessions: int = 0
    pending_actions: int = 0
    idempotency_records: int = 0


def run(db: Session, now: datetime | None = None) -> RetentionStats:
    """Delete everything past its retention period. The caller commits."""
    s = get_settings()
    now = now or utcnow()
    stats = RetentionStats()
    stats.traces = _delete(
        db,
        delete(AgentTrace).where(
            AgentTrace.created_at < now - timedelta(days=s.retention_trace_days)
        ),
    )
    stats.notifications = _delete(
        db,
        delete(Notification).where(
            Notification.read_at.is_not(None),
            Notification.read_at < now - timedelta(days=s.retention_notification_days),
        ),
    )
    stats.sessions = _delete(
        db,
        delete(UserSession).where(
            or_(
                UserSession.expires_at < now - ENDED_GRACE,
                UserSession.revoked_at < now - ENDED_GRACE,
            )
        ),
    )
    stats.pending_actions = _delete(
        db, delete(AgentPendingAction).where(AgentPendingAction.expires_at < now - ENDED_GRACE)
    )
    stats.idempotency_records = _delete(
        db,
        delete(IdempotencyRecord).where(
            IdempotencyRecord.created_at < now - timedelta(days=IDEMPOTENCY_DAYS)
        ),
    )
    return stats


def _delete(db: Session, stmt) -> int:
    return db.execute(stmt.execution_options(synchronize_session=False)).rowcount or 0
