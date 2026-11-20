"""Task request/response models. Priority is always explicit: the system never infers it."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.models import EvidencePolicy, TaskPriority, TaskStatus


def _not_blank(v: str) -> str:
    if not v.strip():
        raise ValueError("must not be blank")
    return v


class TaskCreate(BaseModel):
    team_id: uuid.UUID
    title: str = Field(max_length=200)
    priority: TaskPriority  # required: never guessed
    project_id: uuid.UUID | None = None
    external_key: str | None = Field(default=None, max_length=40)
    description: str = Field(default="", max_length=5000)
    acceptance_criteria: str = Field(default="", max_length=5000)
    due_at: AwareDatetime | None = None  # must include a timezone offset
    estimated_effort_hours: Decimal | None = Field(default=None, gt=0, le=1000)
    requires_approval: bool = False
    evidence_policy: EvidencePolicy = EvidencePolicy.NONE
    publish: bool = Field(default=True, description="true = task pool (UNASSIGNED), false = DRAFT")

    _title = field_validator("title")(_not_blank)


class TaskUpdate(BaseModel):
    version: int = Field(ge=1, description="The version you last saw (optimistic concurrency).")
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    acceptance_criteria: str | None = Field(default=None, max_length=5000)
    priority: TaskPriority | None = None
    due_at: AwareDatetime | None = None
    estimated_effort_hours: Decimal | None = Field(default=None, gt=0, le=1000)
    requires_approval: bool | None = None
    evidence_policy: EvidencePolicy | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return _not_blank(v) if v is not None else v


class AssignIn(BaseModel):
    assignee_id: uuid.UUID
    override_capacity: bool = Field(
        default=False, description="Manager override of the employee's workload limit (audited)."
    )


class ReassignIn(AssignIn):
    reason: str = Field(min_length=1, max_length=1000)


class TransitionIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=5000)
    link: str | None = Field(default=None, max_length=2000)


class PersonRef(BaseModel):
    id: uuid.UUID
    display_name: str


class TaskOut(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    project_id: uuid.UUID | None
    external_key: str | None
    title: str
    description: str
    acceptance_criteria: str
    priority: TaskPriority
    status: TaskStatus
    assignee: PersonRef | None
    created_by: uuid.UUID
    due_at: datetime | None
    timezone: str
    estimated_effort_hours: Decimal | None
    requires_approval: bool
    evidence_policy: EvidencePolicy
    version: int
    created_at: datetime
    updated_at: datetime
    depends_on: list[str] = Field(default_factory=list, description="Keys of predecessor tasks")
    required_skills: list[str] = Field(default_factory=list)


class CurrentTaskOut(BaseModel):
    task: TaskOut | None


class HistoryEntryOut(BaseModel):
    action: str
    from_status: TaskStatus | None
    to_status: TaskStatus
    actor_user_id: uuid.UUID | None
    reason: str | None
    details: dict
    occurred_at: datetime
