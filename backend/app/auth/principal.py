"""The authenticated caller ("principal") and FastAPI dependencies that enforce it."""

import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import find_active_session
from app.core.config import get_settings
from app.db.session import get_db
from app.models import MembershipRole, TeamMembership, UserRole

CSRF_HEADER = "X-CSRF-Token"


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: UserRole
    session_id: uuid.UUID
    csrf_token: str
    member_team_ids: frozenset[uuid.UUID]
    managed_team_ids: frozenset[uuid.UUID]

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN


def _not_authenticated() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in or session expired.")


def get_principal(request: Request, db: Annotated[Session, Depends(get_db)]) -> Principal:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name, "")
    found = find_active_session(db, token, settings)
    if found is None:
        raise _not_authenticated()
    sess, user = found
    memberships = db.execute(
        select(TeamMembership.team_id, TeamMembership.membership_role).where(
            TeamMembership.user_id == user.id
        )
    ).all()
    return Principal(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        session_id=sess.id,
        csrf_token=sess.csrf_token,
        member_team_ids=frozenset(t for t, _ in memberships),
        managed_team_ids=frozenset(t for t, r in memberships if r is MembershipRole.MANAGER),
    )


def require_csrf(
    request: Request, principal: Annotated[Principal, Depends(get_principal)]
) -> Principal:
    """For state-changing requests: the CSRF header must match the session's token."""
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not secrets.compare_digest(sent, principal.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token.")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
MutatingPrincipal = Annotated[Principal, Depends(require_csrf)]
