"""Shared queries for user/team read models."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, Team, TeamMembership, User
from app.schemas.identity import MeOut, OrganizationOut, TeamMembershipOut


def memberships_of(db: Session, user_id: uuid.UUID) -> list[TeamMembershipOut]:
    rows = db.execute(
        select(Team.id, Team.name, TeamMembership.membership_role)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(TeamMembership.user_id == user_id)
        .order_by(Team.name)
    ).all()
    return [TeamMembershipOut(team_id=t, team_name=n, membership_role=r) for t, n, r in rows]


def build_me(db: Session, user: User, csrf_token: str) -> MeOut:
    org = db.get(Organization, user.organization_id)
    if org is None:  # impossible while the foreign key exists; fail loudly, never silently
        raise RuntimeError(f"User {user.id} references a missing organization.")
    return MeOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        organization=OrganizationOut(
            id=org.id, name=org.name, is_demo=org.is_demo, timezone=org.timezone
        ),
        teams=memberships_of(db, user.id),
        csrf_token=csrf_token,
    )
