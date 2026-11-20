"""Project, backlog and notification request/response models."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, Field

from app.models import EvidencePolicy, NotificationKind, ProjectStatus


class ProjectCreate(BaseModel):
    team_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ProjectOut(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    description: str
    status: ProjectStatus
    created_at: datetime
    backlog_approved_at: datetime | None
    started_at: datetime | None


class BacklogTask(BaseModel):
    key: str = Field(min_length=1, max_length=40, description="Your ID for the task, e.g. T12")
    title: str = Field(max_length=200)
    priority: str | None = Field(description="LOW, MEDIUM, HIGH or URGENT — never guessed")
    description: str = Field(default="", max_length=5000)
    acceptance_criteria: str = Field(default="", max_length=5000)
    due_at: AwareDatetime | None = None
    estimated_effort_hours: Decimal | None = Field(default=None, gt=0, le=1000)
    required_skills: list[str] = Field(default_factory=list, max_length=20)
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    requires_approval: bool = False
    evidence_policy: EvidencePolicy = EvidencePolicy.NONE


class BacklogIn(BaseModel):
    tasks: list[BacklogTask] = Field(max_length=1000)


class ValidationOut(BaseModel):
    ok: bool
    errors: list[str]
    warnings: list[str]
    task_count: int
    can_start_immediately: list[str]


class PlanItemOut(BaseModel):
    task_id: uuid.UUID
    key: str
    title: str
    priority: str
    outcome: str
    reason: str
    assignee_id: uuid.UUID | None = None
    assignee_name: str | None = None


class EvaluationOut(BaseModel):
    project_id: uuid.UUID
    assigned: list[dict]
    waiting_for_capacity: list[dict]
    needs_decision: list[dict]
    skipped: list[dict]


class ProgressOut(BaseModel):
    project_id: uuid.UUID
    name: str
    status: str
    total: int
    completed: int
    percent_complete: int
    in_progress: int
    ready_to_assign: int
    waiting_on_dependencies: int
    blocked_by_issue: int
    awaiting_review: int
    needs_decision: list[dict]
    draft: int
    cancelled: int


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: NotificationKind
    title: str
    body: str
    task_id: uuid.UUID | None
    project_id: uuid.UUID | None
    created_at: datetime
    read: bool


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int
    limit: int
    offset: int
