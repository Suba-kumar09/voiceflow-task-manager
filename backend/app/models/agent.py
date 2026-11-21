"""Agent harness state: pending confirmations and per-turn traces.

Traces explain HOW a request was handled; audit_events remain the record of WHAT changed.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import created_at_col, uuid_pk


class AgentPendingAction(Base):
    """A proposed change waiting for the user's spoken "yes". Single use, short-lived."""

    __tablename__ = "agent_pending_actions"
    __table_args__ = (Index("ix_agent_pending_actions_user_open", "user_id", "consumed_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tool: Mapped[str] = mapped_column(String(60), nullable=False)
    args: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # What is still missing before we can ask for confirmation ("note", "reason") or None.
    awaiting: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = created_at_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # executed | cancelled | superseded | failed
    outcome: Mapped[str | None] = mapped_column(String(20))


class AgentTrace(Base):
    __tablename__ = "agent_traces"
    __table_args__ = (Index("ix_agent_traces_org_created", "organization_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()
    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # voice | text
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stt_ms: Mapped[int | None] = mapped_column(Integer)
    intent: Mapped[str] = mapped_column(String(60), nullable=False)
    slots: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tool: Mapped[str | None] = mapped_column(String(60))
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    speech: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text)
    total_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
