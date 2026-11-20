"""Organizations, teams, users, team memberships and login sessions."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import created_at_col, str_enum, uuid_pk


class UserRole(enum.StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"


class MembershipRole(enum.StrEnum):
    MEMBER = "MEMBER"
    MANAGER = "MANAGER"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # Demo data must always be clearly labelled (CLAUDE.md section 19).
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_teams_org_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    memberships: Mapped[list["TeamMembership"]] = relationship(back_populates="team")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    # Stored lower-case; globally unique in v1 (single organization per deployment).
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Max tasks this person may actively hold (ASSIGNED/ACCEPTED/IN_PROGRESS/BLOCKED). D4.
    wip_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    memberships: Mapped[list["TeamMembership"]] = relationship(back_populates="user")

    __table_args__ = (
        Index("ix_users_organization_id", "organization_id"),
        CheckConstraint("username = lower(username)", name="username_lowercase"),
        CheckConstraint("wip_limit BETWEEN 0 AND 20", name="wip_limit_range"),
    )


class TeamMembership(Base):
    """A user's membership of a team. MANAGER membership defines a manager's scope."""

    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_memberships_team_user"),
        Index("ix_team_memberships_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    membership_role: Mapped[MembershipRole] = mapped_column(
        str_enum(MembershipRole, "membership_role"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()

    team: Mapped[Team] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class UserSession(Base):
    """Server-side login session. Only a SHA-256 hash of the cookie token is stored."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # The CSRF token is only useful together with the HttpOnly session cookie.
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
