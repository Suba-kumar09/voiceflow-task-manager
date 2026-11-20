"""Projects (minimal until Phase 4), tasks, assignments, status history, evidence."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import created_at_col, str_enum, uuid_pk


class ProjectStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class TaskStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    PENDING_REVIEW = "PENDING_REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskPriority(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class EvidencePolicy(enum.StrEnum):
    NONE = "NONE"
    NOTE = "NOTE"
    LINK = "LINK"
    MANAGER_APPROVAL = "MANAGER_APPROVAL"


class AssignmentSource(enum.StrEnum):
    MANUAL = "MANUAL"
    ORCHESTRATOR = "ORCHESTRATOR"


class AssignmentEndReason(enum.StrEnum):
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REASSIGNED = "REASSIGNED"
    DECLINED = "DECLINED"
    UNASSIGNED = "UNASSIGNED"


class EvidenceKind(enum.StrEnum):
    NOTE = "NOTE"
    LINK = "LINK"


# Statuses in which a task is held by an employee and counts against their WIP limit.
ACTIVE_HOLD_STATUSES = (
    TaskStatus.ASSIGNED,
    TaskStatus.ACCEPTED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.BLOCKED,
)
# Statuses in which assigned_to must be set (COMPLETED keeps who did the work).
OWNED_STATUSES = (*ACTIVE_HOLD_STATUSES, TaskStatus.PENDING_REVIEW, TaskStatus.COMPLETED)

_owned_sql = ", ".join(f"'{s.value}'" for s in OWNED_STATUSES)


def _uuid_fk(target: str, *, nullable: bool, ondelete: str = "RESTRICT") -> Mapped:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_projects_org_name"),
        Index("ix_projects_team_id", "team_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = _uuid_fk("organizations.id", nullable=False)
    team_id: Mapped[uuid.UUID] = _uuid_fk("teams.id", nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        str_enum(ProjectStatus, "project_status"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = _uuid_fk("users.id", nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_org_team_status", "organization_id", "team_id", "status"),
        Index("ix_tasks_assigned_to_status", "assigned_to", "status"),
        Index("ix_tasks_project_id", "project_id"),
        # Backlog keys (e.g. "T12") are unique within a project.
        Index(
            "uq_tasks_project_external_key",
            "project_id",
            "external_key",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL AND external_key IS NOT NULL"),
        ),
        # The database itself refuses an owner/status mismatch.
        CheckConstraint(
            f"(status IN ({_owned_sql}) AND assigned_to IS NOT NULL)"
            " OR (status IN ('DRAFT', 'UNASSIGNED') AND assigned_to IS NULL)"
            " OR status = 'CANCELLED'",
            name="assignee_matches_status",
        ),
        CheckConstraint(
            "estimated_effort_hours IS NULL OR estimated_effort_hours > 0", name="effort_positive"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = _uuid_fk("organizations.id", nullable=False)
    team_id: Mapped[uuid.UUID] = _uuid_fk("teams.id", nullable=False)
    project_id: Mapped[uuid.UUID | None] = _uuid_fk("projects.id", nullable=True)
    external_key: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[TaskPriority] = mapped_column(
        str_enum(TaskPriority, "task_priority"), nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus, "task_status"), nullable=False)
    created_by: Mapped[uuid.UUID] = _uuid_fk("users.id", nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = _uuid_fk("users.id", nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_effort_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_policy: Mapped[EvidencePolicy] = mapped_column(
        str_enum(EvidencePolicy, "evidence_policy"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Optimistic concurrency: every UPDATE checks and increments `version`.
    __mapper_args__ = {"version_id_col": version}


class TaskAssignment(Base):
    """Assignment history. At most one open (ended_at IS NULL) row per task — enforced by index."""

    __tablename__ = "task_assignments"
    __table_args__ = (
        Index(
            "uq_task_assignments_one_open_per_task",
            "task_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_task_assignments_assignee", "assignee_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = _uuid_fk("tasks.id", nullable=False, ondelete="CASCADE")
    assignee_id: Mapped[uuid.UUID] = _uuid_fk("users.id", nullable=False)
    source: Mapped[AssignmentSource] = mapped_column(
        str_enum(AssignmentSource, "assignment_source"), nullable=False
    )
    assigned_by: Mapped[uuid.UUID | None] = _uuid_fk("users.id", nullable=True)
    assigned_at: Mapped[datetime] = created_at_col()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[AssignmentEndReason | None] = mapped_column(
        str_enum(AssignmentEndReason, "assignment_end_reason")
    )


class TaskStatusHistory(Base):
    """Append-only record of every status change (and reassignment)."""

    __tablename__ = "task_status_history"
    __table_args__ = (Index("ix_task_status_history_task", "task_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = _uuid_fk("tasks.id", nullable=False, ondelete="CASCADE")
    from_status: Mapped[TaskStatus | None] = mapped_column(
        str_enum(TaskStatus, "history_from_status")
    )
    to_status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus, "history_to_status"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = _uuid_fk("users.id", nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = created_at_col()


class TaskCompletionEvidence(Base):
    __tablename__ = "task_completion_evidence"
    __table_args__ = (Index("ix_task_completion_evidence_task", "task_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = _uuid_fk("tasks.id", nullable=False, ondelete="CASCADE")
    submitted_by: Mapped[uuid.UUID] = _uuid_fk("users.id", nullable=False)
    kind: Mapped[EvidenceKind] = mapped_column(
        str_enum(EvidenceKind, "evidence_kind"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = created_at_col()


class IdempotencyRecord(Base):
    """Stored result of a retry-sensitive request, keyed by (actor, Idempotency-Key)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "key", name="uq_idempotency_records_actor_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_user_id: Mapped[uuid.UUID] = _uuid_fk("users.id", nullable=False, ondelete="CASCADE")
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
