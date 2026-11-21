"""Deadline extension requests and progress updates (Phase 8)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import created_at_col, str_enum, uuid_pk


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


class ExtensionStatus(enum.StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DeadlineExtensionRequest(Base):
    """An employee's request for a later due date. The deadline changes only on approval."""

    __tablename__ = "deadline_extension_requests"
    __table_args__ = (
        # At most one open request per task.
        Index(
            "uq_extension_one_pending_per_task",
            "task_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_extension_requests_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = _fk("organizations.id", ondelete="RESTRICT")
    task_id: Mapped[uuid.UUID] = _fk("tasks.id")
    requested_by: Mapped[uuid.UUID] = _fk("users.id")
    previous_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ExtensionStatus] = mapped_column(
        str_enum(ExtensionStatus, "extension_status"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class TaskProgressUpdate(Base):
    """A progress report from the assignee (percent and/or a short note)."""

    __tablename__ = "task_progress_updates"
    __table_args__ = (
        Index("ix_task_progress_updates_task", "task_id", "created_at"),
        CheckConstraint(
            "percent IS NULL OR (percent >= 0 AND percent <= 100)", name="percent_range"
        ),
        CheckConstraint("percent IS NOT NULL OR note IS NOT NULL", name="has_content"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = _fk("tasks.id")
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    percent: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
