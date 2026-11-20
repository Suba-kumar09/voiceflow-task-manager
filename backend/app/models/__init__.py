"""ORM models. Import every model here so Alembic sees the full metadata."""

from app.models.audit import AuditEvent, AuditOutcome
from app.models.identity import (
    MembershipRole,
    Organization,
    Team,
    TeamMembership,
    User,
    UserRole,
    UserSession,
)
from app.models.tasks import (
    ACTIVE_HOLD_STATUSES,
    AssignmentEndReason,
    AssignmentSource,
    EvidenceKind,
    EvidencePolicy,
    IdempotencyRecord,
    Project,
    ProjectStatus,
    Task,
    TaskAssignment,
    TaskCompletionEvidence,
    TaskPriority,
    TaskStatus,
    TaskStatusHistory,
)

__all__ = [
    "ACTIVE_HOLD_STATUSES",
    "AssignmentEndReason",
    "AssignmentSource",
    "AuditEvent",
    "AuditOutcome",
    "EvidenceKind",
    "EvidencePolicy",
    "IdempotencyRecord",
    "MembershipRole",
    "Organization",
    "Project",
    "ProjectStatus",
    "Task",
    "TaskAssignment",
    "TaskCompletionEvidence",
    "TaskPriority",
    "TaskStatus",
    "TaskStatusHistory",
    "Team",
    "TeamMembership",
    "User",
    "UserRole",
    "UserSession",
]
