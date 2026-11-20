"""Request/response models for authentication and people. No secrets ever appear here."""

import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.models import MembershipRole, UserRole

T = TypeVar("T")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    is_demo: bool
    timezone: str


class TeamMembershipOut(BaseModel):
    team_id: uuid.UUID
    team_name: str
    membership_role: MembershipRole


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole
    organization: OrganizationOut
    teams: list[TeamMembershipOut]
    csrf_token: str = Field(description="Send as X-CSRF-Token on every state-changing request.")


class EmployeeSummary(BaseModel):
    id: uuid.UUID
    display_name: str
    role: UserRole
    membership_role: MembershipRole
    is_active: bool


class EmployeeOut(BaseModel):
    id: uuid.UUID
    display_name: str
    role: UserRole
    is_active: bool
    teams: list[TeamMembershipOut]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
