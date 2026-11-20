"""Current user, team rosters and employee profiles (all scoped by policy)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.deps import enforce
from app.api.v1.people import build_me, memberships_of
from app.auth.policy import can_view_employee, can_view_team_roster
from app.auth.principal import CurrentPrincipal
from app.db.session import get_db
from app.models import Team, TeamMembership, User
from app.schemas.identity import EmployeeOut, EmployeeSummary, MeOut, Page

router = APIRouter(tags=["people"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/users/me", response_model=MeOut)
def me(principal: CurrentPrincipal, db: DB) -> MeOut:
    user = db.get(User, principal.user_id)
    if user is None:  # deleted between session check and now
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in or session expired.")
    return build_me(db, user, principal.csrf_token)


@router.get("/teams/{team_id}/employees", response_model=Page[EmployeeSummary])
def team_employees(
    team_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EmployeeSummary]:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    enforce(
        can_view_team_roster(principal, team.organization_id, team.id),
        db,
        principal,
        action="team.roster.view",
        target_type="team",
        target_id=team.id,
    )

    base = (
        select(User, TeamMembership.membership_role)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(TeamMembership.team_id == team.id, User.organization_id == principal.organization_id)
    )
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(User.display_name, User.id).limit(limit).offset(offset)).all()
    items = [
        EmployeeSummary(
            id=u.id,
            display_name=u.display_name,
            role=u.role,
            membership_role=r,
            is_active=u.is_active,
        )
        for u, r in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/employees/{employee_id}", response_model=EmployeeOut)
def employee(employee_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> EmployeeOut:
    target = db.get(User, employee_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found.")
    teams = memberships_of(db, target.id)
    enforce(
        can_view_employee(principal, target.id, target.organization_id, [t.team_id for t in teams]),
        db,
        principal,
        action="employee.view",
        target_type="employee",
        target_id=target.id,
    )
    return EmployeeOut(
        id=target.id,
        display_name=target.display_name,
        role=target.role,
        is_active=target.is_active,
        teams=teams,
    )
