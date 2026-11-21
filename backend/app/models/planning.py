"""Skills, task dependencies and notifications (Phase 4)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import created_at_col, str_enum, uuid_pk


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


class Skill(Base):
    """An organization's skill catalog. Names are matched case-insensitively."""

    __tablename__ = "skills"
    __table_args__ = (
        Index("uq_skills_org_lower_name", "organization_id", text("lower(name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = _fk("organizations.id", ondelete="RESTRICT")
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class UserSkill(Base):
    __tablename__ = "user_skills"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", name="uq_user_skills_user_skill"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    skill_id: Mapped[uuid.UUID] = _fk("skills.id")


class TaskRequiredSkill(Base):
    __tablename__ = "task_required_skills"
    __table_args__ = (
        UniqueConstraint("task_id", "skill_id", name="uq_task_required_skills_task_skill"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = _fk("tasks.id")
    skill_id: Mapped[uuid.UUID] = _fk("skills.id", ondelete="RESTRICT")


class TaskDependency(Base):
    """`task_id` cannot start until `depends_on_task_id` is COMPLETED."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependencies_pair"),
        CheckConstraint("task_id <> depends_on_task_id", name="not_self"),
        Index("ix_task_dependencies_depends_on", "depends_on_task_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = _fk("tasks.id")
    depends_on_task_id: Mapped[uuid.UUID] = _fk("tasks.id")


class NotificationKind(enum.StrEnum):
    TASK_ASSIGNED = "TASK_ASSIGNED"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED"
    COMPLETION_APPROVED = "COMPLETION_APPROVED"
    COMPLETION_REJECTED = "COMPLETION_REJECTED"
    TASK_BLOCKED = "TASK_BLOCKED"
    TASK_DECLINED = "TASK_DECLINED"
    PROJECT_SUMMARY = "PROJECT_SUMMARY"
    NEEDS_DECISION = "NEEDS_DECISION"
    EXTENSION_REQUESTED = "EXTENSION_REQUESTED"
    EXTENSION_APPROVED = "EXTENSION_APPROVED"
    EXTENSION_DENIED = "EXTENSION_DENIED"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    DAILY_DIGEST = "DAILY_DIGEST"


class ReminderLog(Base):
    """One row per reminder actually sent, so the worker never sends the same one twice.
    `key` identifies the occasion, e.g. "<task id>:<due date>" or "digest:<local date>"."""

    __tablename__ = "reminder_log"
    __table_args__ = (UniqueConstraint("user_id", "kind", "key", name="uq_reminder_log_once"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    kind: Mapped[NotificationKind] = mapped_column(
        str_enum(NotificationKind, "reminder_kind"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Notification(Base):
    """In-app notification. Voice delivery (Phase 6+) reads from here; it never changes tasks."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient_unread", "recipient_user_id", "read_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = _fk("organizations.id", ondelete="RESTRICT")
    recipient_user_id: Mapped[uuid.UUID] = _fk("users.id")
    kind: Mapped[NotificationKind] = mapped_column(
        str_enum(NotificationKind, "notification_kind"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks.id", nullable=True, ondelete="SET NULL")
    project_id: Mapped[uuid.UUID | None] = _fk("projects.id", nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = created_at_col()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
