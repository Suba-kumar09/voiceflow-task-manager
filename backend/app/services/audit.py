"""Write audit events. The caller owns the transaction (commit happens with the change)."""

import uuid

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.models import AuditEvent, AuditOutcome


def record_audit(
    db: Session,
    *,
    action: str,
    outcome: AuditOutcome,
    organization_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            action=action,
            outcome=outcome,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            request_id=request_id_var.get(),
            details=details or {},
        )
    )
