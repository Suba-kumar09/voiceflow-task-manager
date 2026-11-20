"""Shared API helpers: turning policy decisions into audited HTTP errors."""

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.policy import Decision
from app.auth.principal import Principal
from app.auth.throttle import LoginThrottle
from app.models import AuditOutcome
from app.services.audit import record_audit


def enforce(
    decision: Decision,
    db: Session,
    principal: Principal,
    *,
    action: str,
    target_type: str,
    target_id: object,
) -> None:
    """Raise 403/404 for a non-ALLOW decision, recording the denial in the audit log first."""
    if decision is Decision.ALLOW:
        return
    record_audit(
        db,
        action=action,
        outcome=AuditOutcome.DENIED,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        target_type=target_type,
        target_id=str(target_id),
        details={"decision": decision.value},
    )
    db.commit()
    if decision is Decision.NOT_FOUND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{target_type.capitalize()} not found.")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this.")


def get_login_throttle(request: Request) -> LoginThrottle:
    return request.app.state.login_throttle
