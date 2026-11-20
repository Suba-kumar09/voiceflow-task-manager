"""Audit events: authoritative record of who did what, to what, and with what outcome.

Kept separate from agent traces (CLAUDE.md section 14). Never store secrets in `details`.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import created_at_col, str_enum, uuid_pk


class AuditOutcome(enum.StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_occurred", "organization_id", "occurred_at"),
        Index("ix_audit_events_actor", "actor_user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = created_at_col()
    # Nullable: e.g. a failed login for an unknown username has no organization/actor.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[AuditOutcome] = mapped_column(
        str_enum(AuditOutcome, "audit_outcome"), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
