"""Server-side sessions. The browser holds a random token; the database holds its SHA-256."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import User, UserSession
from app.models.common import utcnow

# Refresh last_seen_at at most this often, to avoid a write on every request.
_TOUCH_INTERVAL = timedelta(minutes=1)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NewSession:
    token: str  # goes into the HttpOnly cookie; never stored
    csrf_token: str
    expires_at: datetime


def create_session(
    db: Session,
    user: User,
    settings: Settings,
    ip_address: str | None,
    user_agent: str | None,
) -> NewSession:
    now = utcnow()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = now + timedelta(hours=settings.session_absolute_hours)
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            csrf_token=csrf,
            user_id=user.id,
            expires_at=expires,
            last_seen_at=now,
            ip_address=(ip_address or "")[:64] or None,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    return NewSession(token=token, csrf_token=csrf, expires_at=expires)


def find_active_session(
    db: Session, token: str, settings: Settings
) -> tuple[UserSession, User] | None:
    """Return the session and its active user, or None if missing/expired/idle/revoked."""
    if not token or len(token) > 128:
        return None
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == _hash_token(token))
    ).first()
    if row is None:
        return None
    sess, user = row
    now = utcnow()
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if (
        sess.revoked_at is not None
        or sess.expires_at <= now
        or now - sess.last_seen_at > idle_limit
        or not user.is_active
    ):
        return None
    if now - sess.last_seen_at > _TOUCH_INTERVAL:
        sess.last_seen_at = now
        db.commit()
    return sess, user


def revoke_session(db: Session, session_id: uuid.UUID) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
